# Project Status

Last updated: 2026-07-20

## Snapshot

- Branch: `graphics-library-preview`
- Deployment target: VPS at `http://155.138.193.113/`
- Runtime status: deployed and responding through Nginx
- Focused regression suite: `123 passed`
- Current state: functional demo-to-deliverable pipeline with active consolidation work

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

## Partial

- README and operator-facing docs are behind the actual shipped feature set
- Queue and planning artifacts drifted behind the code and need ongoing correction
- Graphics/library/lab-bench feature band exists but still needs packaging and scope trimming
- Reasoning features exist in code, but still need a tighter product-grade walkthrough across UI surfaces
- Production deployment is working, but runtime management is not yet standardized to one documented mode

## Missing

- One current source-of-truth release checklist for end-to-end product acceptance
- A clean release narrative for non-technical reviewers
- Finalized production operating model: single documented service path, restart path, and recovery path
- Deliberate milestone boundaries between demo-ready, graphics/library, and field-tooling work

Note:
`docs/DEMO_READY_CHECKLIST.md` now covers the current demo-ready acceptance path. The remaining gap is broader release narration and operational standardization.

## Next Release Slice

Current next slice: `Demo Ready Consolidation`

Purpose:
Stabilize what already exists into a coherent demo and review experience before widening scope again.

Included:

- Refresh README and status docs so they match the running system
- Lock in demo-load, output-link, and runtime storage behavior with tests
- Reduce branch noise from generated runtime artifacts and tracked fixture mutation
- Review graphics/library/lab-bench files for intentional inclusion
- Keep the live VPS deployment aligned with the reviewed repo state

Deferred until after this slice:

- Inline CSV editor
- Drag-drop column mapping
- Larger reasoning-product expansions
- Broader field/simulator polish

## Recommended Order

1. Commit the current runtime/demo-storage and audit pass.
2. Treat `docs/PROJECT_STATUS.md` and `docs/PROJECT_AUDIT.md` as the current planning baseline.
3. Use `docs/DEMO_READY_CHECKLIST.md` as the acceptance gate for the current slice.
4. Review the remaining graphics/library/lab-bench scope as the following release slice.
