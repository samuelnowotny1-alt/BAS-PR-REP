# Assumptions

## Purpose
Define how assumptions are identified, recorded, and reviewed.

## Scope
Applies to imported data, generated artifacts, AI explanations, troubleshooting, and documentation.

## Inputs
- Missing or ambiguous source data.
- User instructions.
- Validation findings.

## Outputs
- Assumption records.
- Review prompts.
- Approval or rejection status.

## Dependencies
- [AI Reasoning](ai_reasoning.md)
- [Validation](validation.md)

## Design Reasoning
Assumptions are sometimes necessary, but hidden assumptions create engineering risk. All assumptions must be visible and reviewable.

## Standards
- State what is assumed.
- Explain why the assumption was made.
- Identify affected outputs.
- Mark whether approval is required.
- Replace assumptions with confirmed data when available.

## Future Improvements
- Add assumption tracking model.
- Add assumption expiration/review status.
- Add UI review workflow.

## Examples
- "Assumed `AHU-1` is served by `MPC-1` because all AHU-1 points are grouped under that controller in the point list. Requires review."

