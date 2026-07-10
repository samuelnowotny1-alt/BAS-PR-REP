# Equipment Model

## Purpose
Define structured equipment data.

## Scope
Includes equipment identity, type, location, served area, relationships, required points, sequence references, and controller assignment.

## Inputs
- Equipment schedules.
- Mechanical drawings.
- Point lists.
- Sequences.

## Outputs
- Equipment records used by graphics, logic, checkout, and reports.

## Dependencies
- [Equipment Domain](../domain/equipment.md)
- [Templates](../templates/AHU.md)

## Design Reasoning
Equipment-specific modeling keeps generation grounded in real system context.

## Future Improvements
- Add required fields by equipment type.
- Add relationships such as AHU-to-VAV and chiller-to-pump.
- Add design capacity fields.

## Examples
```yaml
id: AHU-1
type: AHU
location: Mechanical Room
controller_id: MPC-1
```

