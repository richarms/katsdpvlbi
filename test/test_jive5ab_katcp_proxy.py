import asyncio
import importlib.util
import json
from unittest.mock import AsyncMock
from pathlib import Path

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "jive5ab_katcp_proxy.py"
_SPEC = importlib.util.spec_from_file_location("jive5ab_katcp_proxy", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
proxy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(proxy)


def test_capture_block_to_vdif_scan_uses_stable_scan_name() -> None:
    cbid, scan_name = proxy.capture_block_to_vdif_scan("1234567890", "sdp_vdif")
    assert cbid == "1234567890"
    assert scan_name == "1234567890_sdp_vdif"


@pytest.mark.parametrize("capture_block_id", ["", "abc/def", r"abc\def", "abc..def", "177_other"])
def test_capture_block_to_vdif_scan_rejects_invalid_paths(capture_block_id: str) -> None:
    with pytest.raises(ValueError):
        proxy.capture_block_to_vdif_scan(capture_block_id, "sdp_vdif")


def test_flatten_vdif_recording_layout_moves_nested_capture_files(tmp_path: Path) -> None:
    product_root = tmp_path / "1776702842_vdif.writing"
    nested = product_root / "1776702842_vdif"
    nested.mkdir(parents=True)
    payload = nested / "1776702842_vdif.00000"
    payload.write_bytes(b"vdif")

    changed = proxy.flatten_vdif_recording_layout(product_root, "1776702842_vdif")

    assert changed is True
    assert not nested.exists()
    assert (product_root / "1776702842_vdif.00000").read_bytes() == b"vdif"


def test_flatten_vdif_recording_layout_is_noop_without_nested_dir(tmp_path: Path) -> None:
    product_root = tmp_path / "1776702842_vdif.writing"
    product_root.mkdir()

    changed = proxy.flatten_vdif_recording_layout(product_root, "1776702842_vdif")

    assert changed is False


@pytest.mark.parametrize("stream", ["", "../escape", "a/b", r"a\b", "a b", "sdp_vdif\n"])
def test_invalid_stream_name(stream: str) -> None:
    with pytest.raises(ValueError):
        proxy.capture_block_to_vdif_scan("177", stream)


def make_raw_writing(tmp_path: Path, stream: str = "sdp_vdif") -> Path:
    writing = tmp_path / ".vlbi" / "177" / stream / "raw.writing"
    nested = writing / f"177_{stream}"
    nested.mkdir(parents=True)
    (nested / f"177_{stream}.00000000").write_bytes(b"vdif")
    return writing


def test_close_capture_publishes_versioned_inventory(tmp_path: Path) -> None:
    writing = make_raw_writing(tmp_path)
    final = proxy.close_capture(writing, "177", "sdp_vdif")
    assert final == tmp_path / ".vlbi/177/sdp_vdif/raw"
    assert not writing.exists()
    assert (final / "177_sdp_vdif.00000000").read_bytes() == b"vdif"
    assert json.loads((final / "capture.json").read_text()) == {
        "version": 1,
        "capture_block_id": "177",
        "stream_name": "sdp_vdif",
        "status": "closed",
        "shards": [{"name": "177_sdp_vdif.00000000", "size_bytes": 4}],
    }


@pytest.mark.parametrize("kind", ["empty", "zero_size", "unexpected", "existing"])
def test_close_capture_rejects_incomplete_or_conflicting_output(tmp_path: Path, kind: str) -> None:
    writing = make_raw_writing(tmp_path)
    shard = writing / "177_sdp_vdif/177_sdp_vdif.00000000"
    if kind == "empty":
        shard.unlink()
    elif kind == "zero_size":
        shard.write_bytes(b"")
    elif kind == "unexpected":
        (writing / "unexpected").write_bytes(b"x")
    else:
        (writing.parent / "raw").mkdir()
    with pytest.raises((ValueError, FileExistsError)):
        proxy.close_capture(writing, "177", "sdp_vdif")
    assert writing.exists()
    assert not (writing.parent / "raw/capture.json").exists()


def test_capture_lifecycle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DISK_PATHS", str(tmp_path))
    monkeypatch.setenv("VLBI_STREAM_NAME", "sdp_vdif")

    async def run():
        server = proxy.Jive5abServer("127.0.0.1", 0, 2620)
        monkeypatch.setattr(server, "_poll_once", AsyncMock())
        jive = AsyncMock(return_value="!record= 0 ;")
        monkeypatch.setattr(proxy, "jive_cmd", jive)
        await server.request_capture_init(None, "177")
        writing = tmp_path / ".vlbi/177/sdp_vdif/raw.writing"
        assert writing.is_dir()
        assert jive.call_args_list[0].args[1] == f"set_disks = {writing}"
        assert jive.call_args_list[1].args[1] == "record = on:177_sdp_vdif"
        with pytest.raises(proxy.FailReply, match="already active"):
            await server.request_capture_init(None, "178")
        nested = writing / "177_sdp_vdif"
        nested.mkdir()
        (nested / "177_sdp_vdif.00000000").write_bytes(b"vdif")
        await server.request_capture_done(None)
        assert not writing.exists()
        assert (writing.parent / "raw/capture.json").exists()
        await server.request_capture_done(None)
        with pytest.raises(proxy.FailReply, match="already exists"):
            await server.request_capture_init(None, "177")
        monkeypatch.setenv("VLBI_STREAM_NAME", "other")
        await server.request_capture_init(None, "177")
        assert (tmp_path / ".vlbi/177/other/raw.writing").is_dir()

    asyncio.run(run())


@pytest.mark.parametrize("reply", ["!record= 1 : ambiguous stop ;", "!record= 4 : error ;"])
def test_failed_stop_does_not_publish_raw(tmp_path: Path, monkeypatch, reply: str) -> None:
    writing = make_raw_writing(tmp_path)

    async def run():
        server = proxy.Jive5abServer("127.0.0.1", 0, 2620)
        server._active_capture = (writing, "177", "sdp_vdif")
        monkeypatch.setattr(server, "_poll_once", AsyncMock())
        monkeypatch.setattr(proxy, "jive_cmd", AsyncMock(return_value=reply))
        with pytest.raises(proxy.FailReply):
            await server.request_capture_done(None)
        assert writing.exists()
        assert not (writing.parent / "raw").exists()
        assert server._active_capture is not None

    asyncio.run(run())


def test_capture_requires_stream_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DISK_PATHS", str(tmp_path))
    monkeypatch.delenv("VLBI_STREAM_NAME", raising=False)

    async def run():
        server = proxy.Jive5abServer("127.0.0.1", 0, 2620)
        jive = AsyncMock()
        monkeypatch.setattr(proxy, "jive_cmd", jive)
        with pytest.raises(proxy.FailReply, match="identifier"):
            await server.request_capture_init(None, "177")
        jive.assert_not_called()
        assert list(tmp_path.iterdir()) == []

    asyncio.run(run())
