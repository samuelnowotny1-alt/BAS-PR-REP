# Lab Bench Blueprint

## Goal

Build a small BAS bench that is accurate enough to test:

- imports
- validation
- graphics
- logic
- alarms
- trends
- station sync assumptions

without needing a full building.

## Recommended Path

Use three layers in order:

1. Structured project model in BAS Assistant
2. Emulator plus realistic runtime data
3. Real station or real controller bench

That lets you validate the data model first, then the behavior, then the real integration target.

## Best Practical Bench

### Phase 1: Repo-Only Bench

Use what is already in this repo:

- `bas emulate` for controller and point topology
- `examples/generate_fake_station_data.py` for trends, alarms, and snapshots
- `examples/sample-hvac-project.json` as the initial project fixture

This is the fastest way to get repeatable behavior without hardware.

### Phase 2: Real Supervisor Bench

Add a real supervisory target:

- Niagara Workbench + test station, or
- another real front end you actually intend to support

Use the repo emulator and generated station data to feed review and comparison workflows while the real station becomes the truth target.

### Phase 3: Real Controller Bench

Add one real field controller and simulate the plant around it:

- 1 AHU controller
- 2 to 3 VAV controllers
- BACnet/IP backbone
- BACnet/MSTP trunk if you want realistic downstream topology

Use simulated sensors and feedback around the controller instead of inventing random values directly in the station.

## Minimum Point Set

Start with one AHU and two VAVs.

### AHU

- `AHU-1 SAT`
- `AHU-1 MAT`
- `AHU-1 RAT`
- `AHU-1 OAT`
- `AHU-1 SF CMD`
- `AHU-1 SF STS`
- `AHU-1 SF VFD-SPD`
- `AHU-1 SF VFD-SPD-SP`
- `AHU-1 DAT-SP`
- `AHU-1 CLG-VLV-CMD`
- `AHU-1 CLG-VLV-POS`
- `AHU-1 HTG-VLV-CMD`
- `AHU-1 HTG-VLV-POS`
- `AHU-1 OAD-CMD`
- `AHU-1 OAD-POS`
- `AHU-1 DUCT-SP`
- `AHU-1 DUCT-PRES`
- `AHU-1 SMK-ALM`
- `AHU-1 FLT-ALM`
- `AHU-1 OCC-CMD`

### VAV-101 / VAV-102

- `VAV-101 ZN-T`
- `VAV-101 DAT`
- `VAV-101 AIRFLOW`
- `VAV-101 AIRFLOW-SP`
- `VAV-101 DMP-CMD`
- `VAV-101 DMP-POS`
- `VAV-101 HTG-CMD`
- `VAV-101 HTG-POS`
- `VAV-101 OCC`
- `VAV-101 FLT-ALM`

Mirror the same for `VAV-102`.

## Behavior You Actually Want

The bench should simulate cause and effect, not just values.

### Normal

- occupied start
- warmup
- steady occupied mode
- unoccupied setback

### Disturbance

- hot outside air
- low duct pressure
- high zone load
- slow valve response
- damper tracking error

### Fault

- failed fan proof
- stuck damper
- stuck valve
- drifting SAT sensor
- bad airflow sensor
- controller offline
- intermittent point quality degradation

## What “Accurate” Means Here

For this repo, accurate simulation data means:

- point values follow sequence timing
- commands and statuses can disagree during faults
- analog values move with delay and inertia
- alarms appear from conditions, not from random toggles
- trends are internally consistent across related points

If `SF CMD` turns on, `SF STS` should not always turn on immediately. That delay and mismatch window is where real testing value comes from.

## Cheapest Hardware Path

- mini PC or Raspberry Pi 4 for BAS Assistant + emulator
- managed switch or isolated bench network
- optional used BACnet/IP controller
- optional USB-RS485 adapter for MSTP later

This is enough to start validating workflows before buying a full station stack.

## Best “Real Station” Path

- Windows laptop or VM with Niagara Workbench
- one JACE or test Niagara station
- one real BACnet/IP controller
- isolated bench VLAN
- BAS Assistant on a separate machine or same VM host

This gives you the cleanest route to testing exports, graphics assumptions, point naming, and station sync expectations.

## Repo Workflow

### Generate bench artifacts

```bash
./scripts/run_lab_bench.sh examples/sample-hvac-project.json
```

This will:

- build emulator files under `./emulation`
- generate trend, snapshot, alarm, and controller runtime CSVs under `./examples/fake_station`

### Serve emulator API

```bash
./scripts/run_lab_bench.sh examples/sample-hvac-project.json --serve
```

Default emulator endpoint:

- `http://127.0.0.1:8787`

## Immediate Next Step

Run the repo-only bench first and use it to validate:

- point inventory completeness
- alarm surfacing
- trend ingestion
- generated graphics linkage
- generated output review

After that, connect one real station target and compare:

- expected point inventory
- expected writable points
- expected trend and alarm behavior
- export assumptions versus actual station objects

## Decision Rule

If you want the fastest progress:

- do repo-only emulator first

If you want the most truthful integration target:

- add a real Niagara bench next

If you want the best long-term validation quality:

- use both, with the emulator for repeatable regression and the real bench for truth checks
