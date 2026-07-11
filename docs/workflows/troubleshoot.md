# Troubleshoot Workflow

## Purpose
Describe how the assistant supports BAS troubleshooting.

## Scope
Includes interpreting alarms, trends, point status, sequence context, and user observations.

## Inputs
- Alarm history.
- Trend data.
- Current point values.
- Equipment and sequence models.
- User observations.

## Outputs
- Diagnostic hypotheses.
- Recommended checks.
- Data gaps.
- Explanation of reasoning.

## Dependencies
- [Trends](../domain/trends.md)
- [Alarms](../domain/alarms.md)
- [AI Reasoning](../reasoning/ai_reasoning.md)

## Design Reasoning
Troubleshooting should produce transparent reasoning and recommended verification steps, not unsupported certainty.

## Future Improvements
- Add diagnostic rule library.
- Add trend analysis tools.
- Add confidence scoring examples.

## Examples
- If discharge air temperature is high while cooling valve command is full open, check valve feedback, chilled water availability, coil condition, and sensor accuracy.

