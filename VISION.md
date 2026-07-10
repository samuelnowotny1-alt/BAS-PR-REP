# Vision

## Purpose
Define the long-term purpose of the BAS programming assistant.

## Scope
This document covers product philosophy, success criteria, boundaries, and user expectations. It does not define implementation details.

## Inputs
- User goals.
- BAS engineering practices.
- Feedback from technicians, controls engineers, programmers, and commissioning agents.

## Outputs
- Shared product direction.
- Criteria for evaluating features.
- Guardrails for automation and AI use.

## Dependencies
- [Design Principles](DESIGN_PRINCIPLES.md)
- [AI Reasoning](reasoning/ai_reasoning.md)
- [Roadmap](ROADMAP.md)

## Design Reasoning
The assistant should reduce repetitive BAS engineering work while preserving human engineering authority. Deterministic scripts should perform repeatable transformations. AI should explain, plan, summarize, and identify gaps, but it must not become the unchecked source of critical engineering calculations or invented project data.

## Core Principles
- Deterministic scripts over AI execution whenever possible.
- AI is used for reasoning, planning, explanation, and documentation, not for critical engineering calculations.
- Every module should be independently testable.
- Minimize hidden state.
- Use structured data instead of free-form prompts.
- Prefer explicit configuration over implicit behavior.
- Modular architecture with low coupling and high cohesion.
- Human engineers remain the final authority for engineering decisions.

## Future Improvements
- Define measurable productivity targets.
- Identify primary user personas.
- Add non-goals for unsupported BAS tasks.

## Examples
- Good: Import a structured point list and validate naming before generating outputs.
- Bad: Ask AI to invent missing BACnet objects from a vague equipment description.

