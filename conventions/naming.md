# Naming Conventions

## Purpose
Define naming standards for equipment, controllers, points, files, and generated artifacts.

## Scope
Applies to source data, internal models, generated BAS outputs, documentation, and tests.

## Inputs
- Project naming standards.
- Equipment schedules.
- Point lists.
- Controller inventories.

## Outputs
- Consistent names across the project.
- Validation errors for invalid or ambiguous names.
- Predictable generated file and object names.

## Dependencies
- [Points Model](../models/points.md)
- [Equipment Model](../models/equipment.md)
- [Controller Model](../models/controller.md)

## Design Reasoning
Naming is an engineering interface. Inconsistent names cause commissioning errors, graphics confusion, and logic defects. The assistant must never invent point names or equipment names when source data is missing.

## Standards
- Equipment names should use a stable equipment type prefix and numeric identifier, such as `AHU-1`, `VAV-203`, or `CHWP-1`.
- Controller names should identify panel, location, or served equipment when available.
- Point names should be descriptive, deterministic, and traceable to source documents.
- File names should use lowercase words separated by underscores.
- Generated names must preserve approved project identifiers.

## Future Improvements
- Add customer-specific naming profiles.
- Add BACnet object name and instance validation.
- Add collision detection examples.

## Examples
- Valid equipment: `AHU-1`, `RTU-2`, `VAV-121`.
- Valid internal file: `ahu_1_checkout.md`.
- Invalid behavior: creating `Zone Temp 1` when no source point exists.

