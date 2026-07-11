# Logic Model

## Purpose
Define structured data for control logic generation.

## Scope
Includes modes, setpoints, control loops, safeties, alarms, schedules, overrides, and source references.

## Inputs
- Sequences.
- Equipment model.
- Points model.
- Controller capabilities.

## Outputs
- Logic requirements and generated logic artifacts.

## Dependencies
- [Logic Conventions](../conventions/logic.md)
- [Sequences](../domain/sequences.md)

## Design Reasoning
Logic generation needs a structured intermediate representation so behavior can be validated before vendor-specific export.

## Future Improvements
- Add logic block schema.
- Add simulation harness.
- Add traceability to source sequence paragraphs.

## Examples
```yaml
modes:
  occupied:
    source: sequence_placeholder
setpoints: []
safeties: []
```

