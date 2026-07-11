# Alarms

## Purpose
Define BAS alarm concepts and standards.

## Scope
Includes alarm sources, priorities, delays, messages, enable conditions, acknowledgements, and reporting.

## Inputs
- Sequences of operation.
- Owner standards.
- Point lists.
- Equipment models.

## Outputs
- Alarm requirements.
- Validation checks.
- Alarm report content.

## Dependencies
- [Points Model](../models/points.md)
- [Sequences](sequences.md)
- [Reports Conventions](../conventions/reports.md)

## Design Reasoning
Alarms must be actionable. Excessive, vague, or fabricated alarms reduce operator trust.

## Standards
- Define alarm condition, delay, priority, message, and enable state where possible.
- Avoid duplicate alarms for the same failure.
- Do not create alarm points without approved requirements.
- Include equipment identifier in alarm context.

## Future Improvements
- Add alarm priority matrix.
- Add nuisance alarm review workflow.
- Add standard alarm messages.

## Examples
- `AHU-1 Supply Fan Failure`: Command is on, proof remains off after approved delay.

