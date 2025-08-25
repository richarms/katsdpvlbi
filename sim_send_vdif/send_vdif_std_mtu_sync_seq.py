#!/usr/bin/env python3
import argparse, math, socket, struct, time
import numpy as np
from datetime import datetime, timezone

VDIF_HEADER_BYTES = 32
VDIF_VERSION = 1
BITS_PER_SAMPLE = 2  # actual bits per sample (not minus one)
CHANNELS = 1
STATION_ID = "AA"
THREAD_ID = 0

def vdif_ref_epoch_info(unix_t):
    epoch0 = datetime(2000,1,1,tzinfo=timezone.utc).timestamp()
    secs = unix_t - epoch0
    half_year = 365 * 24 * 3600 / 2
    ref_epoch = int(secs // half_year) & 0x3F
    secs_from_ref = int(secs - ref_epoch * half_year)
    if secs_from_ref < 0: secs_from_ref = 0
    return ref_epoch, secs_from_ref

def build_vdif_header(secs_from_ref, ref_epoch, frame_within_sec, frame_len_bytes):
    """Build a minimal 32-byte VDIF header.

    The layout follows the VDIF standard (see
    https://vlbi.org/vdif/docs/vdif-specification) and matches the structure
    used inside jive5ab. The previous implementation mixed several fields,
    which resulted in an invalid header that jive5ab could not recognise and
    caused ``vbsrecord`` to abort with ``rtm==fill2vbs``.
    """

    frame_len_8 = frame_len_bytes // 8
    log2ch = int(math.log2(CHANNELS))

    # Word 0
    legacy = 1  # we only implement the legacy 32 byte header
    invalid = 0
    w0 = ((invalid & 0x1) << 31) | ((legacy & 0x1) << 30) | (secs_from_ref & 0x3FFFFFFF)

    # Word 1
    w1 = ((frame_within_sec & 0xFFFFFF) << 8) | ((ref_epoch & 0x3F) << 2)

    # Word 2
    w2 = ((frame_len_8 & 0x00FFFFFF) << 8) | ((log2ch & 0x1F) << 3) | (VDIF_VERSION & 0x7)

    # Word 3
    station = (ord(STATION_ID[0]) << 8) | ord(STATION_ID[1])
    w3 = ((station & 0xFFFF) << 16) | ((THREAD_ID & 0x3FF) << 6) | (((BITS_PER_SAMPLE - 1) & 0x1F) << 1)

    header = bytearray(VDIF_HEADER_BYTES)
    struct.pack_into(">IIII", header, 0, w0, w1, w2, w3)
    return header

def quantize_2bit_unsigned(x):
    thr = np.percentile(x, [25, 50, 75])
    return np.digitize(x, thr, right=True).astype(np.uint8)

def pack_2bit(q):
    pad = (-len(q)) % 4
    if pad: q = np.pad(q, (0, pad), mode="constant")
    q4 = q.reshape(-1, 4)
    b = ((q4[:,0] << 6) | (q4[:,1] << 4) | (q4[:,2] << 2) | q4[:,3]).astype(np.uint8)
    return b.tobytes()

def main():
    ap = argparse.ArgumentParser(description="VDIF UDP sender (std MTU, second-synced)")
    ap.add_argument("--ip", default="10.8.80.30")
    ap.add_argument("--port", type=int, default=50000)
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--tone-hz", type=float, default=1_000_000.0)
    ap.add_argument("--noise-std", type=float, default=0.2)
    ap.add_argument("--fps", type=int, default=11176, help="integer frames/s")
    ap.add_argument("--seq", type=bool, default=True, help="prepend 8B seqno for jive5ab udps mode")
    ap.add_argument("--sndbuf", type=int, default=16*1024*1024)
    args = ap.parse_args()

    # Std MTU, udps seqno consumes 8 bytes: payload_bytes = 1472 - 8 - 32 = 1432
    vdif_payload_bytes = 1432 if args.seq else 1440
    samples_per_frame = vdif_payload_bytes * 4
    frame_bytes = VDIF_HEADER_BYTES + vdif_payload_bytes
    fps = int(args.fps)
    frame_duration = 1.0 / fps
    eff_sample_rate = samples_per_frame * fps

    print(f"Dest {args.ip}:{args.port}")
    print(f"udps-seq={'on' if args.seq else 'off'} | payload={vdif_payload_bytes}B | frame={frame_bytes}B | fps={fps} | Fs={eff_sample_rate/1e6:.6f} MS/s")

    # Wait for next integer second (first frame at boundary)
    while True:
        now = time.time()
        if now - math.floor(now) < 1e-3:
            break
        time.sleep(0.0002)

    # Ref epoch & seconds-from-ref at boundary
    boundary = math.floor(time.time())
    ref_epoch, secs_from_ref = vdif_ref_epoch_info(boundary)

    # One-frame time base
    t = np.arange(samples_per_frame, dtype=np.float64) / eff_sample_rate
    phase = 0.0
    phase_inc = 2*math.pi*args.tone_hz*frame_duration

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, args.sndbuf)

    n_frames = int(args.duration * fps)
    next_deadline = time.perf_counter()
    frame_within_sec = 0
    seqno = 0

    for _ in range(n_frames):
        signal = np.sin(2*math.pi*args.tone_hz*t + phase) + np.random.normal(0, args.noise_std, samples_per_frame)
        phase += phase_inc
        if phase >= 2*math.pi: phase -= 2*math.pi

        q = quantize_2bit_unsigned(signal)
        payload = pack_2bit(q)
        header = build_vdif_header(secs_from_ref, ref_epoch, frame_within_sec, frame_bytes)

        if args.seq:
            pkt = struct.pack(">Q", seqno) + header + payload  # 8B big-endian seqno
            seqno += 1
        else:
            pkt = header + payload

        sock.sendto(pkt, (args.ip, args.port))

        frame_within_sec += 1
        if frame_within_sec == fps:
            frame_within_sec = 0
            secs_from_ref += 1

        next_deadline += frame_duration
        sleep_time = next_deadline - time.perf_counter()
        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            next_deadline = time.perf_counter()

if __name__ == "__main__":
    main()

