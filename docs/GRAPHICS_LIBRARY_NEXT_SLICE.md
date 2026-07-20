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
