# Graphics / Library / Lab Bench Slice

Last updated: 2026-07-20

## Purpose

Package the current graphics workbench, graphics library, and lab-bench assets into one intentional follow-on release slice after demo-ready consolidation.

## Why This Needs Its Own Slice

The current branch contains meaningful graphics and lab-oriented work, but it spans multiple user stories:

- active project graphics preview
- reusable graphics symbol and unit library
- fullscreen operator/programmer simulation views
- lab/emulation assets and deployment helpers
- documentation and reference packs for recognizable HVAC geometry

Without an explicit slice boundary, these features risk being treated as one vague “graphics improvement” band even though they have different users and acceptance criteria.

## Included Scope

### 1. Graphics Workbench Packaging

- Validate the active-device graphics flow from generated JSON to detail page to fullscreen view
- Confirm output-link behavior and reviewer affordances
- Document what “done” means for project-facing graphics review

### 2. Known Unit Library

- Review `graphics_library` and `graphics_detail` surfaces
- Decide which library items are canonical product assets
- Separate reusable references from experimental or transitional assets

### 3. Lab Bench / Emulator Assets

- Review emulator JSON fixtures, manifests, and helper scripts
- Decide whether these are demo infrastructure, technician tooling, or internal engineering support
- Align docs and deployment expectations for the supported subset

### 4. Documentation and Reference Assets

- Keep `graphics-asset-reference-map.md` aligned with the actual library strategy
- Clarify what reference assets are for proportion and composition guidance versus runtime product behavior

## Asset Classification

### Product-Facing

These are part of the actual BAS Assistant user experience and belong in the slice narrative.

| Asset | Classification | Why it stays |
| --- | --- | --- |
| `ui/templates/graphics.html` | Product | Main graphics workbench for active project devices |
| `ui/templates/graphics_detail.html` | Product | Inspect surface for one generated graphic |
| `ui/templates/graphics_fullscreen.html` | Product | Fullscreen/operator-programmer review mode |
| `ui/templates/graphics_library.html` | Product | Reusable known-unit graphics library |
| `docs/graphics-asset-reference-map.md` | Product-supporting | Explains the visual reference strategy behind the graphics library |

### Supporting Fixtures And Demo Infrastructure

These should remain in the repo, but they are support assets for demos, tests, and engineering review rather than primary product features.

| Asset | Classification | Why it stays |
| --- | --- | --- |
| `examples/demo_documents/*` | Supporting fixture | Seed/demo source documents for realistic document-library flows |
| `ui/examples/demo_documents/*` | Supporting fixture | UI demo fixture set aligned to the explicit demo project |
| `emulation/lab_manifest.json` | Supporting fixture | Example generated bench manifest for emulator workflows |
| `emulation/runtime_snapshot.json` | Supporting fixture | Example runtime state fixture for bench review |
| `emulation/controllers/*.json` | Supporting fixture | Example controller-level emulator payloads |
| `scripts/run_lab_bench.sh` | Supporting fixture | Local bench-generation helper |
| `docs/LAB_BENCH_BLUEPRINT.md` | Supporting fixture | Planning and setup guidance for realistic bench validation |

### Internal / Transitional Tooling

These should not define the public release narrative. They are useful, but they are operator or engineering-support utilities.

| Asset | Classification | Why it is not core product |
| --- | --- | --- |
| `scripts/setup_raspi_lab_emulator.sh` | Internal tooling | Environment/bootstrap automation for a dedicated lab target |
| `scripts/deploy_raspi_lab_emulator.sh` | Internal tooling | Remote deployment helper for a Pi lab bench |

## Release Narrative Boundary

For the follow-on slice, describe the work as:

- active project graphics review
- reusable graphics library
- supporting bench fixtures for validation

Do not describe the slice as:

- full field tooling
- finished commissioning toolkit
- production-ready external emulator platform

The Pi/lab assets are valuable, but they remain support infrastructure until they have their own operational and acceptance story.

## Keep / Support / Defer Decisions

### Keep In Product Narrative

- graphics workbench
- graphic detail page
- fullscreen review mode
- known-unit graphics library

### Keep As Repo Support Assets

- demo source-document fixtures
- emulator manifests and controller JSON examples
- lab bench blueprint
- local bench runner script

### Defer From Core Release Messaging

- Raspberry Pi deployment automation
- any claim that emulator tooling is production-ready field tooling
- any claim that the library is a finished canonical design system

## Out of Scope

- Inline CSV editing
- Column mapping UI
- Broader reasoning-product work
- Full field-tooling polish beyond the reviewed emulator subset

## Acceptance Targets

1. Graphics workbench flows are documented and regression-covered.
2. Library pages and asset categories have a clear product/experimental boundary.
3. Lab-bench files remaining in the repo are intentionally included and documented.
4. The follow-on slice has a bounded release narrative instead of “misc graphics work.”

## Candidate Deliverables

- refreshed graphics/library docs
- cleaned include/exclude set for lab assets
- explicit reviewer walkthrough for graphics surfaces
- follow-on task list based on accepted library and emulator scope

Current supporting docs for this slice:

- `docs/GRAPHICS_REVIEW_WALKTHROUGH.md`
- `docs/graphics-asset-reference-map.md`
- `docs/LAB_BENCH_BLUEPRINT.md`

## Proposed Next Tasks For This Slice

1. Add a reviewer walkthrough for the graphics workbench, detail page, library, and fullscreen mode.
2. Mark the lab bench scripts and fixtures as support infrastructure in docs and release notes.
3. Decide whether the legacy flat symbol reference remains visible by default or moves behind a clearer compatibility label.
4. Validate that every repo-retained lab asset has a documented reason to exist.
