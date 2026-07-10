# Pump Template

## Purpose
Provide a starting template for pump documentation and generation.

## Scope
Applies to pump graphics, logic, checkout, alarms, trends, and reports.

## Inputs
- Pump equipment record.
- Pump point list.
- Hydronic sequence.
- Controller or VFD assignment.

## Outputs
- Pump-specific requirements and generated artifacts.

## Dependencies
- [Equipment](../domain/equipment.md)
- [Checkout Conventions](../conventions/checkout.md)

## Design Reasoning
Pump control commonly depends on enable logic, proof, speed control, differential pressure, lead-lag sequencing, and alarms. These must be explicit.

## Future Improvements
- Add constant-speed and variable-speed variants.
- Add lead-lag rules.
- Add VFD integration profiles.

## Examples
- A pump speed command requires a defined control variable, such as differential pressure, before speed loop generation.

