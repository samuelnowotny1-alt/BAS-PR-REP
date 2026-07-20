# BAS Assistant Engineering Wiki

## Purpose
This wiki is the single source of truth for the BAS programming assistant. It records architecture, conventions, engineering standards, domain assumptions, workflows, reasoning rules, and decision history.

## Scope
The wiki governs planning, implementation, testing, documentation, and generated BAS deliverables. It applies to human contributors and AI agents.

## Inputs
- Project requirements and user-approved decisions.
- BAS standards, equipment schedules, point lists, sequences, and submittals.
- Source code, tests, generated artifacts, and review feedback.

## Outputs
- Authoritative project guidance.
- Cross-linked engineering references.
- Decision records and implementation constraints.
- Templates for common BAS equipment and workflows.

## Dependencies
- [Vision](VISION.md)
- [Architecture](ARCHITECTURE.md)
- [Design Principles](DESIGN_PRINCIPLES.md)
- [Decision Log](DECISIONS.md)
- [Roadmap](ROADMAP.md)
- [Execution Plan](EXECUTION_PLAN.md)
- [Project Status](PROJECT_STATUS.md)
- [Project Audit](PROJECT_AUDIT.md)

## Design Reasoning
The wiki exists before application logic so the project has stable engineering boundaries from day one. Future code should conform to documented behavior. If code and documentation conflict, the discrepancy must be recorded and reviewed instead of silently changing behavior.

## Future Improvements
- Add project-specific diagrams after the first prototype.
- Link code modules to documentation sections.
- Add generated documentation checks in CI.
- Add examples from real approved BAS projects.

## Examples
- Use [Point Naming](conventions/naming.md) before generating points.
- Use [AI Reasoning](reasoning/ai_reasoning.md) before asking an AI agent to draft logic.
- Use [Decision Log](DECISIONS.md) when making architectural tradeoffs.
