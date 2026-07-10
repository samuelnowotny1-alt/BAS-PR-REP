# Import Project Workflow

## Purpose
Describe how source project data enters the assistant.

## Scope
Includes importing schedules, point lists, controller data, sequences, and configuration into structured models.

## Inputs
- Project files.
- User-provided configuration.
- Naming standards.

## Outputs
- Normalized project model.
- Import warnings and errors.
- Source provenance records.

## Dependencies
- [Project Model](../models/project.md)
- [Validation](../reasoning/validation.md)

## Design Reasoning
Import should preserve source data and normalize it without silently correcting engineering meaning.

## Future Improvements
- Add supported file formats.
- Add import preview UI.
- Add duplicate detection.

## Examples
- A spreadsheet point list becomes structured point records with source row references.

