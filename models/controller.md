# Controller Model

## Purpose
Define structured controller data.

## Scope
Includes controller ID, name, type, network identity, served equipment, point ownership, and capabilities.

## Inputs
- Controller schedules.
- Network diagrams.
- Point ownership tables.

## Outputs
- Controller records for validation, checkout, and generation.

## Dependencies
- [Controllers Domain](../domain/controllers.md)
- [Points Model](points.md)

## Design Reasoning
Controllers are important deployment and validation boundaries. Explicit modeling helps detect missing ownership, overloaded panels, and unclear network addresses.

## Future Improvements
- Add capability profiles by vendor/model.
- Add I/O capacity schema.
- Add network address validation.

## Examples
```yaml
id: MPC-1
serves:
  - AHU-1
protocols:
  - BACnet/IP
```

