# Confidence

## Purpose
Define how confidence should be communicated.

## Scope
Applies to AI explanations, validation results, troubleshooting hypotheses, generated outputs, and reports.

## Inputs
- Source data quality.
- Validation status.
- Number and severity of assumptions.
- Human approvals.

## Outputs
- Confidence statements.
- Review requirements.
- Risk indicators.

## Dependencies
- [Validation](validation.md)
- [Assumptions](assumptions.md)

## Design Reasoning
Confidence should reflect evidence, not tone. A confident answer without traceable support is unsafe for BAS engineering.

## Standards
- Tie confidence to source quality.
- Lower confidence when required data is missing.
- Do not use confidence to bypass review.
- Separate likely hypotheses from confirmed facts.

## Future Improvements
- Add scoring rubric.
- Add confidence labels by workflow.
- Add examples from real projects.

## Examples
- High confidence: all required points are present, sequence is explicit, and output passed validation.
- Low confidence: trend data is missing and alarm condition is inferred from user description.

