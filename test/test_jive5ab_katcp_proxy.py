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
