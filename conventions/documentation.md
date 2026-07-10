# Documentation Conventions

## Purpose
Define how project documentation should be written and maintained.

## Scope
Applies to this wiki, code comments, generated documentation, README files, and implementation notes.

## Inputs
- Engineering decisions.
- Source code behavior.
- Domain standards.
- User review feedback.

## Outputs
- Clear Markdown documentation.
- Consistent document structure.
- Traceable design reasoning.

## Dependencies
- [Decision Log](../DECISIONS.md)
- [README](../README.md)

## Design Reasoning
Documentation must explain why the system behaves as it does. A future developer or AI agent should be able to reconstruct intent without guessing from code alone.

## Standards
- Use clear Markdown headings.
- Include purpose, scope, inputs, outputs, dependencies, design reasoning, future improvements, and examples.
- Link related documents.
- Prefer concrete examples over vague guidance.
- Mark unknown project-specific details as placeholders.
- Update documentation when behavior changes.

## Future Improvements
- Add documentation linting.
- Add diagrams for stable workflows.
- Add generated API reference after code exists.

## Examples
- Good: "This validator fails closed because missing point units can create unsafe assumptions."
- Weak: "Validate points."

