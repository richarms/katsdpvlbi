Provides a prototype workflow for streaming and recording VLBI VDIF data over UDP using jive5ab and Python helper scripts.

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

Start receiver stack with:
`docker compose -f docker-compose.dev.yml up`

CI/build pipeline uses `Jenkinsfile` + `Dockerfile`; compose is for local development.

Run sender with destination set to the receiver host/port.

`python3 scripts/send_vdif.py --dest 10.107.0.10 --port 50000 --fps 2`

## Repository layout

Operational scripts live in `scripts/`.

Older prototype files are kept under `archive/concept/`.
