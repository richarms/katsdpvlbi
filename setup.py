#!/usr/bin/env python3

from setuptools import setup


tests_require = ["pytest"]


setup(
    name="katsdpvlbi",
    description="MeerKAT VLBI data capture utilities",
    author="MeerKAT SDP team",
    author_email="sdpdev+katsdpvlbi@ska.ac.za",
    scripts=[
        "scripts/jive5ab_katcp_proxy.py",
        "scripts/send_vdif.py",
        "scripts/send_vdif_std_mtu_sync_seq.py",
    ],
    install_requires=[
        "aiokatcp",
        "numpy",
    ],
    extras_require={"test": tests_require},
    tests_require=tests_require,
    use_katversion=True,
)
