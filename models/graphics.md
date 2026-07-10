# Graphics Model

## Purpose
Define structured data for BAS graphics.

## Scope
Includes graphic identity, equipment association, point bindings, navigation, layout metadata, and review status.

## Inputs
- Equipment model.
- Points model.
- Graphic conventions.

## Outputs
- Graphic definitions and binding lists.

## Dependencies
- [Graphics Conventions](../conventions/graphics.md)
- [Generate Graphics Workflow](../workflows/generate_graphics.md)

## Design Reasoning
Graphics should be generated from explicit bindings and equipment context so review can catch missing or incorrect data before deployment.

## Future Improvements
- Add layout schema.
- Add reusable symbols.
- Add vendor export model.

## Examples
```yaml
graphic_id: ahu_1
equipment_id: AHU-1
bindings:
  sat: AHU-1 SAT
```

