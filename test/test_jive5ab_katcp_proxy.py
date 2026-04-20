import importlib.util
from pathlib import Path

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "jive5ab_katcp_proxy.py"
_SPEC = importlib.util.spec_from_file_location("jive5ab_katcp_proxy", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
proxy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(proxy)


def test_capture_block_to_vdif_scan_uses_stable_scan_name() -> None:
    cbid, scan_name = proxy.capture_block_to_vdif_scan("1234567890")
    assert cbid == "1234567890"
    assert scan_name == "1234567890_vdif"


@pytest.mark.parametrize("capture_block_id", ["", "abc/def", r"abc\def", "abc..def"])
def test_capture_block_to_vdif_scan_rejects_invalid_paths(capture_block_id: str) -> None:
    with pytest.raises(ValueError):
        proxy.capture_block_to_vdif_scan(capture_block_id)


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
