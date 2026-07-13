# BAS Assistant Engineering Wiki — Home

> **Single source of truth** for the BAS Programming Assistant.
> Architecture, conventions, domain models, workflows, reasoning rules, templates, and decisions.

---

## Quick Navigation

### Core Foundation
| Document | Purpose |
|----------|---------|
| [[VISION]] | Product philosophy, success criteria, boundaries |
| [[ARCHITECTURE]] | High-level components, data flow, module boundaries |
| [[DESIGN_PRINCIPLES]] | Engineering principles for the assistant |
| [[ROADMAP]] | Phased development plan |
| [[DECISIONS]] | Architecture decision log |

### Domain Knowledge
| Area | Documents |
|------|-----------|
| **BAS Fundamentals** | [[domain/bas_fundamentals]], [[domain/equipment]], [[domain/controllers]], [[domain/sequences]] |
| **Protocols** | [[domain/bacnet]], [[domain/modbus]], [[domain/niagara]] |
| **Commissioning** | [[domain/commissioning]], [[domain/alarms]], [[domain/trends]] |

### Structured Models
| Model | Purpose |
|-------|---------|
| [[models/project]] | Top-level project container |
| [[models/equipment]] | Equipment definitions & relationships |
| [[models/points]] | Point definitions, naming, validation |
| [[models/controller]] | Controller inventory & capabilities |
| [[models/logic]] | Control logic intermediate representation |
| [[models/graphics]] | Graphics definitions & bindings |
| [[models/checkout]] | Checkout sheet model |

### Conventions (Generation Rules)
| Convention | Applies To |
|------------|------------|
| [[conventions/naming]] | All point & equipment names |
| [[conventions/logic]] | Control logic structure |
| [[conventions/graphics]] | Graphics layout & binding |
| [[conventions/checkout]] | Checkout sheet format |
| [[conventions/reports]] | Report templates |
| [[conventions/documentation]] | Documentation style |
| [[conventions/python]] | Code style for generators |

### Workflows (How-To)
| Workflow | Purpose |
|----------|---------|
| [[workflows/import_project]] | Import schedules, point lists, sequences |
| [[workflows/generate_logic]] | Generate control logic from sequences |
| [[workflows/generate_graphics]] | Generate graphics from equipment + points |
| [[workflows/generate_checkout]] | Generate checkout sheets |
| [[workflows/generate_reports]] | Generate submittal/engineering reports |
| [[workflows/troubleshoot]] | AI-assisted troubleshooting |

### Reasoning & AI
| Document | Purpose |
|----------|---------|
| [[reasoning/ai_reasoning]] | How AI should reason about BAS tasks |
| [[reasoning/validation]] | Validation rules & engine |
| [[reasoning/engineering_rules]] | Hard engineering constraints |
| [[reasoning/confidence]] | Confidence scoring for AI outputs |
| [[reasoning/assumptions]] | Assumption tracking |

### Equipment Templates (Ready-to-Use)
| Template | Equipment Type |
|----------|----------------|
| [[templates/AHU]] | Air Handling Unit |
| [[templates/VAV]] | VAV Box |
| [[templates/Chiller]] | Chiller Plant |
| [[templates/Boiler]] | Boiler Plant |
| [[templates/CoolingTower]] | Cooling Tower |
| [[templates/Pump]] | Pump (HW/CHW/CW) |
| [[templates/RTU]] | Rooftop Unit |

---

## Graph View Tips
- **Tags**: `#model` `#convention` `#workflow` `#template` `#domain` `#reasoning`
- **Folders**: `models/` `conventions/` `workflows/` `templates/` `domain/` `reasoning/`
- **Links**: Every doc links to its dependencies — use the graph to explore relationships

---

## Getting Started
1. Read [[VISION]] → [[ARCHITECTURE]] → [[DESIGN_PRINCIPLES]]
2. Browse [[models/project]] and the domain models
3. Pick a workflow (e.g., [[workflows/import_project]])
4. Use templates as starting points for equipment definitions

---

## Project Status
**Current Phase:** Phase 1 — Wiki, conventions, domain model drafts ✅
**Next:** Phase 2 — Structured project import & validation

---

*Last updated: 2026-07-09*
*Vault: `bas-assistant-vault`*