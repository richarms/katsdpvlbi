# katsdpvlbi

Provides the recorder side of the MeerKAT+ VLBI instrument.

## Product

The current `gpucbf` VLBI output is:
- one tied-array beam
- two polarisations
- two sidebands
- four VDIF threads total

Thread interpretation:
- `lsb-pol0`
- `lsb-pol1`
- `usb-pol0`
- `usb-pol1`

In the current configuration:
- `pol0 -> x`
- `pol1 -> y`
- threads and mean-power sensors therefore appear as:
  - `x0`
  - `y0`
  - `x1`
  - `y1`

Bandwidth interpretation:
- the V-engine input parent band is ~ `107 MHz`
- the emitted VLBI bandwidth is `64 MHz`
- the configured flat passband fraction is `0.9`

This is one beam represented as four VLBI threads from sideband x polarisation.

## Recorder Contract

`katsdpvlbi` currently fronts `jive5ab` through a KATCP proxy so that
`katsdpcontroller` can drive capture lifecycle through:
- `?capture-init <cbid>`
- `?capture-done`

The version-1 [recorder handoff contract](docs/handoff.md) defines the only
supported controller-managed layout:

- recording: `<data_dir>/.vlbi/<cbid>/<stream>/raw.writing/`
- closed raw input: `<data_dir>/.vlbi/<cbid>/<stream>/raw/`
- shards: `<cbid>_<stream>.<decimal-shard-number>`
- closure record: `raw/capture.json`, containing identity, version, and shard sizes

`data_dir` is the shared volume root from `DISK_PATHS`. The controller must also
set `VLBI_STREAM_NAME`; it is not inferred from the capture ID. The recorder
alone stops capture, flattens jive5ab's nested scan directory, and renames
`raw.writing` to `raw`. An empty capture or ambiguous stop response is an error.

`vlbimeta` consumes the closed raw directory and publishes separate
`<data_dir>/<cbid>_<stream>.vdif` and `<data_dir>/<cbid>_<stream>.metadata`
products. Raw data is retained. The old `_vdif` directory layouts are not
accepted as the new handoff; controller and recorder/postprocess images must
be updated together.

## Receiver Modes

`jive5ab` supports two modes here:
- `net2file`
  - flat-file debugging path
- `record=on:<scan>`
  - FlexBuff/VBS recording path used by the controller workflow

The active path is the VBS recording path.

`J5A_NETPORT` accepts SDP multicast ranges such as `239.192.63.252+3@7148`.
The entrypoint expands this to four explicit `address@port` destinations,
separated by colons, for jive5ab. Native jive5ab destination lists and single
destinations are also accepted. When `J5A_CBF_INTERFACE` is set, each multicast
destination must route through that interface before the receiver starts.

## Usage

For local dvelopment:

`docker compose -f docker-compose.dev.yml up`

Offline sender:

`python3 scripts/send_vdif.py --dest 10.107.0.10 --port 50000 --fps 2`

## Repository Layout

Operational scripts live in `scripts/`.

Key files:
- `scripts/jive5ab_katcp_proxy.py`
- `scripts/validate_vdif.py`
