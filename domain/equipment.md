# Equipment

## Purpose
Define how BAS-controlled equipment is represented and reasoned about.

## Scope
Includes AHUs, RTUs, VAVs, boilers, pumps, chillers, cooling towers, and future equipment types.

## Inputs
- Equipment schedules.
- Mechanical drawings.
- Sequences of operation.
- Point lists.

## Outputs
- Equipment models.
- Required point expectations.
- Generated artifacts by equipment type.

## Dependencies
- [Equipment Model](../models/equipment.md)
- [Templates](../templates/AHU.md)
- [Sequences](sequences.md)

## Design Reasoning
Equipment type drives expected points, graphics, logic, alarms, trends, and checkout. Modeling equipment explicitly prevents free-form assumptions.

## Future Improvements
- Add required and optional point matrices.
- Add equipment relationship modeling.
- Add vendor-specific equipment variations.

## Examples
- A VAV with reheat typically needs damper command, airflow, zone temperature, and heating output points.
- A pump may require command, status, speed, alarm, and differential pressure context depending on system design.

