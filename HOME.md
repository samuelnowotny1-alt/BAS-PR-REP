# BAS Assistant — Engineering Wiki

> **Single source of truth** for the BAS Programming Assistant project.
> Architecture, conventions, domain models, workflows, reasoning rules, and decision history.

---

## 🗂️ Quick Navigation

### Core
- [[VISION]] — Product philosophy, success criteria, boundaries
- [[ARCHITECTURE]] — High-level components, data flow, module boundaries
- [[DESIGN_PRINCIPLES]] — Deterministic-first, AI-for-reasoning, human authority
- [[ROADMAP]] — Phased development plan
- [[DECISIONS]] — Architecture Decision Records

### Models (Structured Data Schemas)
- [[models/project]] — Project metadata, schedules, requirements
- [[models/equipment]] — Equipment types, templates, relationships
- [[models/points]] — Point definitions, naming, validation rules
- [[models/controller]] — Controller inventories, comms, mappings
- [[models/logic]] — Control sequences, conditions, modes
- [[models/graphics]] — Graphics definitions, bindings, layouts
- [[models/checkout]] — Checkout items, evidence, status tracking

### Conventions (Standards & Style)
- [[conventions/naming]] — Equipment, point, file, artifact naming
- [[conventions/logic]] — Sequence structure, condition formatting
- [[conventions/graphics]] — Symbol standards, color, layout
- [[conventions/python]] — Code style for generators/scripts
- [[conventions/documentation]] — Doc formatting, cross-references
- [[conventions/checkout]] — Checkout sheet structure
- [[conventions/reports]] — Report templates, sections

### Domain Knowledge (Engineering Reference)
- [[domain/bas_fundamentals]] — BAS concepts, terminology
- [[domain/equipment]] — AHU, VAV, Chiller, Boiler, Pump, RTU, Cooling Tower
- [[domain/controllers]] — Controller types, vendors, capabilities
- [[domain/sequences]] — Common sequences of operation
- [[domain/bacnet]] — BACnet objects, services, conformance
- [[domain/niagara]] — Niagara Framework, stations, modules
- [[domain/modbus]] — Modbus registers, mappings
- [[domain/commissioning]] — Commissioning process, checklists
- [[domain/alarms]] — Alarm classes, priorities, routing
- [[domain/trends]] — Trend logs, intervals, storage

### Workflows (How-To Guides)
- [[workflows/import_project]] — Ingest project data into models
- [[workflows/generate_logic]] — Produce control logic from sequences
- [[workflows/generate_graphics]] — Create graphics from equipment + points
- [[workflows/generate_checkout]] — Generate checkout sheets
- [[workflows/generate_reports]] — Produce project reports
- [[workflows/troubleshoot]] — AI-assisted troubleshooting workflow

### Reasoning (AI Assistant Rules)
- [[reasoning/ai_reasoning]] — How AI should reason, plan, explain
- [[reasoning/validation]] — Validation rules, completeness checks
- [[reasoning/engineering_rules]] — Hard engineering constraints
- [[reasoning/assumptions]] — Documented assumptions, traceability
- [[reasoning/confidence]] — Confidence scoring for AI outputs

### Templates (Equipment Patterns)
- [[templates/AHU]] — Air Handling Unit
- [[templates/VAV]] — Variable Air Volume box
- [[templates/Chiller]] — Chiller plant
- [[templates/Boiler]] — Boiler plant
- [[templates/Pump]] — Pump (CHW, HW, CW)
- [[templates/RTU]] — Rooftop Unit
- [[templates/CoolingTower]] — Cooling Tower

---

## 🔗 Graph View Entry Points

```dataview
TABLE file.folder as Folder, file.name as Note
FROM ""
WHERE file.name != "README"
SORT file.folder ASC, file.name ASC
```

---

## 🎯 Current Phase

**Phase 1: Wiki, Conventions, Domain Model Drafts** ✓

> Next: Phase 2 — Structured project import and validation engine.

---

## 🏷️ Tags

#bas #building-automation #hvac #controls #bacnet #niagara #commissioning #engineering-wiki