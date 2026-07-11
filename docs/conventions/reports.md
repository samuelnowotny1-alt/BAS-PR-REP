# Report Conventions

## Purpose
Define standards for generated reports.

## Scope
Applies to validation reports, checkout reports, project summaries, point summaries, graphics reports, and logic review reports.

## Inputs
- Structured project data.
- Validation results.
- Generated artifacts.
- Human review status.

## Outputs
- Clear reports for engineering, commissioning, and project management.

## Dependencies
- [Generate Reports Workflow](../workflows/generate_reports.md)
- [Validation](../reasoning/validation.md)

## Design Reasoning
Reports should help users make decisions. They should separate facts, assumptions, warnings, errors, and recommendations.

## Standards
- Include generation date and source data version when available.
- Label assumptions explicitly.
- Group errors by equipment, controller, and severity.
- Avoid unsupported claims.
- Preserve traceability to source inputs.

## Future Improvements
- Add report templates by audience.
- Add export formats such as PDF, HTML, and CSV.
- Add executive summary generation rules.

## Examples
- A validation report should list missing required points before listing optional recommendations.

