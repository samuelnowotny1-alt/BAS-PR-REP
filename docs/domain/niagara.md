# Niagara

## Purpose
Document Niagara-related assumptions and integration guidance.

## Scope
Includes station organization, components, points, graphics, histories, alarms, and future export strategy.

## Inputs
- Niagara station standards.
- Vendor conventions.
- Project point lists.
- Graphic and logic requirements.

## Outputs
- Niagara mapping guidance.
- Export constraints.
- Review notes.

## Dependencies
- [Graphics Conventions](../conventions/graphics.md)
- [Logic Conventions](../conventions/logic.md)
- [BACnet](bacnet.md)

## Design Reasoning
Niagara is often both a supervisory platform and an engineering environment. The assistant should produce structured artifacts that can be reviewed before any station import.

## Standards
- Keep station paths explicit.
- Do not overwrite station components without confirmation.
- Separate generated suggestions from approved station changes.
- Preserve project naming conventions.

## Future Improvements
- Add Niagara file/export format decisions.
- Add station path conventions.
- Add component template library.

## Examples
- A generated AHU graphic binding list should be reviewable before being applied to a Niagara station.

