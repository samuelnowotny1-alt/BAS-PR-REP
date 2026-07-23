# Release Handoff

Last updated: 2026-07-23

## Release Candidate

- Branch: `codex/demo-ready-consolidation`
- Base commit: `cd2c6fd`
- Accepted commit: the commit containing this handoff (`git rev-parse HEAD`)
- Full regression: `203 passed in 248.11s`
- Local smoke: 9 release routes and 5 rendered links passed
- Public reachability: 9 release routes passed through Nginx
- Authenticated smoke: 9 protected release routes and 179 rendered links passed through Nginx
- Release ID: `20260723T162926Z`
- Target: `http://155.138.193.113/`
- Runtime: `bas-assistant.service` behind Nginx
- Service migration: stale unmanaged listener removed; systemd owns port `8000`
- Persistent state: `data/`, `uploads/`, `output/`, `logs/`, and `config/bas-assistant.env`

## Included

- Project live-conditions operator dashboard with retained sparkline trends
- Rendered dead-link safeguards across project and output review surfaces
- Niagara graphics binding regression coverage
- Common contractor CSV heading mapping and inline correction workflow
- Worktree-safe VPS deployment with systemd, health checks, and automatic code rollback
- Local/public release route and rendered-link smoke checks
- Explicit graphics/library product scope and lab/emulator support boundary

## Acceptance Commands

```bash
pytest -q
python scripts/release_smoke.py --base-url http://127.0.0.1:8000 --project-id codex-test-project
python scripts/release_smoke.py --base-url http://155.138.193.113 --project-id codex-test-project
```

Public smoke must pass before the deployment is considered complete.

## Parallel Codex Rule

Use a separate branch and worktree for each Codex window. Exchange branch name, commit ID, working-tree status, test result, and deployment state before merging work.
