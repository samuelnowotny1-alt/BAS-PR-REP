# BACnet

## Purpose
Document BACnet assumptions and standards for the project.

## Scope
Includes BACnet objects, naming, instances, device identity, services, and validation boundaries.

## Inputs
- BACnet device lists.
- Object lists.
- Vendor documentation.
- Project specifications.

## Outputs
- BACnet validation rules.
- Object mapping guidance.
- Integration notes.

## Dependencies
- [Naming Conventions](../conventions/naming.md)
- [Points Model](../models/points.md)
- [Controllers](controllers.md)

## Design Reasoning
BACnet objects are integration contracts. The assistant must never invent BACnet objects, instance numbers, device IDs, or object names.

## Standards
- Use provided object identifiers when available.
- Flag missing instance numbers as unresolved.
- Preserve object type and units.
- Distinguish BACnet object name from internal point name.

## Future Improvements
- Add supported object type matrix.
- Add BACnet export validation.
- Add device/object collision detection.

## Examples
- `analog-input,1` and `AI-1` may refer to the same object but should not be conflated without explicit mapping.

