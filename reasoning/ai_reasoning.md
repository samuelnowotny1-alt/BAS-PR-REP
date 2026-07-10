# AI Reasoning Guidelines

## Purpose
Define how AI agents should behave in this project.

## Scope
Applies to planning, documentation, validation support, generated explanations, troubleshooting, and review assistance.

## Inputs
- Structured project data.
- Source documents.
- User requests.
- Validation results.

## Outputs
- Reasoned explanations.
- Draft documentation.
- Gap lists.
- Suggested outputs pending approval.

## Dependencies
- [Assumptions](assumptions.md)
- [Confidence](confidence.md)
- [Validation](validation.md)

## Design Reasoning
AI is useful for language, organization, and reasoning support, but BAS engineering requires traceability and human approval.

## Rules
- Never invent BACnet objects.
- Never fabricate point names.
- Always explain reasoning when generating control logic.
- Validate sequences before creating outputs.
- Ask for clarification if required information is missing.
- Never overwrite user work without confirmation.
- Treat generated outputs as suggestions unless explicitly approved.
- State assumptions explicitly.
- Prefer structured inputs over free-form prompts.

## Future Improvements
- Add prompt templates.
- Add approval-state model.
- Add examples of acceptable uncertainty language.

## Examples
- Good: "The sequence requires fan proof, but no proof point is present. Logic generation is blocked until this is clarified."
- Bad: "I created `AHU-1 SF Proof` because the fan probably needs it."

