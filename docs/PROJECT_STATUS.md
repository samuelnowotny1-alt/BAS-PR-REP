# Project Status

Last updated: 2026-07-23

## Snapshot

- Branch: `graphics-library-preview`
- Deployment target: VPS at `http://155.138.193.113/`
- Runtime status: deployed and responding through Nginx
- Full regression suite: `208 passed`
- Current state: release-candidate demo-to-deliverable pipeline with consolidated dashboard, link handling, import ergonomics, and VPS operations

## Done

- Project CRUD, dashboard, and project detail flows
- Authentication, bootstrap admin, and project membership foundations
- JSON + relational persistence and runtime health checks
- Equipment / points / controllers CSV import workflow
- First-run `Codex Test Project` seeding
- Home-page `Load Demo Project` flow
- Automatic demo output generation for checkout, reports, graphics, logic, and exports
- Validation engine and validate/issues UI
- Document library, generated-output review, and artifact lineage flows
- Graphics workbench, detail page, fullscreen view, and graphics library
- Logic generation and vendor export surfaces
- Project duplication flow
- Pi / lab emulation foundations
- VPS deployment path with live app verification
- Project live-conditions operator dashboard with retained trend graphs
- Common contractor CSV heading mapping and inline post-import correction
- CSV header preflight and structured import rollback snapshots
- Full-building plant graphics and Niagara system overview pages
- Rendered-link release smoke checks

## Partial

- Graphics/library/lab-bench feature band exists but still needs packaging and scope trimming
- Reasoning features exist in code, but still need a tighter product-grade walkthrough across UI surfaces

## Missing

- A clean release narrative for non-technical reviewers
- Deliberate milestone boundaries between demo-ready, graphics/library, and field-tooling work

Note:
`docs/DEMO_READY_CHECKLIST.md` now covers the current demo-ready acceptance path. The remaining gap is broader release narration and operational standardization.

## Next Release Slice

Current next slice: `Release Candidate Acceptance`

Purpose:
Complete acceptance evidence for the consolidated demo and establish the next bounded product slice.

Included:

- Run the complete local and public acceptance suites
- Record the reviewed commit and VPS deployment state
- Keep graphics/library product scope separate from lab support tooling
- Prepare a concise reviewer walkthrough

Deferred until after this slice:

- Inline CSV editor
- Drag-drop column mapping
- Larger reasoning-product expansions
- Broader field/simulator polish

## Recommended Order

1. Use `docs/DEMO_READY_CHECKLIST.md` as the release acceptance gate.
2. Use `scripts/release_smoke.py` for local and public route/link verification.
3. Record the accepted commit and deployment in `docs/RELEASE_HANDOFF.md`.
4. Use `docs/GRAPHICS_LIBRARY_NEXT_SLICE.md` as the bounded follow-on slice.
