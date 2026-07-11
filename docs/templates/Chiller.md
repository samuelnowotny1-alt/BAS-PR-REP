# Chiller Template

## Purpose
Provide a starting template for chiller documentation and generation.

## Scope
Applies to chiller graphics, logic, checkout, alarms, trends, and reports.

## Inputs
- Chiller equipment record.
- Chiller point list.
- Chilled water plant sequence.
- Integration documentation.

## Outputs
- Chiller-specific requirements and generated artifacts.

## Dependencies
- [Equipment](../domain/equipment.md)
- [Modbus](../domain/modbus.md)
- [BACnet](../domain/bacnet.md)

## Design Reasoning
Chillers are often vendor-controlled and integrated through BACnet or Modbus. The assistant must respect vendor object/register documentation and approved plant sequences.

## Future Improvements
- Add chiller enable and isolation valve patterns.
- Add plant staging templates.
- Add integration point profiles.

## Examples
- Do not infer chiller run status from enable command unless the integration documentation confirms that behavior.

