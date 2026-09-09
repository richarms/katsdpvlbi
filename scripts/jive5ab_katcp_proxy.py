#!/usr/bin/env python3
"""KATCP proxy server for jive5ab."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
from typing import Optional, Tuple

from aiokatcp import DeviceServer, FailReply, Sensor

logger = logging.getLogger(__name__)

WRITING_SUFFIX = ".writing"
HANDOFF_VERSION = 1
RECORD_STOP_TIMEOUT = 10.0


# ---------------- low-level jive helpers ----------------

def _as_text(value) -> str:
    """Convert KATCP string/bytes arguments to plain text."""

    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="strict")
    return str(value)

async def jive_cmd(port: int, cmd: str, timeout: float = 1.0) -> str:
    """Send *cmd* to the jive5ab control port and return the raw reply."""

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection("127.0.0.1", port), timeout=timeout
    )
    try:
        writer.write((cmd.strip() + ";\n").encode("ascii"))
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
        return data.decode("ascii", errors="ignore")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def parse_status(reply: str) -> str:
    """Extract the state from a ``status?`` reply."""

    m = re.search(r"!status\?\s+\d+\s:\s(\w+)\s:\s(\d+)", reply)
    return m.group(1) if m else "unknown"


def parse_protocol(reply: str) -> str:
    """Extract the network protocol from a ``net_protocol?`` reply."""

    m = re.search(r"!net_protocol\?\s+\d+\s:\s([A-Za-z0-9_]+)", reply)
    return m.group(1) if m else "unknown"


def parse_port(reply: str) -> str:
    """Extract the configured port from a ``net_port?`` reply."""

    m = re.search(r"!net_port\?\s+\d+\s:\s(.+?)\s;", reply)
    return m.group(1).strip() if m else "unknown"


def parse_reply_status(reply: str):
    """Extract status code + detail from a jive5ab reply line."""

    m = re.search(r"!\S+\s*=?\s*(\d+)(?:\s*:\s*(.*?))?\s*;", reply, re.DOTALL)
    if not m:
        raise ValueError(f"Could not parse jive5ab reply: {reply!r}")
    code = int(m.group(1))
    detail = (m.group(2) or "").strip()
    return code, detail


def require_success(reply: str, command: str) -> None:
    """Raise RuntimeError if jive5ab reports a non-zero status code."""

    code, detail = parse_reply_status(reply)
    if code != 0:
        if detail:
            raise RuntimeError(f"{command} failed with code {code}: {detail}")
        raise RuntimeError(f"{command} failed with code {code}")


def validate_path_component(value: str) -> str:
    """Accept one unambiguous capture or stream identifier, without normalising it."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) or ".." in value:
        raise ValueError(f"Invalid capture/stream identifier: {value!r}")
    return value


def capture_block_to_vdif_scan(capture_block_id: str, stream_name: str) -> Tuple[str, str]:
    """Return the capture ID and stable, stream-specific jive5ab scan name."""
    if not re.fullmatch(r"[0-9]+", capture_block_id):
        raise ValueError(f"Invalid capture block ID (decimal digits required): {capture_block_id!r}")
    cbid = capture_block_id
    return cbid, f"{cbid}_{validate_path_component(stream_name)}"


def close_capture(product_root: Path, cbid: str, stream_name: str) -> Path:
    """Publish a closed raw capture after jive5ab has stopped successfully.

    The directory rename is the handoff. Neither an unfinished directory nor a
    capture.json file inside one authorises postprocessing.
    """
    final_dir = product_root.with_name("raw")
    if final_dir.exists():
        raise FileExistsError(f"Closed capture already exists: {final_dir}")
    _, scan_name = capture_block_to_vdif_scan(cbid, stream_name)
    flatten_vdif_recording_layout(product_root, scan_name)
    shards = []
    for path in sorted(product_root.iterdir()):
        if path.name == "capture.json":
            continue  # A previous close may have failed immediately before rename.
        if path.is_symlink() or not path.is_file() or not re.fullmatch(
            re.escape(scan_name) + r"\.[0-9]+", path.name
        ):
            raise ValueError(f"Unexpected recorder output: {path}")
        size = path.stat().st_size
        if size == 0:
            raise ValueError(f"Empty recorder shard: {path}")
        shards.append({"name": path.name, "size_bytes": size})
    if not shards:
        raise ValueError(f"Cannot close an empty capture: {product_root}")
    manifest = {
        "version": HANDOFF_VERSION,
        "capture_block_id": cbid,
        "stream_name": stream_name,
        "status": "closed",
        "shards": shards,
    }
    (product_root / "capture.json").write_text(json.dumps(manifest, indent=2) + "\n")
    product_root.rename(final_dir)
    return final_dir


def first_disk_path_from_env() -> str:
    """Return first configured DISK_PATHS entry, defaulting to /var/kat/data."""

    raw = os.environ.get("DISK_PATHS", "/var/kat/data")
    for path in (part.strip() for part in raw.split(",")):
        if path:
            return path
    return "/var/kat/data"


def flatten_vdif_recording_layout(product_root: Path, scan_name: str) -> bool:
    """Flatten legacy ``<product_root>/<scan_name>/<scan_name>.*`` output in-place.

    jive5ab creates a scan-named subdirectory beneath the configured disk root for
    VBS recordings. We want ``product_root`` itself to be the in-progress product
    directory, so move any nested capture files up one level and remove the extra
    directory. Returns ``True`` if a nested directory was flattened.
    """

    nested_dir = product_root / scan_name
    if not nested_dir.is_dir():
        return False
    for child in nested_dir.iterdir():
        destination = product_root / child.name
        if destination.exists():
            raise FileExistsError(f"Cannot flatten {nested_dir}: destination exists: {destination}")
        child.rename(destination)
    nested_dir.rmdir()
    return True


# ---------------- aiokatcp server ----------------

class Jive5abServer(DeviceServer):
    VERSION = "jive5ab-katcp-proxy 0.3"
    BUILD_STATE = "unknown"
    DESCRIPTION = "KATCP proxy that forwards control to a local jive5ab instance"

    def __init__(self, host: str, port: int, jive_port: int):
        super().__init__(host, port)
        self.jive_port = jive_port

        self.s_state = self._make_sensor(str, "jive5ab-state", "jive5ab state", "unknown")
        self.s_bytes = self._make_sensor(int, "jive5ab-bytes", "bytes written", 0)
        self.s_proto = self._make_sensor(str, "jive5ab-protocol", "network protocol", "unknown")
        self.s_nport = self._make_sensor(str, "jive5ab-port", "net_port", "unknown")
        self.s_error = self._make_sensor(str, "jive5ab-error", "last proxy error", "")

        self._active_capture: Optional[Tuple[Path, str, str]] = None
        self._capture_lock = asyncio.Lock()

    def _make_sensor(self, sensor_type, name, description, initial):
        """Create a sensor, initialise it and add it to the server."""

        sensor = Sensor(sensor_type, name, description)
        sensor.set_value(initial)
        # Older aiokatcp only accepts one sensor per add()
        self.sensors.add(sensor)
        return sensor

    async def start(self):
        await super().start()

    async def stop(self):
        await super().stop()

    async def _poll_once(self) -> None:
        try:
            reply = await jive_cmd(self.jive_port, "status?")
            self.s_state.set_value(parse_status(reply))
            self.s_error.set_value("")
        except (asyncio.TimeoutError, OSError) as err:
            self.s_error.set_value(f"status?: {err}")
            logger.error("status? failed: %s", err)
        try:
            reply = await jive_cmd(self.jive_port, "net_protocol?")
            self.s_proto.set_value(parse_protocol(reply))
        except (asyncio.TimeoutError, OSError) as err:
            self.s_error.set_value(f"net_protocol?: {err}")
            logger.error("net_protocol? failed: %s", err)
        try:
            reply = await jive_cmd(self.jive_port, "net_port?")
            self.s_nport.set_value(parse_port(reply))
        except (asyncio.TimeoutError, OSError) as err:
            self.s_error.set_value(f"net_port?: {err}")
            logger.error("net_port? failed: %s", err)

    # ---------------- KATCP requests (name-based) ----------------

    async def request_status(self, ctx):
        """Return compact status line."""
        await self._poll_once()
        line = f"{self.s_state.value} {self.s_bytes.value}B {self.s_proto.value} {self.s_nport.value}"
        return "ok", line

    async def request_set_protocol(self, ctx, proto, rcv="33554432", snd="33554432", threads="4"):
        """Set network protocol. Usage: ?set-protocol <udp|udps|udpsnor> [<rcv> <snd> <threads>]"""
        proto = _as_text(proto)
        rcv = _as_text(rcv)
        snd = _as_text(snd)
        threads = _as_text(threads)
        proto_l = proto.lower()
        if proto_l not in ("udp", "udps", "udpsnor"):
            raise FailReply("protocol must be udp, udps or udpsnor")
        try:
            if proto_l in ("udps", "udpsnor"):
                cmd = f"net_protocol = {proto_l} : {int(rcv)} : {int(snd)} : {int(threads)}"
            else:
                cmd = "net_protocol = udp"
        except ValueError as err:
            raise FailReply(str(err))
        try:
            rep = await jive_cmd(self.jive_port, cmd)
            require_success(rep, "net_protocol")
            await self._poll_once()
            return "ok", ""
        except (asyncio.TimeoutError, OSError, RuntimeError, ValueError) as err:
            self.s_error.set_value(str(err))
            logger.error("set-protocol failed: %s", err)
            raise FailReply(str(err))

    async def request_set_port(self, ctx, destination):
        """Set net_port. Usage: ?set-port <port | mcast@port> (e.g. 50000 or 239.1.2.3@50000)"""
        destination = _as_text(destination)
        try:
            if "@" in destination:
                ip, port = destination.split("@", 1)
                int(port)
            else:
                int(destination)
        except ValueError:
            raise FailReply("invalid port")
        try:
            rep = await jive_cmd(self.jive_port, f"net_port = {destination}")
            require_success(rep, "net_port")
            await self._poll_once()
            return "ok", ""
        except (asyncio.TimeoutError, OSError, RuntimeError, ValueError) as err:
            self.s_error.set_value(str(err))
            logger.error("set-port failed: %s", err)
            raise FailReply(str(err))

    async def request_set_disks(self, ctx, *paths):
        """Configure FlexBuff mountpoints. Usage: ?set-disks /mnt/disk0 [: /mnt/disk1 : ...]"""
        if not paths:
            raise FailReply("provide at least one disk path")
        # send comma-separated list
        joined = ":".join(_as_text(path) for path in paths)
        try:
            rep = await jive_cmd(self.jive_port, f"set_disks = {joined}")
            require_success(rep, "set_disks")
            return "ok", ""
        except (asyncio.TimeoutError, OSError, RuntimeError, ValueError) as err:
            self.s_error.set_value(str(err))
            logger.error("set-disks failed: %s", err)
            raise FailReply(str(err))

    async def request_record_start(self, ctx, scan_name):
        """Start VBS recording (shrapnel). Usage: ?record-start <scan_name>"""
        scan_name = _as_text(scan_name)
        if not scan_name:
            raise FailReply("scan_name required")
        try:
            rep = await jive_cmd(self.jive_port, f"record = on:{scan_name}")
            require_success(rep, "record")
            # Many builds do not echo bytes for record?, but poll anyway:
            await self._poll_once()
            return "ok", ""
        except (asyncio.TimeoutError, OSError, RuntimeError, ValueError) as err:
            self.s_error.set_value(str(err))
            logger.error("record-start failed: %s", err)
            raise FailReply(str(err))

    async def request_capture_init(self, ctx, capture_block_id):
        """Controller compatibility alias. Usage: ?capture-init <capture_block_id>"""
        async with self._capture_lock:
            if self._active_capture is not None:
                raise FailReply("A capture is already active; close it before starting another")
            try:
                stream_name = os.environ.get("VLBI_STREAM_NAME", "")
                cbid, scan_name = capture_block_to_vdif_scan(_as_text(capture_block_id), stream_name)
                capture_root = Path(first_disk_path_from_env()) / ".vlbi" / cbid / stream_name
                if (capture_root / "raw").exists():
                    raise FileExistsError(f"Closed capture already exists: {capture_root / 'raw'}")
                product_root = capture_root / ("raw" + WRITING_SUFFIX)
                product_root.mkdir(parents=True, exist_ok=False)
                rep = await jive_cmd(self.jive_port, f"set_disks = {product_root}")
                require_success(rep, "set_disks")
                reply = await self.request_record_start(ctx, scan_name)
                self._active_capture = (product_root, cbid, stream_name)
                return reply
            except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as err:
                self.s_error.set_value(str(err))
                logger.error("capture-init failed: %s", err)
                raise FailReply(str(err))

    async def _wait_record_stopped(self) -> None:
        """Confirm completion after jive5ab accepts an asynchronous stop."""
        while True:
            reply = await jive_cmd(self.jive_port, "record?")
            _, detail = parse_reply_status(reply)
            require_success(reply, "record?")
            state = detail.partition(":")[0].strip()
            if state == "off":
                return
            if state != "on":
                raise ValueError(f"Unexpected record state while stopping: {reply!r}")
            await asyncio.sleep(0.1)

    async def request_record_stop(self, ctx):
        """Stop VBS recording. Usage: ?record-stop"""
        try:
            rep = await jive_cmd(self.jive_port, "record = off")
            code, detail = parse_reply_status(rep)
            # The pinned jive5ab returns 1 even when stopping successfully. It
            # only permits handoff once record? explicitly confirms "off".
            if code == 1:
                try:
                    await asyncio.wait_for(self._wait_record_stopped(), RECORD_STOP_TIMEOUT)
                except asyncio.TimeoutError as err:
                    raise RuntimeError("Timed out waiting for jive5ab to confirm record off") from err
            elif code != 0 and not (code == 6 and detail == "Not doing record"):
                if detail:
                    raise RuntimeError(f"record failed with code {code}: {detail}")
                raise RuntimeError(f"record failed with code {code}")
            await self._poll_once()
            return "ok", ""
        except (asyncio.TimeoutError, OSError, RuntimeError, ValueError) as err:
            self.s_error.set_value(str(err))
            logger.error("record-stop failed: %s", err)
            raise FailReply(str(err))

    async def request_capture_done(self, ctx):
        """Controller compatibility alias. Usage: ?capture-done"""
        async with self._capture_lock:
            reply = await self.request_record_stop(ctx)
            if self._active_capture is None:
                return reply
            try:
                final_dir = close_capture(*self._active_capture)
            except (OSError, ValueError) as err:
                self.s_error.set_value(str(err))
                raise FailReply(str(err))
            self._active_capture = None
            logger.info("Closed raw VDIF capture: %s", final_dir)
            return reply

    async def request_record_status(self, ctx):
        """Query VBS recording status. Usage: ?record-status"""
        try:
            rep = await jive_cmd(self.jive_port, "record?")
            # Some versions reply as: !record? 0 : <state> : <bytes> ;
            # If not parseable, return the raw reply.
            m = re.search(r"!record\?\s+\d+\s:\s(\w+)\s:\s(\d+)", rep)
            if m:
                state, bytes_ = m.group(1), m.group(2)
                return "ok", f"{state} {bytes_}B"
            return "ok", rep.strip()
        except (asyncio.TimeoutError, OSError) as err:
            self.s_error.set_value(str(err))
            logger.error("record-status failed: %s", err)
            raise FailReply(str(err))

    # Keep net2file controls if you still need them
    async def request_net2file_start(self, ctx, output_path="/mnt/disk0/testscan/testscan.vdif"):
        """Start legacy net2file to OUTPUT_PATH."""
        output_path = _as_text(output_path)
        try:
            r = await jive_cmd(self.jive_port, f"net2file = open : {output_path}, w")
            try:
                require_success(r, "net2file open")
            except RuntimeError:
                rep = await jive_cmd(self.jive_port, "net2file = connect")
                require_success(rep, "net2file connect")
                r2 = await jive_cmd(self.jive_port, f"net2file = open : {output_path}, w")
                require_success(r2, "net2file open")
            rep = await jive_cmd(self.jive_port, "net2file = on")
            require_success(rep, "net2file on")
            await self._poll_once()
            return "ok", ""
        except (asyncio.TimeoutError, OSError, RuntimeError, ValueError) as err:
            self.s_error.set_value(str(err))
            logger.error("net2file-start failed: %s", err)
            raise FailReply(str(err))

    async def request_net2file_stop(self, ctx):
        """Stop legacy net2file (off, flush, close)."""
        try:
            rep = await jive_cmd(self.jive_port, "net2file = off")
            require_success(rep, "net2file off")
            rep = await jive_cmd(self.jive_port, "net2file = flush")
            require_success(rep, "net2file flush")
            rep = await jive_cmd(self.jive_port, "net2file = close")
            require_success(rep, "net2file close")
            await self._poll_once()
            return "ok", ""
        except (asyncio.TimeoutError, OSError, RuntimeError, ValueError) as err:
            self.s_error.set_value(str(err))
            logger.error("net2file-stop failed: %s", err)
            raise FailReply(str(err))


# ---------------- CLI ----------------

async def _amain():
    ap = argparse.ArgumentParser(description="aiokatcp proxy for jive5ab")
    ap.add_argument("--katcp-host", default="0.0.0.0")
    ap.add_argument("--katcp-port", type=int, default=7147)
    ap.add_argument("--jive-port", type=int, default=2620)
    args = ap.parse_args()

    server = Jive5abServer(args.katcp_host, args.katcp_port, args.jive_port)
    await server.start()
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()

def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_amain())

if __name__ == "__main__":
    main()
