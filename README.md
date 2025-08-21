Provides a prototype workflow for streaming and recording VLBI VDIF data over UDP using jive5ab and a Python-based sender.

# Components
## Sender

Python script that generates synthetic VDIF frames.

Frames carry correctly-formed headers (sequence numbers, frame length, timestamps).

Packaged into UDP packets with an optional UDPS prefix.

Transmission rate is configurable (frames per second).

## Receiver

jive5ab runs in Docker containers.

Supports two modes:

net2file: write incoming frames into flat files (for debugging).

`record=on:<scan>:` record into FlexBuff VBS "shrapnel" chunks for long-term capture and transfer.

## Usage

Start receiver stack with docker-compose up.

Run sender with destination set to the receiver host/port.

`python sender.py --dest 10.107.0.10 --port 50000 --fps 2


On the receiver:

Debug with net2file.

Switch to record=on:<scan_name> once headers are validated.
