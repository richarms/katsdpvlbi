# katsdpvlbi

Provides the recorder/control side of the current VLBI sandbox workflow.

## Current Product

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

In the current sandbox configuration:
- `pol0 -> x`
- `pol1 -> y`
- threads and mean-power sensors therefore appear as:
  - `x0`
  - `y0`
  - `x1`
  - `y1`

Bandwidth interpretation:
- the V-engine input parent band is about `107 MHz`
- the emitted VLBI bandwidth is `64 MHz`
- the configured flat passband fraction is `0.9`

This is one beam represented as four VLBI threads from sideband x polarisation.

## Recorder Contract

`katsdpvlbi` currently fronts `jive5ab` through a KATCP proxy so that
`katsdpcontroller` can drive capture lifecycle through:
- `?capture-init <cbid>`
- `?capture-done`

The intended product layout is:
- in-progress directory:
  - `/scratch/data/<cbid>/<cbid>_vdif.writing/`
- final directory:
  - `/scratch/data/<cbid>/<cbid>_vdif/`

Preferred shard naming inside the directory:
- `<cbid>_vdif.00000000`
- `<cbid>_vdif.00000001`

Design rule:
- `.writing` should indicate product state on the directory
- shard basenames should remain stable and should not themselves carry `.writing`

This keeps downstream validation and postprocessing simpler.

## Receiver Modes

`jive5ab` supports two modes here:
- `net2file`
  - flat-file debugging path
- `record=on:<scan>`
  - FlexBuff/VBS recording path used by the controller workflow

The active path is the VBS recording path.

## Usage

Start the receiver stack with:

`docker compose -f docker-compose.dev.yml up`

CI/build pipeline uses `Jenkinsfile` + `Dockerfile`; compose is for local
development.

Synthetic sender example:

`python3 scripts/send_vdif.py --dest 10.107.0.10 --port 50000 --fps 2`

## Repository Layout

Operational scripts live in `scripts/`.

Key files:
- `scripts/jive5ab_katcp_proxy.py`
- `scripts/validate_vdif.py`

Older proof-of-concept material remains under `archive/concept/`.
