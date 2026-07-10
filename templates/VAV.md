# VAV Template

## Purpose
Provide a starting template for variable air volume terminal unit documentation and generation.

## Scope
Applies to VAV graphics, logic, checkout, alarms, trends, and reports.

## Inputs
- VAV equipment record.
- VAV point list.
- Sequence of operation.
- Controller assignment.

## Outputs
- VAV-specific requirements and generated artifacts.

## Dependencies
- [Equipment](../domain/equipment.md)
- [Sequences](../domain/sequences.md)

## Design Reasoning
VAV behavior depends on zone temperature, airflow, damper control, occupancy, and reheat configuration. Required points must be validated by VAV type.

## Future Improvements
- Add cooling-only, reheat, fan-powered, and dual-duct variants.
- Add airflow calibration checkout.
- Add demand reset participation rules.

## Examples
- A reheat VAV should not generate heating logic unless the reheat output and sequence requirements are present.

