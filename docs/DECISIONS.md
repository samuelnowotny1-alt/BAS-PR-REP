# Decision Log

## Purpose
Record meaningful project decisions and the reasoning behind them.

## Scope
Use this log for architecture, conventions, data contracts, AI behavior, engineering standards, tooling, and workflow decisions. Minor implementation details may remain in code comments or pull requests.

## Inputs
- Design proposals.
- Engineering constraints.
- Review feedback.
- Lessons from implementation.

## Outputs
- Historical decision record.
- Rationale for current behavior.
- Review queue for decisions that may change.

## Dependencies
- [Architecture](ARCHITECTURE.md)
- [Design Principles](DESIGN_PRINCIPLES.md)
- [Roadmap](ROADMAP.md)

## Design Reasoning
Engineering projects accumulate context that is often lost. This log preserves why choices were made so future contributors do not repeat old debates or silently reverse important assumptions.

## Entry Template
```markdown
## YYYY-MM-DD - Decision Title

- Date: YYYY-MM-DD
- Decision:
- Reason:
- Alternatives considered:
- Consequences:
- Future review status:
```

## Decisions

## 2026-07-03 - Establish Wiki Before Application Logic

- Date: 2026-07-03
- Decision: Create the engineering wiki before writing application logic.
- Reason: The project needs stable conventions, architectural intent, and AI behavior rules before generated code or outputs exist.
- Alternatives considered: Start coding first and document later; document only after the first prototype.
- Consequences: Early development may move slower, but future agents and developers gain a shared source of truth.
- Future review status: Review after the first working prototype.

## 2026-07-03 - Prefer Deterministic Generators Over AI Execution

- Date: 2026-07-03
- Decision: Use deterministic scripts for repeatable output generation whenever possible.
- Reason: BAS deliverables must be reproducible, testable, and explainable.
- Alternatives considered: Let AI directly generate final graphics, logic, and reports from prompts.
- Consequences: More structured models and validators are required, but output quality is easier to verify.
- Future review status: Permanent principle; review only for low-risk assistive features.

## 2026-07-03 - Human Engineer Remains Final Authority

- Date: 2026-07-03
- Decision: Treat generated BAS outputs as suggestions until approved by a qualified human.
- Reason: BAS programming can affect equipment operation, comfort, safety, and energy performance.
- Alternatives considered: Fully automated approval for validated outputs.
- Consequences: Workflows must include review states and approval tracking.
- Future review status: Permanent principle.

## 2026-07-11 - Niagara Export Uses JSON Canonical Model with Parallel XML

- Date: 2026-07-11
- Decision: Keep the Niagara JSON station model as the canonical export graph and generate Niagara-shaped XML/WXF/PX artifacts from that model in parallel.
- Reason: The station semantics, ORD generation, hierarchy, and PX bindings are the hard part; keeping one canonical model reduces drift while allowing iterative XML compatibility work.
- Alternatives considered: Write XML directly with no intermediate model; stop at JSON-only review artifacts.
- Consequences: JSON and XML outputs must stay aligned through regression tests, and compatibility work should focus on serializer changes instead of duplicating business logic.
- Future review status: Revisit when a real Niagara reference export is available and import compatibility becomes the primary target.

## Future Improvements
- Add decision identifiers.
- Add links from decisions to implementation files.
- Add superseded decision status.

## Examples
- Record a new BACnet object naming convention here before applying it across generators.
- Record a vendor-specific Niagara export strategy here before implementing it.
