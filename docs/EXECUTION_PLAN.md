# Execution Plan

## Purpose
Translate the BAS Assistant vision and directional roadmap into an execution-grade build sequence with concrete outcomes, dependencies, and acceptance targets.

## Scope
This plan governs near-term implementation order for the commercial BAS Assistant platform. It is intentionally more operational than `ROADMAP.md`.

## Planning Rules
- Build trust before autonomy.
- Prefer deterministic engineering workflows before LLM-assisted workflows.
- Keep every phase shippable.
- Add tests and documentation in the same slice as feature work.
- Do not introduce BAS-facing AI behaviors until the supporting structured data exists.

## Current Baseline
Implemented platform areas at the time of this plan:
- FastAPI web UI with authentication and project membership controls.
- Structured persistence for projects, uploads, documents, knowledge, tasks, and BAS objects.
- CSV import workflows for equipment, points, and controllers.
- Niagara/PX and station-tree ingestion paths.
- Validation, checkout, report, graphics, logic, export, troubleshooting, and assumptions modules.
- Document library, knowledge library, artifact lineage, and controller topology views.

## Phase Sequence

### Phase A: Platform Hardening
Objective:
Stabilize deployment, runtime visibility, and operator confidence.

Deliverables:
- Production deployment docs and scripts stay accurate.
- Health, logging, and runtime path checks stay green.
- Sample data and templates remain synchronized with importer contracts.

Acceptance:
- Runtime infrastructure tests pass.
- Manual bootstrap on VPS follows documented steps without ad hoc fixes.

### Phase B: Retrieval-Ready Knowledge Engine
Objective:
Turn ingested documents into usable engineering reference material.

Deliverables:
- Searchable knowledge records and chunk retrieval.
- Project knowledge search UI and JSON API.
- Snippet rendering with source attribution and chunk metadata.
- Deterministic ranking baseline suitable for later vector search integration.

Acceptance:
- Engineers can upload a sequence, manual, or CSV and retrieve relevant passages from the UI.
- Tests cover ingestion, retrieval, and empty-result behavior.

### Phase C: BAS Object Review Workspace
Objective:
Make the structured project graph navigable enough for real engineering review.

Deliverables:
- Rich equipment, point, and controller detail pages.
- Cross-links between source artifacts, structured objects, and generated outputs.
- Object-level status, provenance, and engineering completeness indicators.

Acceptance:
- A project reviewer can trace a controller or point back to imported documents and generated artifacts.

### Phase D: Parser Expansion Framework
Objective:
Standardize how Niagara, PX, point lists, and future BACnet/Modbus parsers produce structured objects.

Deliverables:
- Parser contracts and parser result envelopes.
- Shared object-link persistence.
- Import summaries with warnings, diffs, and re-import behavior.

Acceptance:
- New parsers can be added without changing dashboard or object-review code paths.

### Phase E: Engineering Dashboard
Objective:
Turn the project detail page into an engineering control center instead of a navigation hub.

Deliverables:
- Project health summary.
- Recent uploads, knowledge, conversations, and task activity.
- Validation status, parser warnings, and generation readiness indicators.
- BAS-specific cards for equipment coverage, controller coverage, and document ingestion completeness.

Acceptance:
- A project lead can identify what is missing from a project within one screen.

### Phase F: Review-Grade Generators
Objective:
Deepen deterministic output quality for controls engineers.

Deliverables:
- Better logic narratives and sequence traceability.
- Stronger graphics metadata and binding diagnostics.
- Report packages with network topology, object provenance, and readiness summaries.

Acceptance:
- Generated outputs explain what source data they used and what assumptions remain unresolved.

### Phase G: AI Orchestration Layer
Objective:
Introduce bounded AI behaviors on top of structured project data.

Deliverables:
- Task-oriented AI orchestration contracts.
- Retrieval-backed question answering over project knowledge.
- Sequence explanation, logic review, and alarm review flows.
- Confidence, assumption, and provenance requirements enforced in outputs.

Acceptance:
- AI responses cite source chunks and structured BAS objects rather than inventing facts.

### Phase H: Simulator and Field Tooling
Objective:
Prepare for technician and commissioning workflows.

Deliverables:
- Simulated trends, alarms, schedules, and virtual devices.
- Replay-friendly data model for troubleshooting and field assistance.
- Raspberry Pi compatible runtime boundaries.

Acceptance:
- Example projects can run against simulated data for troubleshooting and demo workflows.

## Immediate Next Slices
1. Add deterministic knowledge retrieval over stored chunks.
2. Expose BAS object completeness and provenance more deeply in review pages.
3. Normalize parser contracts so import paths behave consistently.
4. Expand the project dashboard from counts to engineering status.

## Exit Criteria For Commercial Readiness
- Authentication, persistence, and deployment are repeatable.
- Import workflows preserve source lineage.
- Generated deliverables are deterministic and reviewable.
- Knowledge and AI workflows are retrieval-backed and source-attributed.
- Core BAS engineering workflows can be demonstrated end-to-end on representative projects.
