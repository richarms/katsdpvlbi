Provides a prototype workflow for streaming and recording VLBI VDIF data over UDP using jive5ab and a Python-based sender.

## Sender

Python script that generates synthetic VDIF frames.

Frames carry correctly-formed headers (sequence numbers, frame length, timestamps).

Packaged into UDP packets with an optional UDPS prefix.

Transmission rate is configurable (frames per second).

## Receiver

jive5ab runs in Docker container.

Supports two modes:

net2file: write incoming frames into flat files (for debugging).

`record=on:<scan>:` record into FlexBuff VBS "shrapnel" chunks for long-term capture and transfer.

## Usage

Start receiver stack with docker-compose up.

Run sender with destination set to the receiver host/port.

`python sender.py --dest 10.107.0.10 --port 50000 --fps 2`

----


## VLBI Streaming and Recording Integration Plan September 2025

### Month 1–2: Stabilise Prototype

- **Sender**
  - Finalise Python VDIF generator with correct headers, sequence numbers, and timing.
  - Validate output against VDIF spec and sanity checker.
  - Benchmark sustained frame rates (64 MHz equivalent).
- **Receiver**
  - Confirm Dockerised `jive5ab` setup works with `net2file` and `record=on`.
  - Test persistence of recordings across disk mounts with XFS-formatted media.
- **Testing**
  - Run lab-scale sender/receiver loop on local cluster or staging hardware.
  - Validate files with sanity checker, confirm integrity and correct VDIF header parsing.

### Month 3–4: FlexBuff Integration

- **Hardware Setup**
  - Deploy multiple physical (XFS) disks on receiver nodes.
  - Record shrapnel using `record=on`.
- **Control Layer**
  - Finalise `aiokatcp` proxy for jive5ab (status, start/stop, error reporting).
  - Write test clients to send `record=on:<scan>` commands and monitor state.
- **Operations Tests**
  - Simulate sustained data rates equivalent to MeerKAT beamformed output.
  - Measure write performance, tune `nWriters` and UDP buffer sizes.
  - Ensure jumbo frames configured end-to-end.

### Month 5 (January '26): Telescope Integration

- **Interface with MeerKAT**
  - Define mapping from MeerKAT CBID/scan IDs to `record=on:<scan>` naming.
  - Build bridge from MeerKAT scheduling system to KATCP control proxy.
- **Networking**
  - Validate UDP/multicast path from telescope front-end to FlexBuff nodes.
- **Monitoring**
  - Integrate metrics (disk throughput, packet loss, error) into SDP logging stack.

### Month 6 (February '26): Pre-Deployment Validation

- **End-to-End Tests**
  - Run test observations with CBF backend.
  - Record multiple hours of data, validate with downstream processing tools.
- **Operational Procedures**
  - Document setup (orchestration, disk prep, control scripts).
  - Handover to operations team on starting/stopping recordings and handling failures. Identify remaining gaps (e.g. re-transmission, monitoring dashboards).
  - 
