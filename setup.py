#!/usr/bin/env python3

from setuptools import setup


tests_require = ["pytest"]


setup(
    name="katsdpvlbi",
    description="MeerKAT VLBI data capture utilities",
    author="MeerKAT SDP team",
    author_email="sdpdev+katsdpvlbi@ska.ac.za",
    py_modules=["aiokatcp_jive5ab"],
    scripts=[
        "sim_send_vdif/send.py",
        "sim_send_vdif/send_vdif_std_mtu_sync_seq.py",
    ],
    install_requires=[
        "aiokatcp",
        "numpy",
    ],
    extras_require={"test": tests_require},
    tests_require=tests_require,
    use_katversion=True,
)
