# Checkout Conventions

## Purpose
Define standards for commissioning and checkout artifacts.

## Scope
Applies to point-to-point checkout, functional testing, prefunctional checks, issue tracking, and generated forms.

## Inputs
- Validated point list.
- Equipment model.
- Sequence requirements.
- Commissioning requirements.

## Outputs
- Checkout sheets.
- Functional test procedures.
- Issue lists.
- Completion status summaries.

## Dependencies
- [Checkout Model](../models/checkout.md)
- [Commissioning](../domain/commissioning.md)
- [Generate Checkout Workflow](../workflows/generate_checkout.md)

## Design Reasoning
Checkout documents must be executable in the field. Each step should be specific, observable, and tied to approved project data.

## Standards
- Include equipment identifier and controller identifier.
- List point name, type, source, expected behavior, and verification method.
- Distinguish physical checkout from software simulation.
- Track pass, fail, not applicable, and blocked states.
- Do not mark generated steps as complete without human input.

## Future Improvements
- Add mobile-friendly checkout format.
- Add issue export format.
- Add sample functional test scripts.

## Examples
- `SAT`: Verify sensor reading against calibrated instrument and record observed value.
- `SF-C`: Command fan on and verify proof status, current, or approved feedback point.

