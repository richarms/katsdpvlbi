"""Check the SDP to jive5ab destination syntax boundary."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "expand_net_port", Path(__file__).resolve().parents[1] / "scripts" / "expand_net_port.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_four_groups():
    assert module.expand_net_port("239.192.63.252+3@7148") == (
        "239.192.63.252@7148 : 239.192.63.253@7148 : "
        "239.192.63.254@7148 : 239.192.63.255@7148"
    )


def test_octet_rollover():
    assert module.expand_net_port("239.192.63.255+1@7148") == (
        "239.192.63.255@7148 : 239.192.64.0@7148"
    )


@pytest.mark.parametrize("value", ["7148", "127.0.0.1@7148", "239.192.63.252@7148"])
def test_single_destination(value):
    assert module.expand_net_port(value) == value


def test_native_list():
    assert module.expand_net_port("239.1.0.1@7148:239.1.0.2@7148") == (
        "239.1.0.1@7148 : 239.1.0.2@7148"
    )


@pytest.mark.parametrize("value", [
    "239.1.0.1+bad@7148", "239.1.0.1+3@0", "239.1.0.1+3@65536",
    "239.255.255.255+1@7148", "10.1.0.1+3@7148", "239.1.0.1+65536@7148",
])
def test_invalid_range(value):
    with pytest.raises(ValueError):
        module.expand_net_port(value)
