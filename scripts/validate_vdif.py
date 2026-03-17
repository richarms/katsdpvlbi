#!/usr/bin/env python3
"""Validate recorded VLBI files for basic VDIF structural correctness.

This tool is intentionally lightweight so it can run without external deps.
It checks:
- plain/raw VDIF framing at byte offset 0
- known "record stride" layouts (e.g. 1004-byte records seen from jive udpsreader)

When baseband is available, it also attempts a parser-level open/read.
"""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence


@dataclass
class Header:
    seconds: int
    invalid: int
    legacy: int
    frame_nr: int
    ref_epoch: int
    frame_bytes: int
    version: int
    thread_id: int
    bits_per_sample: int
    station: int


@dataclass
class LayoutCheck:
    ok: bool
    layout: str
    detail: str


def _parse_header(data: bytes, endian: str) -> Header:
    w0, w1, w2, w3 = struct.unpack(endian + "4I", data[:16])
    return Header(
        seconds=w0 & 0x3FFFFFFF,
        invalid=(w0 >> 31) & 0x1,
        legacy=(w0 >> 30) & 0x1,
        frame_nr=w1 & 0x00FFFFFF,
        ref_epoch=(w1 >> 24) & 0x3F,
        frame_bytes=(w2 & 0x00FFFFFF) * 8,
        version=(w2 >> 29) & 0x7,
        thread_id=(w3 >> 16) & 0x3FF,
        bits_per_sample=((w3 >> 26) & 0x1F) + 1,
        station=w3 & 0xFFFF,
    )


def _iter_candidate_files(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    yield child


def _looks_like_vdif_name(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".vdif") or name.endswith(".00000000")


def _check_raw_vdif(path: Path, sample_frames: int = 4000) -> Optional[LayoutCheck]:
    size = path.stat().st_size
    if size < 32:
        return None
    head = path.read_bytes()[:32]
    best: Optional[LayoutCheck] = None
    for endian, label in (("<", "little"), (">", "big")):
        try:
            first = _parse_header(head, endian)
        except struct.error:
            continue
        frame_bytes = first.frame_bytes
        if frame_bytes < 32 or frame_bytes > 16384:
            continue
        if size % frame_bytes != 0:
            continue
        n_frames = size // frame_bytes
        check_count = min(n_frames, sample_frames)
        bad = 0
        invalid = 0
        threads: set[int] = set()
        last_by_thread: dict[int, tuple[int, int]] = {}
        regressions = 0
        with path.open("rb") as fh:
            for _ in range(check_count):
                frame = fh.read(frame_bytes)
                if len(frame) != frame_bytes:
                    bad += 1
                    break
                try:
                    hdr = _parse_header(frame, endian)
                except struct.error:
                    bad += 1
                    break
                if hdr.frame_bytes != frame_bytes:
                    bad += 1
                    break
                if hdr.invalid:
                    invalid += 1
                threads.add(hdr.thread_id)
                key = (hdr.seconds, hdr.frame_nr)
                prev = last_by_thread.get(hdr.thread_id)
                if prev is not None and key < prev:
                    regressions += 1
                last_by_thread[hdr.thread_id] = key
        if bad == 0:
            detail = (
                f"endian={label} frame_bytes={frame_bytes} frames={n_frames} "
                f"threads={sorted(threads)} invalid_frames={invalid} regressions={regressions} "
                f"epoch={first.ref_epoch} version={first.version} station={first.station}"
            )
            candidate = LayoutCheck(True, "raw_vdif", detail)
            if best is None:
                best = candidate
    return best


def _check_stride_layout(
    path: Path, stride: int, endian: str, sample_records: int = 4000
) -> Optional[LayoutCheck]:
    size = path.stat().st_size
    if size < 32 or size % stride != 0:
        return None
    n_records = size // stride
    check_count = min(n_records, sample_records)
    declared_lengths: set[int] = set()
    bad = 0
    invalid = 0
    threads: set[int] = set()
    last_by_thread: dict[int, tuple[int, int]] = {}
    regressions = 0
    with path.open("rb") as fh:
        for _ in range(check_count):
            record = fh.read(stride)
            if len(record) != stride:
                bad += 1
                break
            try:
                hdr = _parse_header(record, endian)
            except struct.error:
                bad += 1
                break
            declared_lengths.add(hdr.frame_bytes)
            if hdr.invalid:
                invalid += 1
            threads.add(hdr.thread_id)
            key = (hdr.seconds, hdr.frame_nr)
            prev = last_by_thread.get(hdr.thread_id)
            if prev is not None and key < prev:
                regressions += 1
            last_by_thread[hdr.thread_id] = key
    if bad != 0:
        return None
    # Keep only obviously sensible layouts.
    if not declared_lengths:
        return None
    if any(length < 32 or length > 16384 for length in declared_lengths):
        return None
    detail = (
        f"record_stride={stride} endian={'little' if endian == '<' else 'big'} "
        f"declared_frame_bytes={sorted(declared_lengths)} records={n_records} "
        f"threads={sorted(threads)} invalid_records={invalid} regressions={regressions}"
    )
    if len(declared_lengths) == 1 and next(iter(declared_lengths)) > stride:
        detail += " (declared frame larger than stored record: likely truncated/wrapped capture)"
    return LayoutCheck(True, "record_stride", detail)


def _baseband_probe(path: Path) -> str:
    try:
        import baseband.vdif  # type: ignore[import-not-found]
    except Exception as exc:
        return f"baseband: unavailable ({exc})"
    try:
        with open(path, "rb") as fh:
            stream = baseband.vdif.open(fh, "rs")
            _ = stream.read(2)
        return "baseband: PASS"
    except Exception as exc:
        return f"baseband: FAIL ({type(exc).__name__}: {exc})"


def _analyse_file(path: Path, show_baseband: bool) -> str:
    out = [f"{path} ({path.stat().st_size} bytes)"]
    raw = _check_raw_vdif(path)
    if raw is not None and raw.ok:
        out.append(f"  raw_vdif: PASS - {raw.detail}")
    else:
        out.append("  raw_vdif: FAIL")
        for stride in (1004, 1012, 1028, 1032):
            probe = _check_stride_layout(path, stride=stride, endian="<")
            if probe is not None:
                out.append(f"  stride_probe: WARN - {probe.detail}")
                break
    if show_baseband:
        out.append(f"  {_baseband_probe(path)}")
    return "\n".join(out)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate VDIF-like output files.")
    parser.add_argument("paths", nargs="+", type=Path, help="File(s) or directory/directories to scan")
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Scan all files under directories (default scans only .vdif and .00000000 files)",
    )
    parser.add_argument(
        "--baseband",
        action="store_true",
        help="Attempt baseband.vdif parser-level open/read if package is available",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files: list[Path] = []
    for path in _iter_candidate_files(args.paths):
        if args.all_files or _looks_like_vdif_name(path):
            files.append(path)
    if not files:
        print("No candidate files found")
        return 1
    failures = 0
    for path in files:
        report = _analyse_file(path, show_baseband=args.baseband)
        print(report)
        if "raw_vdif: FAIL" in report:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
