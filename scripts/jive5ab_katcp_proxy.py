#!/usr/bin/env python3
"""KATCP proxy server for jive5ab."""

import argparse
import asyncio
import logging
import os
import re
from typing import Tuple

from aiokatcp import DeviceServer, FailReply, Sensor

logger = logging.getLogger(__name__)

VDIF_PRODUCT_NAME = "vdif"
WRITING_SUFFIX = ".writing"


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


def capture_block_to_vdif_scan(capture_block_id: str) -> Tuple[str, str]:
    """Map a capture block id to (<cbid_dir>, <scan_name>) for recorder output."""

    cbid = capture_block_id.strip()
    if not cbid:
        raise ValueError("capture_block_id required")
    if "/" in cbid or "\\" in cbid or ".." in cbid:
        raise ValueError(f"invalid capture_block_id for path construction: {cbid!r}")
    scan_name = f"{cbid}_{VDIF_PRODUCT_NAME}{WRITING_SUFFIX}"
    return cbid, scan_name


def first_disk_path_from_env() -> str:
    """Return first configured DISK_PATHS entry, defaulting to /var/kat/data."""

    raw = os.environ.get("DISK_PATHS", "/var/kat/data")
    for path in (part.strip() for part in raw.split(",")):
        if path:
            return path
    return "/var/kat/data"


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

        self._poll_task = None

    def _make_sensor(self, sensor_type, name, description, initial):
        """Create a sensor, initialise it and add it to the server."""

        sensor = Sensor(sensor_type, name, description)
        sensor.set_value(initial)
        # Older aiokatcp only accepts one sensor per add()
        self.sensors.add(sensor)
        return sensor

    async def start(self):
        await super().start()
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        await super().stop()

    async def _poll_loop(self):
        while True:
            await self._poll_once()
            await asyncio.sleep(120.0)

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
        line = f"{self.s_state.value} {self.s_bytes.value}B {self.s_proto.value} {self.s_nport.value}"
        return "ok", line

    async def request_set_protocol(self, ctx, proto, rcv="33554432", snd="33554432", threads="4"):
        """Set network protocol. Usage: ?set-protocol <udp|udps> [<rcv> <snd> <threads>]"""
        proto = _as_text(proto)
        rcv = _as_text(rcv)
        snd = _as_text(snd)
        threads = _as_text(threads)
        proto_l = proto.lower()
        if proto_l not in ("udp", "udps"):
            raise FailReply("protocol must be udp or udps")
        try:
            if proto_l == "udps":
                cmd = f"net_protocol = udps : {int(rcv)} : {int(snd)} : {int(threads)}"
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
        capture_block_id = _as_text(capture_block_id)
        try:
            cbid, scan_name = capture_block_to_vdif_scan(capture_block_id)
            cbid_root = os.path.join(first_disk_path_from_env(), cbid)
            os.makedirs(cbid_root, exist_ok=True)
            rep = await jive_cmd(self.jive_port, f"set_disks = {cbid_root}")
            require_success(rep, "set_disks")
            return await self.request_record_start(ctx, scan_name)
        except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as err:
            self.s_error.set_value(str(err))
            logger.error("capture-init failed: %s", err)
            raise FailReply(str(err))

    async def request_record_stop(self, ctx):
        """Stop VBS recording. Usage: ?record-stop"""
        try:
            rep = await jive_cmd(self.jive_port, "record = off")
            code, detail = parse_reply_status(rep)
            # jive5ab may auto-stop if the stream dies; treat explicit stop as idempotent.
            # Some FlexBuff/jive builds also return code 1 on record-off despite writing data.
            if code == 1:
                logger.warning("record-stop returned code 1, treating as successful stop: %r", rep.strip())
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
        return await self.request_record_stop(ctx)

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
