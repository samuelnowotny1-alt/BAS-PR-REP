# AHU Template

## Purpose
Provide a starting template for air handling unit documentation and generation.

## Scope
Applies to AHU graphics, logic, checkout, alarms, trends, and reports.

## Inputs
- AHU equipment record.
- AHU point list.
- Sequence of operation.
- Controller assignment.

## Outputs
- AHU-specific requirements and generated artifacts.

## Dependencies
- [Equipment](../domain/equipment.md)
- [Logic Conventions](../conventions/logic.md)
- [Graphics Conventions](../conventions/graphics.md)

## Design Reasoning
AHUs are central HVAC systems with many control modes and safeties. The assistant must validate required points and sequence details before generating outputs.

## Common Points
- Supply fan command and status.
- Supply air temperature.
- Mixed air or return air temperature when applicable.
- Outside air damper command.
- Cooling and heating valve commands when applicable.
- Filter status and safety alarms when applicable.

## Future Improvements
- Add AHU type variants.
- Add economizer rules.
- Add static pressure reset patterns.

## Examples
- Missing supply fan status should block fan failure alarm generation unless the sequence defines another proof method.

