#!/usr/bin/env python3
import socket
import struct
import time
import argparse
import binascii

# ------------------ Defaults ------------------
DEST_IP        = "10.101.0.7"
DEST_PORT      = 50000
FRAME_SIZE     = 8256           # 32B header + 8224 payload
HEADER_SIZE    = 32
PAYLOAD_SIZE   = FRAME_SIZE - HEADER_SIZE
FRAMES_PER_SEC = 2              # set to your test rate
REF_EPOCH      = 0              # 6-bit
THREAD_ID      = 0              # 0..1023
VERSION        = 1              # VDIF v1
UDPS_BE        = True           # UDPS sequence number endianness (big-endian typical)
PACE           = True           # sleep(1/FPS)
# ------------------------------------------------

def build_vdif_header(second: int, frame: int) -> bytes:
    """
    VDIF v1 header layout (32 bytes), little-endian words:
      word0 @ 0x00: seconds
      word1 @ 0x04: [23:0]=frame#, [29:24]=ref_epoch, [31]=invalid(0)
      word2 @ 0x08: [23:0]=frame_len/8, [29:24]=version
      word3 @ 0x0C: [9:0]=thread_id
      words4..7 zero
    """
    h = bytearray(32)

    # word0
    struct.pack_into("<I", h, 0x00, second)

    # word1
    w1 = (frame & 0x00FFFFFF) | ((REF_EPOCH & 0x3F) << 24)  # invalid=0
    struct.pack_into("<I", h, 0x04, w1)

    # word2
    flen8 = FRAME_SIZE // 8  # 8256/8 = 1032 (0x408)
    w2 = (flen8 & 0x00FFFFFF) | ((VERSION & 0x3F) << 24)
    struct.pack_into("<I", h, 0x08, w2)

    # word3
    w3 = (THREAD_ID & 0x3FF)
    struct.pack_into("<I", h, 0x0C, w3)

    # words 4..7 remain zero
    return bytes(h)

def header_selfcheck(hdr: bytes):
    """Print and sanity-check header fields."""
    sec  = struct.unpack_from("<I", hdr, 0x00)[0]
    w1   = struct.unpack_from("<I", hdr, 0x04)[0]
    w2   = struct.unpack_from("<I", hdr, 0x08)[0]
    w3   = struct.unpack_from("<I", hdr, 0x0C)[0]
    flen8 = w2 & 0x00FFFFFF
    ver   = (w2 >> 24) & 0x3F
    print("hdr[0:32] =", binascii.hexlify(hdr).decode())
    print(f"sec={sec}  frame={(w1 & 0xFFFFFF)}  ref_epoch={(w1>>24)&0x3F}  invalid={(w1>>31)&1}")
    print(f"flen8={flen8} (bytes={flen8*8})  version={ver}  thread={w3 & 0x3FF}")
    assert flen8 * 8 == FRAME_SIZE, "frame length field incorrect"
    assert ver == VERSION, "version incorrect"
    # Also visually: bytes 8..11 should be 08 04 00 01 in hex (LE)

def run_sender(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Optional selfcheck: print first header
    if args.selfcheck:
        hdr = build_vdif_header(int(time.time()), 0)
        header_selfcheck(hdr)
        return

    seq = 0
    second = int(time.time())
    frame  = 0
    inter_frame = 1.0 / args.fps if args.fps > 0 else 0.0

    while True:
        hdr = build_vdif_header(second, frame)
        if args.debug and frame == 0:
            header_selfcheck(hdr)

        payload = bytes(PAYLOAD_SIZE)   # replace with generated samples if desired
        vdif_frame = hdr + payload

        # 8-byte UDPS sequence-number prefix
        seq_hdr = struct.pack(">Q" if UDPS_BE else "<Q", seq)
        pkt = seq_hdr + vdif_frame
        sock.sendto(pkt, (args.dest, args.port))

        seq   += 1
        frame += 1
        if frame >= args.fps:
            frame  = 0
            second += 1

        if PACE and inter_frame > 0:
            time.sleep(inter_frame)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=DEST_IP)
    ap.add_argument("--port", type=int, default=DEST_PORT)
    ap.add_argument("--fps", type=int, default=FRAMES_PER_SEC, help="frames per second")
    ap.add_argument("--selfcheck", action="store_true", help="print first header and exit")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    run_sender(args)

if __name__ == "__main__":
    main()

