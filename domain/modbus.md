# Modbus

## Purpose
Document Modbus assumptions and standards for the project.

## Scope
Includes register maps, slave/server IDs, data types, scaling, read/write behavior, and validation.

## Inputs
- Modbus register maps.
- Vendor documentation.
- Integration requirements.

## Outputs
- Register mapping guidance.
- Validation warnings.
- Integration notes.

## Dependencies
- [Points Model](../models/points.md)
- [Controllers](controllers.md)

## Design Reasoning
Modbus integrations are sensitive to addressing, scaling, and data types. Guessing register details can produce incorrect equipment behavior.

## Standards
- Never infer register address, scaling, or word order without a source.
- Record units and scaling explicitly.
- Distinguish read-only and writable registers.
- Validate data type and register length.

## Future Improvements
- Add register map schema.
- Add endian and word-order profiles.
- Add vendor examples.

## Examples
- A temperature register may require a scale factor of `0.1`; this must come from documentation, not AI inference.

