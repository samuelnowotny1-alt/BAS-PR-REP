# Project Model

## Purpose
Define the top-level structured representation of a BAS project.

## Scope
Includes project identity, buildings, systems, equipment, controllers, points, source documents, standards, and approval state.

## Inputs
- Project metadata.
- Imported schedules.
- Point lists.
- User configuration.

## Outputs
- Normalized project data.
- Inputs for validation and generation.

## Dependencies
- [Equipment Model](equipment.md)
- [Controller Model](controller.md)
- [Points Model](points.md)

## Design Reasoning
A project model provides one contract for all workflows. It prevents each generator from inventing its own interpretation of source data.

## Future Improvements
- Add schema format.
- Add source document provenance.
- Add multi-building support details.

## Examples
```yaml
project_id: placeholder
name: Placeholder BAS Project
buildings: []
equipment: []
controllers: []
points: []
```

