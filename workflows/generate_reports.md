# Generate Reports Workflow

## Purpose
Describe how project reports are generated.

## Scope
Includes validation reports, checkout summaries, point summaries, graphics summaries, and logic review reports.

## Inputs
- Project model.
- Validation results.
- Generated artifacts.
- Review statuses.

## Outputs
- Human-readable reports.
- Machine-readable report data where useful.

## Dependencies
- [Report Conventions](../conventions/reports.md)
- [Validation](../reasoning/validation.md)

## Design Reasoning
Reports should separate confirmed facts from assumptions, warnings, and recommendations.

## Future Improvements
- Add report renderer.
- Add PDF/HTML export strategy.
- Add audience-specific templates.

## Examples
- A report may summarize all missing BACnet instance numbers by controller and equipment.

