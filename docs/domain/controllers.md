# Controllers

## Purpose
Define BAS controller concepts and representation.

## Scope
Includes controller identity, served equipment, network address, protocol role, capacity, and point ownership.

## Inputs
- Controller schedules.
- Network drawings.
- Panel layouts.
- Vendor submittals.

## Outputs
- Controller models.
- Mapping between equipment and controllers.
- Validation of point ownership and addressing.

## Dependencies
- [Controller Model](../models/controller.md)
- [BACnet](bacnet.md)
- [Modbus](modbus.md)

## Design Reasoning
Controllers are deployment boundaries. Logic, point addressing, and checkout often depend on which controller owns which points.

## Future Improvements
- Add controller capability profiles.
- Add I/O capacity validation.
- Add network addressing rules.

## Examples
- `MPC-1` may serve `AHU-1` and own all related AHU points.
- A supervisory controller may reference points but not physically own I/O.

