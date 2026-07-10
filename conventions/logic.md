# Logic Conventions

## Purpose
Define standards for generated control logic and logic documentation.

## Scope
Applies to sequence interpretation, control blocks, interlocks, modes, alarms, resets, and generated logic explanations.

## Inputs
- Approved sequences of operation.
- Validated points.
- Equipment models.
- Controller capabilities.

## Outputs
- Reviewable control logic artifacts.
- Logic explanations.
- Validation warnings and missing-information lists.

## Dependencies
- [Logic Model](../models/logic.md)
- [Sequences](../domain/sequences.md)
- [Generate Logic Workflow](../workflows/generate_logic.md)

## Design Reasoning
Control logic must be traceable to approved sequences. AI may help explain logic but must not invent control requirements or silently fill in missing engineering details.

## Standards
- Validate required points before generating logic.
- Separate modes, setpoints, safeties, alarms, and overrides.
- Make interlocks explicit.
- Include source references when possible.
- Explain assumptions in generated logic review notes.

## Future Improvements
- Add reusable logic patterns by equipment type.
- Add simulation tests for common sequences.
- Add vendor-specific export mappings.

## Examples
- If an AHU has a supply fan command but no proof point, generated logic should flag the missing proof requirement before creating a fan failure alarm.

