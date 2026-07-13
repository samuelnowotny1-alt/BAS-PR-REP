# BAS Assistant - Step-by-Step Optimization Plan

> **Generated**: 2026-07-12 | **Project**: BAS Assistant | **Status**: Ready to execute

---

## 📋 How to Use This Plan

1. **Follow sequentially** - Each phase builds on the previous
2. **Check off each step** - Use the checkboxes `[ ]` to track progress
3. **Run verification commands** - Each step includes a test to confirm completion
4. **Commit after each phase** - Keeps history clean and rollback easy

---

## 🎯 Phase 0: Baseline & Benchmarking (Do First!)

### 0.1 Establish Current Metrics
- [ ] Run full test suite: `cd /home/oem/.openclaw/workspace/bas-assistant && pytest tests/ -v --tb=short`
- [ ] Record test count, pass/fail, duration
- [ ] Run lint: `ruff check src/`
- [ ] Run type check: `mypy src/`
- [ ] Benchmark CLI startup: `time bas --help`
- [ ] Benchmark full pipeline: `time bas import examples/equipment_schedule.csv examples/point_list.csv examples/controller_schedule.csv --project demo-opt && time bas validate demo-opt && time bas export demo-opt --format niagara`
- [ ] Record all baseline numbers in `OPTIMIZATION_BASELINE.md`

**Verification**: `cat OPTIMIZATION_BASELINE.md` shows all metrics

---

## 🔧 Phase 1: Core Models & Types (Foundation)

### 1.1 Models Package (`src/bas_assistant/models/`)
**Files**: `__init__.py`, `project.py`, `equipment.py`, `points.py`, `logic.py`, `types.py`, `graphics.py`, `controller.py`, `checkout.py`

| Step | Action | Verification |
|------|--------|--------------|
| 1.1.1 | Add `__slots__` to all Pydantic models for memory efficiency | `python -c "import sys; from bas_assistant.models import Project; print(sys.getsizeof(Project()))"` - should be smaller |
| 1.1.2 | Enable `model_config = ConfigDict(use_enum_values=True, validate_assignment=True, frozen=True)` where immutable | Tests pass, no runtime errors |
| 1.1.3 | Replace `List[]` with `list[]`, `Dict[]` with `dict[]`, `Optional[]` with `X \| None` (Python 3.10+) | `ruff check src/bas_assistant/models/` clean |
| 1.1.4 | Add `frozen=True` to models that shouldn't mutate after creation (ProjectMetadata, Point, Controller) | Try to mutate → `ValidationError` raised |
| 1.1.5 | Consolidate duplicate field definitions into shared base classes | Line count reduced, no duplicate `Field(...)` calls |
| 1.1.6 | Add `__rich_repr__` to key models for better debug output | `python -c "from bas_assistant.models import Project; print(Project())"` shows clean output |
| 1.1.7 | Run model-specific tests: `pytest tests/test_models.py -v` | All pass |

### 1.2 Types Module (`types.py`)
- [ ] Extract all enums to separate `enums.py` if >15 enums
- [ ] Add `Literal` type aliases for common string unions
- [ ] Document each type with docstring explaining BAS context

---

## ⚡ Phase 2: Validation Engine (High Impact)

### 2.1 Validation Engine (`src/bas_assistant/validation/engine.py`)
| Step | Action | Verification |
|------|--------|--------------|
| 2.1.1 | Profile current validation: `python -m cProfile -o val.prof -c "from bas_assistant.validation import ValidationEngine; ValidationEngine().validate(project)"` | `snakeviz val.prof` shows hotspots |
| 2.1.2 | Cache compiled regex patterns (module-level, not per-call) | `ruff check` clean, regex not recompiled |
| 2.1.3 | Convert rule functions to `@dataclass` rules with `__call__` for parallel execution | `pytest tests/test_validation.py::test_parallel_rules -v` passes |
| 2.1.4 | Add `ThreadPoolExecutor` for independent rule groups (equipment, points, controllers) | Speedup >2x on multi-core |
| 2.1.5 | Implement early-exit for critical rules (fail-fast mode) | `ValidationEngine(..., fail_fast=True)` stops on first critical |
| 2.1.6 | Add validation result caching by project hash | Re-running on unchanged project is instant |
| 2.1.7 | Run benchmarks: `pytest tests/test_validation.py -v --benchmark-only` | Record before/after in `OPTIMIZATION_RESULTS.md` |

### 2.2 Built-in Rules (50+ rules)
- [ ] Group rules by category: `equipment/`, `points/`, `controllers/`, `logic/`, `cross_ref/`
- [ ] Add rule metadata: `severity`, `category`, `auto_fixable`, `description`
- [ ] Create rule registry with lazy loading

---

## 📥 Phase 3: CSV Importer (`src/bas_assistant/importers/csv_importer.py`)

| Step | Action | Verification |
|------|--------|--------------|
| 3.1 | Use `csv.DictReader` with explicit encoding (`utf-8-sig`) | Handles BOM correctly |
| 3.2 | Add chunked processing for large files (>10k rows) | Memory stays flat with 100k rows |
| 3.3 | Implement row-level validation with error collection (don't fail fast) | `ImporterResult` with `errors: list[ImportError]` |
| 3.4 | Add type coercion with fallback (string → int/float with logging) | No `ValueError` crashes on bad data |
| 3.5 | Support multiple sheet formats (equipment, points, controllers, sequences) | All example CSVs import cleanly |
| 3.6 | Add `--dry-run` flag to preview without persisting | `bas import --dry-run file.csv` shows preview |
| 3.7 | Benchmark: `time bas import large.csv` | Record in results |

---

## 📤 Phase 4: Exporters (6 Vendors + BACnet)

### 4.1 Base Exporter (`exporters/base.py`)
- [ ] Abstract common logic: file writing, progress callbacks, template rendering
- [ ] Add `ExporterConfig` dataclass for shared options
- [ ] Implement context manager for temp file cleanup

### 4.2 Vendor-Specific Exporters
| Exporter | Key Optimizations | Test Command |
|----------|-------------------|--------------|
| `niagara.py` | Jinja2 template caching, batch point export | `bas export demo --format niagara` |
| `tridium.py` | Same as Niagara (shared base) | `bas export demo --format tridium` |
| `jci.py` | Metasys-specific XML streaming | `bas export demo --format jci` |
| `honeywell.py` | EBI CSV streaming writer | `bas export demo --format honeywell` |
| `siemens.py` | Desigo CC format optimization | `bas export demo --format siemens` |
| `bacnet.py` | BACnet CSV with proper object instances | `bas export demo --format bacnet` |

### 4.3 Exporter CLI Integration
- [ ] Add `--parallel` flag for multi-vendor export
- [ ] Add `--output-dir` with timestamped subdirs
- [ ] Progress bars via `rich.progress`

---

## 🎨 Phase 5: Generators (Checkout, Reports, Graphics, Logic)

### 5.1 Checkout Generator (`generators/checkout.py`)
- [ ] Template caching (Jinja2 `Environment` singleton)
- [ ] Per-equipment parallel generation
- [ ] Output: Excel (.xlsx) with formatted sheets using `openpyxl` styles
- [ ] Add `--equipment-filter` CLI flag

### 5.2 Reports Generator (`generators/reports.py`)
- [ ] 5-file submittal package: Equipment Schedule, Point List, Controller Schedule, Sequence of Operations, Valve/ Damper Schedule
- [ ] Use `pandas.ExcelWriter` for multi-sheet workbooks
- [ ] Auto-size columns, freeze panes, filters

### 5.3 Graphics Generator (`generators/graphics.py`)
- [ ] PX JSON template library (VAV, AHU, Chiller, Boiler, FCU)
- [ ] SVG preview generation via `cairosvg` (optional dep)
- [ ] Component reuse tracking (don't duplicate graphics)

### 5.4 Logic Generator (`generators/logic.py`)
- [ ] Mermaid.js sequence diagrams with proper BAS styling
- [ ] Niagara `.bog` logic blocks export
- [ ] State machine visualization for sequences

---

## 🧠 Phase 6: Reasoning Engine (AI-Assisted)

### 6.1 Gap Analysis (`reasoning/gap_analysis.py`)
- [ ] Cache LLM prompts as templates
- [ ] Add structured output parsing (Pydantic response models)
- [ ] Implement retry with exponential backoff
- [ ] Add token usage tracking

### 6.2 Sequence Parser (`reasoning/sequence_parser.py`)
- [ ] Compile regex patterns at module load
- [ ] Add grammar-based parsing (Lark) for complex SOO
- [ ] Cache parsed sequences by content hash

### 6.3 Troubleshooting (`reasoning/troubleshooting.py`)
- [ ] Pre-load common fault patterns at startup
- [ ] Index by equipment type + symptom
- [ ] Add confidence scoring

### 6.4 Validation Reasoning (`reasoning/validation_reasoning.py`)
- [ ] Rule explanation templates (why did this fail?)
- [ ] Auto-fix suggestions for common patterns

### 6.5 Assumptions Tracker (`reasoning/assumptions.py`)
- [ ] Version control for assumptions (git-like log)
- [ ] Impact analysis when assumption changes

### 6.6 Confidence Scoring (`reasoning/confidence.py`)
- [ ] Calibrate thresholds with historical data
- [ ] Export confidence report with validation

---

## 📊 Phase 7: Analytics (`analytics/statistical_tracking.py`)

- [ ] Vectorize with NumPy/pandas where possible
- [ ] Add incremental statistics (Welford's algorithm)
- [ ] Implement streaming percentile calculation
- [ ] Cache computed metrics by data hash

---

## 🖥️ Phase 8: CLI & UX (`cli.py`)

| Step | Action | Verification |
|------|--------|--------------|
| 8.1 | Add command groups: `bas project`, `bas import`, `bas validate`, `bas generate`, `bas export`, `bas reason` | `bas --help` shows clean hierarchy |
| 8.2 | Add `--verbose`/`-v` (repeatable) and `--quiet`/`-q` flags globally | Log levels work |
| 8.3 | Add `--json` output flag for all commands (machine-readable) | `bas validate demo --json \| jq` works |
| 8.4 | Add shell completions: `bas --install-completion` | Tab completion works in bash/zsh/fish |
| 8.5 | Add config file support (`~/.config/bas/config.toml`) | Persistent defaults |
| 8.6 | Rich progress bars for long operations | Visual feedback on import/export |
| 8.7 | Structured logging (JSON lines) option | `bas --log-format json validate demo` |

---

## 🧪 Phase 9: Testing & CI

### 9.1 Test Organization
```
tests/
├── unit/
│   ├── test_models.py
│   ├── test_validation.py
│   ├── test_importers.py
│   ├── test_exporters.py
│   ├── test_generators.py
│   └── test_reasoning.py
├── integration/
│   ├── test_full_pipeline.py
│   └── test_cli.py
├── fixtures/
│   ├── projects/
│   ├── csv/
│   └── expected_outputs/
└── benchmarks/
    └── test_performance.py
```

### 9.2 Coverage Targets
- [ ] Unit tests: >90% coverage
- [ ] Integration tests: Cover all CLI commands
- [ ] Property-based tests for validation rules (Hypothesis)
- [ ] Mutation testing: `mutmut run` >80% killed

### 9.3 CI Pipeline (GitHub Actions)
- [ ] Matrix: Python 3.10, 3.11, 3.12
- [ ] Lint → Type Check → Unit Tests → Integration Tests → Benchmarks
- [ ] Publish coverage to Codecov
- [ ] Benchmark comparison on PR (fail if >10% regression)

---

## 📦 Phase 10: Packaging & Distribution

### 10.1 `pyproject.toml` Optimization
- [ ] Use `project.optional-dependencies` for `dev`, `ai`, `graphics`, `all`
- [ ] Add `py.typed` marker
- [ ] Set `requires-python = ">=3.10"`
- [ ] Configure `ruff`, `mypy`, `pytest` in `pyproject.toml`

### 10.2 Build Optimization
- [ ] Use `hatch` or `pdm` for faster builds
- [ ] Add `--no-build-isolation` for CI
- [ ] Generate universal wheel

---

## 🚀 Phase 11: Documentation & Examples

### 11.1 API Docs
- [ ] `mkdocstrings` with Google-style docstrings
- [ ] Auto-generate CLI reference from Click commands
- [ ] Mermaid diagrams for architecture

### 11.2 User Guides
- [ ] Quickstart (5 min)
- [ ] Importing from CSV
- [ ] Validation rules reference
- [ ] Exporting to vendor formats
- [ ] Custom validation rules
- [ ] AI reasoning features

### 11.3 Example Projects
- [ ] Small VAV system (5 AHUs, 50 VAVs)
- [ ] Central plant (chillers, boilers, cooling towers)
- [ ] Campus (multiple buildings)

---

## 📈 Phase 12: Performance Verification

### 12.1 Re-run All Benchmarks
| Benchmark | Baseline | Target | Actual |
|-----------|----------|--------|--------|
| CLI startup | ___ms | <50ms | ___ms |
| Import 1k rows | ___ms | <200ms | ___ms |
| Validate demo project | ___ms | <500ms | ___ms |
| Export Niagara (demo) | ___ms | <1s | ___ms |
| Full pipeline | ___s | <5s | ___s |
| Memory (peak) | ___MB | <100MB | ___MB |

### 12.2 Regression Tests
- [ ] `pytest tests/benchmarks/ -v --benchmark-compare=baseline`
- [ ] Document any trade-offs made

---

## ✅ Phase 13: Final Polish

- [ ] Update `CHANGELOG.md` with all optimizations
- [ ] Update `README.md` with new features/flags
- [ ] Tag release: `git tag v0.2.0-optimized`
- [ ] Push to PyPI (if public): `hatch publish`
- [ ] Celebrate! 🎉

---

## 📝 Tracking Files to Create

| File | Purpose |
|------|---------|
| `OPTIMIZATION_BASELINE.md` | Before metrics |
| `OPTIMIZATION_RESULTS.md` | After metrics per phase |
| `OPTIMIZATION_NOTES.md` | Decisions, trade-offs, blockers |
| `tests/benchmarks/test_performance.py` | Automated benchmarks |

---

## 🎯 Quick Start Commands

```bash
# Clone this plan to your workspace
cd /home/oem/.openclaw/workspace/bas-assistant

# Phase 0 - Baseline
pytest tests/ -v --tb=short > baseline_tests.txt 2>&1
ruff check src/ > baseline_lint.txt 2>&1
mypy src/ > baseline_type.txt 2>&1
time bas --help > baseline_cli.txt 2>&1

# Start Phase 1
# ... follow the checkboxes ...
```

---

## 💡 Pro Tips

1. **One phase at a time** - Don't jump ahead
2. **Commit often** - `git add -p` for granular commits
3. **Run tests after each step** - Catch regressions early
4. **Profile before optimizing** - Data > intuition
5. **Document decisions** - Future you will thank present you

---

*Happy optimizing! 🦻🛢️*