# Trends

## Purpose
Define trend logging concepts and standards.

## Scope
Includes trend point selection, intervals, change-of-value behavior, retention, and analysis.

## Inputs
- Owner standards.
- Point lists.
- Equipment models.
- Troubleshooting needs.

## Outputs
- Trend requirements.
- Trend validation warnings.
- Troubleshooting datasets.

## Dependencies
- [Points Model](../models/points.md)
- [Troubleshoot Workflow](../workflows/troubleshoot.md)

## Design Reasoning
Trends provide operational evidence. They should be selected intentionally to support commissioning, energy review, and troubleshooting.

## Standards
- Trend key commands, statuses, sensors, setpoints, and outputs where required.
- Use appropriate interval or change-of-value settings.
- Document retention assumptions.
- Do not treat missing trend data as proof of normal operation.

## Future Improvements
- Add standard trend profiles by equipment type.
- Add anomaly detection rules.
- Add trend export schema.

## Examples
- AHU troubleshooting may require supply air temperature, discharge setpoint, fan command, fan status, cooling valve command, and outside air temperature.

