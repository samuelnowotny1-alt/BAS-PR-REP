# Project Audit

Last updated: 2026-07-20

This audit reflects the current BAS Assistant repo and live VPS state, not the older planning queue.

## Slice Matrix

| Slice | Status | Notes | Next Work |
|------|--------|-------|-----------|
| Project CRUD | Done | Project creation, list, detail, and duplication flows exist and are tested. | Keep under regression coverage. |
| Auth / Access | Done | Bootstrap admin, sessions, and project memberships are present. | Add clearer operator docs. |
| Persistence / Runtime | Done | JSON project storage, relational indexing, health checks, and runtime path setup are working. | Standardize production service management. |
| CSV Import | Done | Structured equipment, point, and controller import path is present. | Add richer editing and mapping ergonomics later. |
| Demo Seeding | Done | First-run seed and explicit demo load exist and generate outputs automatically. | Keep fixtures and runtime docs aligned. |
| Validation | Done | Engine and validate/issues review surfaces are in place. | Expand release-grade review checklist and acceptance criteria. |
| Documents / Lineage | Done | Document library, generated-output review, detail pages, and download paths exist. | Improve reviewer-facing summaries. |
| Graphics | Partial-High | Graphics generation, preview, detail, fullscreen, and library surfaces are strong. | Trim scope, verify packaging, and decide what is product vs. experimental. |
| Logic | Partial-High | Logic generation and review surfaces exist. | End-to-end narrative review against real example projects. |
| Reports / Checkout | Done | Deterministic report and checkout flows exist. | Tighten docs and acceptance walkthroughs. |
| Vendor Export | Partial-High | Export surfaces and vendor modules exist. | Validate more thoroughly against representative target systems. |
| Reasoning | Partial | Gap analysis, troubleshooting, assumptions, and related modules exist. | Productize and review source-attribution behavior end to end. |
| Emulation / Lab | Partial | Emulator and lab assets exist. | Decide whether this is part of the next release or a separate workstream. |
| Deployment | Partial-High | VPS deployment is live and functioning. | Consolidate on one documented runtime model. |
| Documentation | Partial | Docs exist, but several top-level narratives are stale. | Refresh README, roadmap context, and release status references. |

## What Changed Recently

- Demo-generated source documents now write into per-project runtime storage instead of mutating tracked fixture files.
- Demo loader and output-link behavior now have tighter regression coverage.
- Focused graphics/runtime/UI regression suite is green.
- Live VPS app was synced and restarted against the current tree on 2026-07-20.
- A release-grade demo acceptance checklist now exists in `docs/DEMO_READY_CHECKLIST.md`.

## Highest-Value Risks

1. Planning drift: queue and roadmap artifacts can mislead contributors unless they are kept in sync with the code.
2. Runtime ambiguity: Docker artifacts exist, but the currently live VPS path is an existing `uvicorn` process behind Nginx.
3. Scope inflation: graphics/library/lab-bench work can blur into a second product stream if not intentionally bounded.
4. Feature confidence asymmetry: deterministic core flows are strong, but some reasoning and export areas still need deliberate product walkthroughs.

## Recommended Follow-Up

1. Keep the current release slice focused on demo-ready consolidation.
2. Commit only reviewed state and keep runtime artifacts out of the repo.
3. After consolidation, either:
   - package graphics/library/lab-bench intentionally as the next slice, or
   - pivot to real-project import ergonomics with inline editing and column mapping.
