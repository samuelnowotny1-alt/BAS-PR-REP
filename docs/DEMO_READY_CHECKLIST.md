# Demo Ready Checklist

Last updated: 2026-07-20

Purpose:
Provide one end-to-end acceptance checklist for the current BAS Assistant release slice.

Scope:
This checklist is for the `Demo Ready Consolidation` slice. It validates that the shipped BAS Assistant demo path works from first run through generated deliverables and deployment verification.

## Local Acceptance

### 1. Runtime Startup

- [ ] App starts locally with `./scripts/run_ui_server.sh` or `uvicorn ui.api.main:app --host 0.0.0.0 --port 8000`
- [ ] `GET /healthz` returns `status: ok`
- [ ] Runtime directories exist for data, output, uploads, and logs

### 2. First-Run Seeding

- [ ] On an empty runtime, `Codex Test Project` is created automatically
- [ ] Seeded project contains equipment, points, and controllers
- [ ] Seeded demo source documents are written to per-project runtime storage, not tracked fixture paths

### 3. Home Page Demo Flow

- [ ] Home page shows `Load Demo Project`
- [ ] Demo load redirects to `/project/demo-hvac-project`
- [ ] Demo load is idempotent when run more than once

### 4. Demo Project Outputs

- [ ] Demo project has generated checkout outputs
- [ ] Demo project has generated report outputs
- [ ] Demo project has generated graphics outputs
- [ ] Demo project has generated logic outputs
- [ ] Demo project has generated vendor export outputs

### 5. Validation and Review

- [ ] `/project/{id}/validate` renders the findings explorer
- [ ] Validation export links work for JSON and CSV
- [ ] Generated-output review renders on the documents surface

### 6. Documents and Lineage

- [ ] Generated artifacts appear in the document library
- [ ] Downloads work from the document detail/download flow
- [ ] Generated output drift signals appear when expected

### 7. Graphics

- [ ] `/project/{id}/graphics` loads generated graphics
- [ ] Graphics page uses `/output/...` URLs for generated assets
- [ ] No `/static/output/...` regressions appear
- [ ] Graphics detail and fullscreen pages render
- [ ] Graphics library page renders

### 8. Logic and Export

- [ ] Logic page renders generated logic artifacts
- [ ] Export page produces vendor output packages
- [ ] Export artifacts are reachable from the output mount or library flow

### 9. Project Management

- [ ] Project duplication creates a copy with structured data and generated outputs
- [ ] Duplicate project appears on the home page and detail pages

## Regression Commands

Focused demo-ready regression suite:

```bash
./.venv/bin/python -m pytest \
  tests/test_graphics_generator.py \
  tests/test_runtime_infrastructure.py \
  tests/test_ui_workflow.py -q
```

Expected current result:

- `123 passed`

## VPS Acceptance

### 1. Sync and Restart

- [ ] Current branch state is synced to the VPS app directory
- [ ] App process is restarted against the synced code

### 2. Public Reachability

- [ ] Nginx responds on `http://155.138.193.113/`
- [ ] `GET /healthz` returns `status: ok`

### 3. Operator Review

- [ ] Home page loads through the public VPS
- [ ] Demo project can be opened
- [ ] Documents, Graphics, Validation, Logic, and Export pages are reachable

## Exit Criteria

The demo-ready slice is acceptable when:

1. Local focused regressions are green.
2. First-run seeding and explicit demo loading both work.
3. Generated artifacts are visible and reachable.
4. Graphics/output link paths are stable.
5. The VPS deployment serves the reviewed code successfully.
