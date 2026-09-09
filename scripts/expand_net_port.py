#!/usr/bin/env python3
"""Translate SDP IPv4 endpoint ranges to jive5ab's net_port list syntax."""

import ipaddress
import re
import sys


def expand_net_port(value: str) -> str:
    destinations = []
    for destination in value.split(":"):
        if "+" not in destination:
            destinations.append(destination)
            continue
        match = re.fullmatch(r"([0-9.]+)\+([0-9]+)@([0-9]+)", destination)
        if match is None:
            raise ValueError(f"Invalid IPv4 endpoint range: {destination!r}")
        first = ipaddress.IPv4Address(match[1])
        extra = int(match[2])
        port = int(match[3])
        if not 1 <= port <= 65535:
            raise ValueError(f"Invalid UDP port: {port}")
        # SDP endpoint ranges describe multicast subscriptions. Reject a range
        # extending outside multicast space before allocating the list.
        last = first + extra
        if not first.is_multicast or not last.is_multicast:
            raise ValueError("Endpoint range must contain only multicast IPv4 addresses")
        if extra >= 65536:
            raise ValueError("Endpoint range exceeds 65536 destinations")
        destinations.extend(f"{first + offset}@{port}" for offset in range(extra + 1))
    return " : ".join(destinations)


if __name__ == "__main__":
    print(expand_net_port(sys.argv[1]))
