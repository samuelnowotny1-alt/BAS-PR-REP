# Design Principles

## Purpose
Define the engineering principles that govern project decisions.

## Scope
Applies to code, documentation, data models, generation workflows, AI usage, testing, and review.

## Inputs
- Project vision.
- BAS engineering risk.
- Maintainability requirements.

## Outputs
- Decision criteria.
- Implementation guardrails.
- Review standards.

## Dependencies
- [Vision](VISION.md)
- [Engineering Rules](reasoning/engineering_rules.md)
- [Python Conventions](conventions/python.md)

## Design Reasoning
BAS software affects real buildings, equipment, occupants, energy use, and maintenance workflows. The assistant must favor repeatability, transparency, and reviewability over clever automation.

## Principles
- Prefer deterministic scripts for repeatable generation.
- Treat AI output as advisory unless explicitly approved.
- Keep modules independently testable.
- Use structured data as the contract between modules.
- Make configuration explicit.
- Minimize hidden state and global mutation.
- Keep components cohesive and loosely coupled.
- Preserve traceability from input data to generated output.
- Fail clearly when required information is missing.
- Keep humans responsible for final engineering approval.

## Future Improvements
- Add examples of accepted and rejected designs.
- Convert principles into automated linting and review checks.

## Examples
- A generator should take a typed equipment model and return a predictable artifact.
- A validator should produce clear errors instead of guessing missing units or point types.

