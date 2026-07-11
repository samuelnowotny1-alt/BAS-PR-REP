# BAS Fundamentals

## Purpose
Provide baseline BAS concepts for contributors and AI agents.

## Scope
Includes equipment control, points, controllers, networks, graphics, alarms, trends, sequences, and commissioning.

## Inputs
- BAS engineering practices.
- Project specifications.
- Vendor documentation.

## Outputs
- Shared vocabulary.
- Domain assumptions.
- Links to specialized domain documents.

## Dependencies
- [Equipment](equipment.md)
- [Controllers](controllers.md)
- [BACnet](bacnet.md)
- [Sequences](sequences.md)

## Design Reasoning
The assistant must understand BAS work as an engineering workflow, not merely a text-generation task.

## Concepts
- Equipment performs physical HVAC or plant functions.
- Points represent commands, statuses, sensor values, setpoints, alarms, and calculated values.
- Controllers execute logic and expose points.
- Networks carry data between controllers, supervisory systems, and integrations.
- Sequences define expected operation.
- Commissioning verifies installed behavior.

## Future Improvements
- Add glossary.
- Add diagrams for common BAS topologies.
- Add references to accepted standards.

## Examples
- A supply fan command is not the same as a supply fan status.
- A trend confirms historical behavior but does not replace functional testing.

