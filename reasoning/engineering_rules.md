# Engineering Rules

## Purpose
Define engineering rules that should guide validation and generation.

## Scope
Applies to BAS points, equipment, logic, graphics, alarms, trends, checkout, and reports.

## Inputs
- Project standards.
- Equipment and point models.
- Sequences.
- Human-approved decisions.

## Outputs
- Validation checks.
- Generation constraints.
- Review criteria.

## Dependencies
- [Design Principles](../DESIGN_PRINCIPLES.md)
- [Validation](validation.md)

## Design Reasoning
Engineering rules make assumptions explicit and testable. They reduce reliance on subjective prompt interpretation.

## Rules
- Required data must be present before critical outputs are generated.
- Safety and equipment protection logic takes precedence over optimization.
- Commands and statuses must be distinguished.
- Units must be explicit for analog values.
- Source provenance should be preserved.
- Unknowns should become review items, not silent defaults.

## Future Improvements
- Add formal rules engine.
- Add severity levels.
- Add rule identifiers.

## Examples
- A cooling valve command without units may be acceptable if represented as percent open; a temperature without units is not acceptable.

