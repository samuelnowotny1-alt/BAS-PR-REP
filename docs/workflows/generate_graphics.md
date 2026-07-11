# Generate Graphics Workflow

## Purpose
Describe how BAS graphics are generated.

## Scope
Includes selecting equipment templates, binding validated points, producing reviewable graphic artifacts, and reporting missing data.

## Inputs
- Equipment model.
- Points model.
- Graphic conventions.

## Outputs
- Graphic definitions.
- Binding reports.
- Missing point warnings.

## Dependencies
- [Graphics Model](../models/graphics.md)
- [Graphics Conventions](../conventions/graphics.md)

## Design Reasoning
Graphics generation must be deterministic and reviewable. Missing bindings should be reported instead of invented.

## Future Improvements
- Add graphic renderer/exporter.
- Add preview workflow.
- Add vendor-specific output mappings.

## Examples
- Generate `ahu_1` from the AHU template only after required AHU points are validated.

