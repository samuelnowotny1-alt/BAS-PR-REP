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
- Use the `fieldline` visual system for generated SVGs.
- Keep equipment neutral and reserve process color for airflow and water media.
- Use cyan for supply air, warm brown for return air, blue for chilled water,
  teal for condenser water, and orange for heating water.
- Reserve red for actionable alarm state.
- Keep title, system state, and media legend outside the process work area.
- Use labeled zones to group plant equipment, distribution, and terminal loads.
- Add directional markers to process lines without relying on animation alone.
- Preserve accessible SVG titles and descriptions.

## Asset Policy
- Runtime product graphics are original code-generated SVG.
- External libraries require explicit redistribution rights and recorded provenance.
- Customer-licensed Niagara assets must be side-loaded outside Git.
- See [BAS Graphics Source Catalog](../GRAPHICS_SOURCE_CATALOG.md).

## Examples
- AHU graphics should show fan status, discharge air temperature, relevant damper positions, valve positions, and active alarms when available.
- Missing chilled water valve feedback should appear as a validation gap, not as a fabricated binding.
