# Cooling Tower Template

## Purpose
Provide a starting template for cooling tower documentation and generation.

## Scope
Applies to cooling tower graphics, logic, checkout, alarms, trends, and reports.

## Inputs
- Cooling tower equipment record.
- Cooling tower point list.
- Condenser water sequence.
- Controller or VFD assignment.

## Outputs
- Cooling-tower-specific requirements and generated artifacts.

## Dependencies
- [Equipment](../domain/equipment.md)
- [Trends](../domain/trends.md)

## Design Reasoning
Cooling tower control may include fan staging, speed control, basin temperature protection, condenser water temperature control, and alarms. Required behavior must be sequence-driven.

## Future Improvements
- Add multi-cell tower sequencing.
- Add freeze protection patterns.
- Add condenser water reset rules.

## Examples
- Fan speed logic should not be generated until condenser water temperature control requirements and available fan speed points are confirmed.

