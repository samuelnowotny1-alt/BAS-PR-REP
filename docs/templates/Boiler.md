# Boiler Template

## Purpose
Provide a starting template for boiler documentation and generation.

## Scope
Applies to boiler graphics, logic, checkout, alarms, trends, and reports.

## Inputs
- Boiler equipment record.
- Boiler point list.
- Heating water sequence.
- Plant controller assignment.

## Outputs
- Boiler-specific requirements and generated artifacts.

## Dependencies
- [Equipment](../domain/equipment.md)
- [Alarms](../domain/alarms.md)

## Design Reasoning
Boiler control involves equipment protection, enable logic, temperature control, and plant sequencing. Safety-related behavior must come from approved sequences and equipment documentation.

## Future Improvements
- Add lead-lag patterns.
- Add plant enable templates.
- Add boiler safety point matrix.

## Examples
- Boiler enable should not be generated from heating demand alone if required flow proof or safety permissives are undefined.

