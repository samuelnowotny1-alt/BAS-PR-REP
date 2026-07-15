"""Tridium exporter - Fox protocol and station export."""

import json
from datetime import datetime
from pathlib import Path

from ..models import PointKind, Project
from .base import BaseExporter, ExportResult


class TridiumExporter(BaseExporter):
    """Exports BAS project to Tridium Fox format."""

    vendor_name = "Tridium"
    file_extension = ".fox"

    def export(self, output_dir: Path, **kwargs) -> ExportResult:
        """Export to Tridium Fox format."""
        self._ensure_output_dir(output_dir)
        errors = []
        warnings = []
        files = []

        try:
            # Export as Fox-compatible JSON structure
            fox_dir = output_dir / f"{self.project.metadata.project_id}_fox"
            fox_dir.mkdir(exist_ok=True)

            # 1. Station configuration
            station_file = self._export_station(fox_dir)
            files.append(station_file)

            # 2. Components (points, equipment, etc.)
            components_file = self._export_components(fox_dir)
            files.append(components_file)

            # 3. Links/connections
            links_file = self._export_links(fox_dir)
            files.append(links_file)

            # 4. Graphics (PX pages)
            graphics_dir = self._export_graphics(fox_dir)
            files.extend(graphics_dir)

            # 5. Create .bog archive
            bog_path = output_dir / f"{self.project.metadata.project_id}.bog"
            self._create_bog(fox_dir, bog_path)
            files.append(bog_path)

        except Exception as e:
            errors.append(f"Export failed: {e}")

        return ExportResult(
            success=len(errors) == 0,
            message=f"Tridium export {'completed' if len(errors) == 0 else 'failed'}",
            files=files,
            errors=errors,
            warnings=warnings,
        )

    def _export_station(self, output_dir: Path) -> Path:
        """Export station.json - root station configuration."""
        approved_outputs = any(
            approval.approval_key == "outputs-ready" and approval.status == "approved"
            for approval in self.project.review_state.approvals
        )
        station = {
            "station": {
                "name": self.project.metadata.name,
                "id": self.project.metadata.project_id,
                "version": "4.12",
                "vendor": "Tridium",
                "description": self.project.metadata.client or "",
                "timezone": self.project.metadata.timezone or "UTC",
                "created": datetime.now().isoformat(),
                "review": {
                    "validationStatus": self.project.validation_status,
                    "lastValidated": self.project.last_validated.isoformat() if self.project.last_validated else None,
                    "outputsApproved": approved_outputs,
                    "mappingDecisionCount": len(self.project.review_state.mapping_decisions),
                    "assumptionCount": len(self.project.review_state.assumptions),
                },
                "modules": [
                    "bacnet", "fox", "history", "alarm", "schedule", "px"
                ]
            }
        }

        path = output_dir / "station.json"
        with open(path, "w") as f:
            json.dump(station, f, indent=2)
        return path

    def _export_components(self, output_dir: Path) -> Path:
        """Export all components as Fox objects."""
        components = {"components": []}

        # Add controllers as devices
        for ctrl in self.project.controllers:
            comp = {
                "type": "device",
                "name": ctrl.id,
                "displayName": ctrl.name or ctrl.id,
                "vendor": ctrl.vendor or "Generic",
                "model": ctrl.model or "",
                "firmware": ctrl.firmware_version or "",
                "properties": {}
            }

            # Add protocol-specific properties
            for addr in ctrl.network_addresses:
                if "BACnet" in addr.protocol.value:
                    comp["properties"]["bacnetDeviceInstance"] = addr.network_number or 0
                    comp["properties"]["bacnetIp"] = addr.address
                elif "Modbus" in addr.protocol.value:
                    comp["properties"]["modbusIp"] = addr.address
                    comp["properties"]["modbusPort"] = 502

            components["components"].append(comp)

        # Add equipment
        for equip in self.project.equipment:
            comp = {
                "type": "equipment",
                "name": equip.id,
                "displayName": equip.id,
                "equipmentType": equip.type.value,
                "properties": {
                    "servedArea": equip.served_area or "",
                    "building": equip.building or "",
                    "floor": equip.floor or "",
                    "room": equip.room or "",
                    "sequenceReference": equip.sequence_ref or "",
                    "provenanceParser": equip.provenance.get("parser", ""),
                    "provenanceSourceDoc": equip.provenance.get("source_doc_id", ""),
                }
            }
            components["components"].append(comp)

        # Add points
        for point in self.project.points:
            effective_equipment_id = self.project.effective_point_equipment_id(point) or point.equipment_id
            effective_controller_id = self.project.effective_point_controller_id(point)
            ctrl = self.project.get_controller(effective_controller_id) if effective_controller_id else None
            equip = self.project.get_equipment(effective_equipment_id)

            point_type_map = {
                PointKind.SENSOR: "numericPoint",
                PointKind.ACTUATOR: "numericPoint",
                PointKind.SETPOINT: "numericPoint",
                PointKind.STATUS: "booleanPoint",
                PointKind.ALARM: "alarmPoint",
                PointKind.TREND: "numericPoint",
                PointKind.SCHEDULE: "schedulePoint",
                PointKind.CALCULATED: "numericPoint",
                PointKind.PARAMETER: "numericPoint",
                PointKind.DERIVED: "numericPoint",
            }
            fox_type = point_type_map.get(point.kind, "numericPoint")

            comp = {
                "type": fox_type,
                "name": point.name,
                "displayName": point.name,
                "equipment": effective_equipment_id,
                "controller": effective_controller_id or "",
                "properties": {
                    "units": point.units or "",
                    "description": point.description or "",
                    "source": point.source.value,
                    "sourceReference": point.source_reference or "",
                    "validationStatus": point.validation_status,
                    "provenanceParser": point.provenance.get("parser", ""),
                    "provenanceSourceDoc": point.provenance.get("source_doc_id", ""),
                    "mappedController": str((point.controller_id or "") != (effective_controller_id or "")).lower(),
                    "mappedEquipment": str(point.equipment_id != effective_equipment_id).lower(),
                }
            }

            if point.range_min is not None:
                comp["properties"]["rangeMin"] = point.range_min
            if point.range_max is not None:
                comp["properties"]["rangeMax"] = point.range_max

            # BACnet config
            if point.bacnet_object_type:
                comp["properties"]["bacnetObjectType"] = point.bacnet_object_type
                comp["properties"]["bacnetInstance"] = point.bacnet_instance

            # Modbus config
            if point.modbus_register:
                comp["properties"]["modbusRegister"] = point.modbus_register
                comp["properties"]["modbusType"] = point.modbus_type

            components["components"].append(comp)

        path = output_dir / "components.json"
        with open(path, "w") as f:
            json.dump(components, f, indent=2)
        return path

    def _export_links(self, output_dir: Path) -> Path:
        """Export links/connections between components."""
        links = {"links": []}

        # Point -> Controller links
        for point in self.project.points:
            effective_controller_id = self.project.effective_point_controller_id(point)
            if effective_controller_id:
                links["links"].append({
                    "source": effective_controller_id,
                    "target": point.name,
                    "type": "contains",
                })

        # Equipment -> Controller links
        for equip in self.project.equipment:
            effective_controller_id = self.project.effective_equipment_controller_id(equip)
            if effective_controller_id:
                links["links"].append({
                    "source": effective_controller_id,
                    "target": equip.id,
                    "type": "serves",
                })

        # Equipment hierarchy
        for equip in self.project.equipment:
            if equip.parent_equipment_id:
                links["links"].append({
                    "source": equip.parent_equipment_id,
                    "target": equip.id,
                    "type": "contains",
                })

        path = output_dir / "links.json"
        with open(path, "w") as f:
            json.dump(links, f, indent=2)
        return path

    def _export_graphics(self, output_dir: Path) -> list[Path]:
        """Export graphics as PX page definitions."""
        graphics_dir = output_dir / "graphics"
        graphics_dir.mkdir(exist_ok=True)
        files = []

        for equip in self.project.equipment:
            points = self.project.get_points_for_equipment(equip.id)
            if not points:
                continue

            graphic = {
                "name": f"g_{equip.id}",
                "title": equip.id,
                "type": "px",
                "width": 1200,
                "height": 800,
                "metadata": {
                    "equipmentId": equip.id,
                    "sequenceReference": equip.sequence_ref or "",
                    "provenanceParser": equip.provenance.get("parser", ""),
                },
                "components": []
            }

            # Equipment symbol
            graphic["components"].append({
                "type": "rect",
                "x": 100, "y": 100, "width": 300, "height": 200,
                "fill": "#e0e0e0", "stroke": "#333", "strokeWidth": 2,
            })
            graphic["components"].append({
                "type": "text", "x": 250, "y": 200,
                "text": equip.id, "fontSize": 18, "fontFamily": "Arial",
            })

            # Point bindings
            x_pos = 450
            y_pos = 150
            for point in points:
                graphic["components"].append({
                    "type": "binding",
                    "x": x_pos, "y": y_pos,
                    "point": point.name,
                    "label": point.name,
                    "format": ".1f",
                    "bindingType": "value" if point.kind == PointKind.SENSOR else "setpoint",
                    "source": point.source.value,
                    "sourceReference": point.source_reference or "",
                    "validationStatus": point.validation_status,
                })
                y_pos += 40
                if y_pos > 700:
                    y_pos = 150
                    x_pos += 250

            path = graphics_dir / f"g_{equip.id}.json"
            with open(path, "w") as f:
                json.dump(graphic, f, indent=2)
            files.append(path)

        return files

    def _create_bog(self, fox_dir: Path, bog_path: Path) -> None:
        """Create Tridium .bog archive."""
        import zipfile
        with zipfile.ZipFile(bog_path, 'w', zipfile.ZIP_DEFLATED) as bog:
            for file_path in fox_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(fox_dir)
                    bog.write(file_path, arcname)


def export_tridium(project: Project, output_dir: Path) -> ExportResult:
    """Convenience function to export to Tridium format."""
    exporter = TridiumExporter(project)
    return exporter.export(output_dir)


__all__ = ["TridiumExporter", "export_tridium"]
