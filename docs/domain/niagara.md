# Niagara

## Purpose
Document Niagara-related assumptions and integration guidance.

## Scope
Includes station organization, components, points, graphics, histories, alarms, and future export strategy.

## Inputs
- Niagara station standards.
- Vendor conventions.
- Project point lists.
- Graphic and logic requirements.

## Outputs
- Niagara mapping guidance.
- Export constraints.
- Review notes.

## Dependencies
- [Graphics Conventions](../conventions/graphics.md)
- [Logic Conventions](../conventions/logic.md)
- [BACnet](bacnet.md)

## Design Reasoning
Niagara is often both a supervisory platform and an engineering environment. The assistant should produce structured artifacts that can be reviewed before any station import.

## Standards
- Keep station paths explicit.
- Do not overwrite station components without confirmation.
- Separate generated suggestions from approved station changes.
- Preserve project naming conventions.

## Current Export Contract
- Use the JSON station model as the canonical intermediate representation.
- Emit parallel review artifacts for every Niagara export:
  `*.json` for inspection and `*.wxf` / `*.px` for Niagara-shaped XML.
- Use explicit ORD and slot path generation for all exported objects.
- Keep PX pages navigable from a generated dashboard and from equipment navigation nodes.
- Keep point bindings anchored to generated driver paths under `/Drivers/BacnetNetwork/...`.

## Current XML Shape
- `station.wxf`
  contains station metadata and explicit root `slot` entries.
- `navigation.wxf`
  contains recursive `navNode` entries with `pxPageRef` links.
- `points.wxf`
  contains `point` nodes with explicit `proxyExt`, `pointBinding`, and `range`.
- `devices.wxf`
  contains `device` nodes with explicit `networkExt` and `pointRef` children.
- `alarms.wxf`
  contains `alarmExt` nodes with explicit `limits`.
- `schedules.wxf`
  contains `schedule` nodes with explicit `entries/day/occupied` and `unoccupied`.
- `trends.wxf`
  contains `historyExt` nodes with explicit `historyConfig`.
- `graphics/*.px`
  contains `pxPage`, `canvas`, `component`, and `binding` structures.

## Known Gaps
- The XML output is Niagara-shaped, but not yet validated against a real Workbench export.
- Tag names and attributes are chosen for internal consistency, not confirmed import compatibility.
- Module/service metadata is simplified and may not match real Niagara station requirements.
- PX components are structurally explicit, but still omit Niagara-specific widget classes and property bags.
- No named-tunnel or authenticated deployment flow is part of the export process.

## Next Validation Target
- Obtain one real Niagara reference export containing:
  station structure, navigation, at least one PX page, one numeric point, one alarm, one history.
- Build a diff checklist against that reference for:
  root tags, required attributes, slot naming, facet encoding, PX binding encoding, and service metadata.
- Update the XML serializer to close only high-value gaps first:
  import blockers, missing required metadata, and obvious schema mismatches.

## Future Improvements
- Add a real reference fixture from Niagara Workbench output.
- Add station path conventions.
- Add component template library.
- Add explicit compatibility tiers:
  review-only, structured-like-Niagara, import-targeted.

## Examples
- A generated AHU graphic binding list should be reviewable before being applied to a Niagara station.
