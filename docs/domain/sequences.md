# Sequences

## Purpose
Define how sequences of operation are interpreted and validated.

## Scope
Includes modes, setpoints, resets, safeties, alarms, scheduling, overrides, and equipment-specific behavior.

## Inputs
- Approved sequence documents.
- Equipment models.
- Point lists.
- Owner standards.

## Outputs
- Structured sequence requirements.
- Logic generation inputs.
- Validation gaps and assumptions.

## Dependencies
- [Logic Conventions](../conventions/logic.md)
- [Logic Model](../models/logic.md)
- [AI Reasoning](../reasoning/ai_reasoning.md)

## Design Reasoning
Sequences are the authority for control behavior. The assistant may summarize and structure them but must not add requirements that are not present or approved.

## Standards
- Preserve source wording where it affects behavior.
- Flag ambiguous modes or missing setpoints.
- Identify required points for each sequence step.
- Validate safeties before normal control logic.

## Future Improvements
- Add sequence parser schema.
- Add common sequence pattern library.
- Add traceability from generated logic to sequence paragraphs.

## Examples
- If a sequence says "reset duct static pressure based on VAV demand," the demand source and reset range must be defined before implementation.

