# BAS Assistant

**BAS Programming Assistant** — deterministic import, validation, and generation for building automation systems.

Turn sequences of operation → validated, vendor-ready deliverables (Niagara, BACnet, Tridium, JCI, Siemens, Honeywell) in minutes, not weeks.

## Features

- **Project CRUD** — Create, list, manage BAS projects
- **CSV Import** — Equipment schedules, point lists, controller schedules (3-file workflow)
- **Validation Engine** — 50+ built-in rules: naming, completeness, consistency, engineering constraints
- **Checkout Sheets** — Per-equipment Markdown + Excel with pass/fail fields
- **Submittal Reports** — 5-file package (summary, equipment, points, controllers, validation)
- **Graphics** — Niagara PX JSON + SVG previews for AHU, VAV, RTU, Chiller, Boiler, Pump, etc.
- **Logic Diagrams** — Mermaid + Niagara sequence export for control sequences
- **Export (6 vendors)** — Niagara (.bog/.wxf), BACnet (.ede/.csv), Tridium (.fox), JCI, Siemens, Honeywell
- **Sequence Parser** — Natural language SOO → structured logic + points + graphics
- **Troubleshooting** — Trend/alarm/loop analysis with confidence scoring
- **Assumptions Tracker** — Categorized, statused, impact-linked engineering assumptions
- **Web UI** — htmx + Tailwind, dark mode, responsive sidebar, document library, object lineage
- **Authentication** — Bootstrap admin, role-based access, project memberships

## Quickstart

### Option 1: Docker (Recommended)

```bash
# Build and start
docker compose up -d --build

# Open http://localhost:8000
```

### Option 2: Local Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run web UI
uvicorn ui.api.main:app --host 0.0.0.0 --port 8000

# Or use the bundled launcher
./scripts/run_ui_server.sh

# Or run CLI
bas --help
```

## Demo in 30 Seconds

1. Open http://localhost:8000
2. Click **"New Project"** → fill in project ID/name → Create
3. Click **"Import Data"** → upload the 3 sample CSVs from `examples/`
   - `equipment_schedule.csv`
   - `point_list.csv`
   - `controller_schedule.csv`
4. Click **"Validate"** → see 0 errors (green!)
5. Generate: **Checkout Sheets**, **Reports**, **Graphics**, **Logic Diagrams**
6. Click **"Export"** → select all 6 vendors → download vendor-ready packages

## Project Structure

```
bas-assistant/
├── src/bas_assistant/       # Core library
│   ├── models/              # Pydantic models (project, equipment, points, etc.)
│   ├── importers/           # CSV import → structured models
│   ├── validation/          # 50+ rule validation engine
│   ├── generators/          # Checkout, reports, graphics, logic
│   ├── exporters/           # 6 vendor export formats
│   └── reasoning/           # AI-assisted gap analysis, troubleshooting
├── ui/                      # FastAPI + htmx web UI
│   ├── api/main.py          # All routes
│   ├── templates/           # Jinja2 templates
│   └── static/              # CSS/JS (minimal, CDN-based)
├── examples/                # Sample CSV files + generated demo project
├── tests/                   # Pytest suite (22 tests passing)
├── docs/                    # Architecture, decisions, conventions
└── bas-assistant-vault/     # Engineering wiki (Obsidian-compatible)
```

## CLI Usage

```bash
# Create sample CSVs
bas init -o ./my-project

# Create new project
bas new -p my-project -n "My HVAC Project" -o project.json

# Import data
bas import project.json -e equipment.csv -p points.csv -c controllers.csv

# Validate
bas validate project.json --format table

# Generate outputs
bas checkout project.json -o checkout/
bas reports project.json -o reports/
bas graphics project.json -o graphics/
bas logic project.json -o logic/

# Export to vendor formats
bas export project.json -o export/ --format all
```

## Web UI Endpoints

| Page | URL | Purpose |
|------|-----|---------|
| Home | `/` | Project list + create new |
| Project Detail | `/project/{id}` | Dashboard with counts |
| Documents | `/project/{id}/documents` | Upload and generated artifact library |
| Import | `/project/{id}/import` | Upload 3 CSVs |
| Validate | `/project/{id}/validate` | Run 50+ rules, export JSON/CSV |
| Gap Analysis | `/project/{id}/gaps` | AI-assisted completeness check |
| Checkout | `/project/{id}/checkout` | Generate per-equipment sheets |
| Reports | `/project/{id}/reports` | 5-file submittal package |
| Graphics | `/project/{id}/graphics` | PX JSON + SVG previews |
| Logic | `/project/{id}/logic` | Mermaid + Niagara sequences |
| Export | `/project/{id}/export` | 6 vendor formats |
| Sequence Parser | `/project/{id}/sequence` | Paste SOO → structured logic |
| Troubleshooting | `/project/{id}/troubleshoot` | Trend/alarm analysis |
| Assumptions | `/project/{id}/assumptions` | Track engineering assumptions |
| Health | `/healthz` | Runtime health status for service monitoring |

## Production Runtime

- Environment example: `config/bas-assistant.env.example`
- Local launcher: `scripts/run_ui_server.sh`
- Production launcher: `scripts/start_production.sh`
- Health check: `scripts/healthcheck.sh`
- Example systemd unit: `deploy/bas-assistant.service.example`
- Database migrations: `alembic upgrade head`
- Bootstrap auth: admin account is created from `BAS_BOOTSTRAP_ADMIN_*` settings

## Architecture Principles

- **Deterministic generators** — Same input → same output, always testable
- **AI as advisor** — Explains, plans, summarizes; never invents engineering data
- **Structured data contracts** — Pydantic models between all modules
- **Human authority** — All outputs require engineer approval before use
- **Modular, testable** — Each generator/exporter independently testable

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BAS_DATA_DIR` | `./data` | Project JSON persistence |
| `BAS_OUTPUT_DIR` | `./ui/output` | Generated artifacts |
| `PYTHONUNBUFFERED` | `1` | Unbuffered logging |

## Testing

```bash
pytest tests/ -v
# focused regression suite currently passes in CI/dev runs
```

## License

MIT — see LICENSE for details.

## Contributing

1. Read `docs/ARCHITECTURE.md` and `docs/DESIGN_PRINCIPLES.md`
2. Check `docs/DECISIONS.md` for context on past choices
3. Follow `conventions/python.md` and `conventions/naming.md`
4. Add tests for new validation rules or generators
5. Run `ruff check . && mypy src/` before PR
