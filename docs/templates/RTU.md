# RTU Template

## Purpose
Provide a starting template for rooftop unit documentation and generation.

## Scope
Applies to RTU graphics, logic, checkout, alarms, trends, and reports.

## Inputs
- RTU equipment record.
- RTU point list.
- Sequence of operation.
- Controller assignment.

## Outputs
- RTU-specific requirements and generated artifacts.

## Dependencies
- [Equipment](../domain/equipment.md)
- [Checkout Conventions](../conventions/checkout.md)

## Design Reasoning
RTUs vary widely by packaged controls, staged heating/cooling, economizers, and integration depth. Generation must reflect actual available points.

## Future Improvements
- Add staged cooling/heating patterns.
- Add economizer templates.
- Add packaged unit integration examples.

## Examples
- If only BACnet integration points are available, checkout should verify communicated values rather than physical I/O wiring.

