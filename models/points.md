# Points Model

## Purpose
Define structured BAS point data.

## Scope
Includes point identity, type, units, direction, source, object mapping, controller ownership, equipment association, and validation status.

## Inputs
- Point lists.
- BACnet object lists.
- Modbus register maps.
- Controller schedules.

## Outputs
- Validated point records.
- Inputs for graphics, logic, checkout, trends, and alarms.

## Dependencies
- [Naming Conventions](../conventions/naming.md)
- [BACnet](../domain/bacnet.md)
- [Modbus](../domain/modbus.md)

## Design Reasoning
Points are the core contract between physical systems, controllers, graphics, logic, and reports. They must be explicit and traceable.

## Future Improvements
- Add canonical point type enum.
- Add units catalog.
- Add protocol mapping schema.

## Examples
```yaml
name: AHU-1 SAT
equipment_id: AHU-1
kind: sensor
units: degF
source: point_list
```

