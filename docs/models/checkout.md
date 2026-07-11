# Checkout Model

## Purpose
Define structured data for checkout and commissioning workflows.

## Scope
Includes checkout items, equipment references, point references, expected results, observed results, status, evidence, and reviewer notes.

## Inputs
- Point model.
- Equipment model.
- Commissioning requirements.
- Human observations.

## Outputs
- Checkout sheets.
- Completion reports.
- Issue lists.

## Dependencies
- [Checkout Conventions](../conventions/checkout.md)
- [Commissioning](../domain/commissioning.md)

## Design Reasoning
Checkout data must distinguish generated instructions from field-verified results.

## Future Improvements
- Add evidence attachment schema.
- Add issue tracking integration.
- Add status transition rules.

## Examples
```yaml
point: AHU-1 SAT
method: compare_to_calibrated_instrument
status: not_started
```

