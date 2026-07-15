## Pi Lab Emulator

### Purpose

Use a Raspberry Pi 4 as a BAS test bench for BAS Assistant by turning a project JSON into a lightweight, JACE-like gateway plus emulated controller and point inventory.

This is intentionally **not** a full Niagara/JACE runtime clone. It emulates the device topology, point inventory, and writable/read-only behavior that BAS Buddy can test against without depending on Tridium software.

### What It Produces

- One gateway device named `JACE-EMU` by default
- One emulated controller device per controller discovered in the project
- Deterministic BACnet-style device instances and object instances
- Initial point values and simple live sensor drift for read-only points
- A REST API for lab automation and BAS Buddy integration testing

### Generate a Lab

```bash
bas emulate examples/sample-hvac-project.json -o ./emulation
```

This writes:

- `emulation/lab_manifest.json`
- `emulation/runtime_snapshot.json`
- `emulation/controllers/*.json`

### Run the Emulator API on the Pi

```bash
bas emulate examples/sample-hvac-project.json -o ./emulation --serve --host 0.0.0.0 --port 8787
```

REST endpoints:

- `GET /healthz`
- `GET /manifest`
- `GET /snapshot`
- `POST /step?steps=1`
- `GET /devices`
- `GET /devices/{device_id}`
- `GET /points`
- `GET /points/{point_name}`
- `POST /points/{point_name}`

Writable point write body:

```json
{
  "value": 55.0
}
```

### Recommended Pi 4 Layout

1. Run BAS Assistant and the emulator on the Pi together.
2. Keep the emulator on a dedicated VLAN or isolated bench network.
3. Point BAS Buddy at the emulator REST API first.
4. If you later need live BACnet/IP, add a separate adapter process that maps `lab_manifest.json` and `runtime_snapshot.json` into real BACnet objects.

### Why This Cut Is Useful

- It lets you validate controller/point topology before field hardware exists.
- It gives BAS Buddy a stable target for regression tests.
- It keeps the project data model as the single source of truth.
- It avoids pretending to emulate proprietary Niagara internals that cannot be reproduced faithfully.

