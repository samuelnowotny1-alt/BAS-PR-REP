# Graphics Conventions

## Purpose
Define standards for BAS graphics generated or reviewed by the assistant.

## Scope
Applies to equipment graphics, navigation graphics, point binding, labels, colors, and generated graphic metadata.

## Inputs
- Equipment models.
- Point models.
- Project graphic standards.
- Customer or vendor requirements.

## Outputs
- Consistent graphic definitions.
- Clear point binding lists.
- Reviewable generated graphics.

## Dependencies
- [Graphics Model](../models/graphics.md)
- [Generate Graphics Workflow](../workflows/generate_graphics.md)
- [Equipment Domain](../domain/equipment.md)

## Design Reasoning
BAS graphics are operational tools. They should prioritize clarity, accurate status, and maintainability over decoration.

## Standards
- Bind graphics only to validated points.
- Show command, status, alarm, and key sensor values clearly.
- Use consistent equipment symbols and labels.
- Avoid hiding critical points behind ambiguous icons.
- Do not fabricate values, bindings, or navigation links.

## Future Improvements
- Add standard color palette.
- Add symbol library references.
- Add vendor-specific graphic export rules.

## Examples
- AHU graphics should show fan status, discharge air temperature, relevant damper positions, valve positions, and active alarms when available.
- Missing chilled water valve feedback should appear as a validation gap, not as a fabricated binding.

