# Third-Party Inventory

This file records third-party material that may affect ownership,
redistribution, or commercialization.

## Current decision

The repository remains proprietary until this inventory is completed and any
required permissions, notices, or exclusions are resolved.

## Reviewed areas

### Core application code

- Path scope reviewed: `src/`, `ui/`, `scripts/`, `tests/`, `docs/`
- Result: no obvious third-party attribution markers or copied-source notices
  were found during a text scan.
- Limitation: absence of attribution text does not prove originality.

### Git authorship

- Current git history reviewed with `git shortlog -sne HEAD`
- Result: one visible commit author in the current history
- Limitation: this does not prove sole ownership of code, assets, or source
  material that may have been copied in from elsewhere.

### Example and sample files

- Reviewed paths:
  - `examples/*.csv`
  - `examples/*.json`
  - `examples/fake_station/*.csv`
  - `ui/examples/*.csv`
- Working assumption: these appear to be project sample data and generated test
  fixtures.
- Required follow-up: confirm they were authored internally and do not contain
  customer data, vendor-proprietary data, or copied documentation.

### Training-data tooling

- Reviewed path: `training_data/extract_training_data.py`
- External sources referenced directly by code:
  - DOE Commercial Reference Buildings
  - ASHRAE RP-1312 data
  - Modelica Buildings Library
- Risk level: high
- Why: those sources may be usable for internal research, but that does not
  automatically make redistributed processed outputs, derivative datasets, or
  commercial packaging safe.
- Current rule: do not distribute downloaded raw data or derived training
  outputs without source-by-source license review.

### Python dependencies

- Core runtime dependencies appear to be standard open-source Python packages.
- Several packages report permissive licenses such as MIT, BSD, or Apache-2.0.
- Required follow-up: if you distribute binaries, containers, or commercial
  on-prem packages, produce a proper dependency notice bundle from a dedicated
  software composition analysis pass.

## Commercialization blockers

1. No signed ownership chain is documented yet for all contributors and assets.
2. External training-data sources are referenced without a completed rights
   analysis.
3. No dependency notice bundle has been prepared for distributed builds.

## Near-term controls

1. Treat `training_data/` as internal-use-only until reviewed.
2. Keep the repository under the current proprietary `LICENSE`.
3. Do not accept outside contributions without written assignment terms.
4. Build a source ledger for every nontrivial asset added going forward.
