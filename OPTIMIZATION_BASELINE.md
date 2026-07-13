# Optimization Baseline Metrics

**Date**: 2026-07-12
**Commit**: $(cd /home/oem/.openclaw/workspace/bas-assistant && git rev-parse HEAD 2>/dev/null || echo "unknown")
**Python**: 3.12.3
**Environment**: .venv

---

## Test Results

```bash
$ pytest tests/ -v --tb=short --ignore=tests/test_ui_workflow.py
# 15 passed in 0.68s
```

**Test Count**: 15 tests
**Test Time**: 0.68s
**Coverage**: Not measured (add `--cov` later)

---

## CLI Startup Time

```bash
$ time bas --help
# real    0m0.685s
# user    0m0.840s
# sys     0m0.061s
```

**CLI Startup**: ~685ms (cold start with .venv)

---

## Linting (ruff)

```bash
$ ruff check src/
# FAILED: Unknown rule selector 'TKA' in pyproject.toml
```

**Status**: Config error - needs fix
**Files Checked**: N/A (config blocked)

---

## Type Checking (mypy)

```bash
$ mypy src/
# Found 5 errors in 5 files (errors prevented further checking)
```

**Errors**:
1. `src/bas_assistant/analytics/statistical_tracking.py:17` - pandas stubs missing
2. `src/bas_assistant/generators/checkout.py:8` - pandas stubs missing
3. `src/bas_assistant/generators/reports.py:8` - pandas stubs missing
4. `src/bas_assistant/importers/csv_importer.py:9` - pandas stubs missing
5. `.venv/lib/python3.12/site-packages/numpy/__init__.pyi:737` - Python 3.12+ syntax issue

**Status**: Missing pandas-stubs, numpy typing issue

---

## Project Structure

```
src/bas_assistant/
├── cli.py                    # Main CLI entry (38 commands)
├── models/                   # 8 model files
│   ├── project.py
│   ├── equipment.py
│   ├── points.py
│   ├── logic.py
│   ├── types.py
│   ├── graphics.py
│   ├── controller.py
│   └── checkout.py
├── importers/                # 2 files
│   ├── __init__.py
│   └── csv_importer.py
├── validation/               # 2 files
│   ├── __init__.py
│   └── engine.py
├── exporters/                # 8 files (6 vendors + base + bacnet)
│   ├── __init__.py
│   ├── base.py
│   ├── bacnet.py
│   ├── honeywell.py
│   ├── jci.py
│   ├── niagara.py
│   ├── siemens.py
│   └── tridium.py
├── generators/               # 5 files
│   ├── __init__.py
│   ├── checkout.py
│   ├── reports.py
│   ├── graphics.py
│   └── logic.py
├── analytics/                # 2 files
│   ├── __init__.py
│   └── statistical_tracking.py
├── reasoning/                # 7 files
│   ├── __init__.py
│   ├── assumptions.py
│   ├── confidence.py
│   ├── gap_analysis.py
│   ├── sequence_parser.py
│   ├── troubleshooting.py
│   ├── validation.py
│   └── validation_reasoning.py
└── exporters/                # (duplicate listing)

Total Python Files: 38
Total Lines of Code: ~(run: find src -name "*.py" -exec wc -l {} +)
```

---

## Dependencies (pyproject.toml)

```toml
# Core
pydantic>=2.0
click>=8.0
rich>=13.0
pyyaml>=6.0

# Data
pandas>=2.0
numpy>=1.24

# Export
openpyxl>=3.1
jinja2>=3.1
lxml>=4.9

# Web UI
fastapi>=0.100
uvicorn>=0.23
httpx>=0.24

# Dev
pytest>=7.0
pytest-cov>=4.0
ruff>=0.1
mypy>=1.0
```

---

## Next Steps

1. Fix ruff config (remove TKA)
2. Install pandas-stubs for mypy
3. Run full benchmark suite
4. Begin Phase 1: Foundation