"""Siemens Desigo/Apogee exporter."""

import csv
import json
from pathlib import Path

from ..models import PointKind, Project
from .base import BaseExporter, ExportResult


class SiemensExporter(BaseExporter):
    """Exports BAS project to Siemens Desigo/Apogee format."""

    vendor_name = "Siemens"
    file_extension = ".csv"

    def export(self, output_dir: Path, **kwargs) -> ExportResult:
        """Export to Siemens format."""
        self._ensure_output_dir(output_dir)
        errors = []
        warnings = []
        files = []

        try:
            siemens_dir = output_dir / f"{self.project.metadata.project_id}_siemens"
            siemens_dir.mkdir(exist_ok=True)

            # 1. Export Desigo PX points
            points_file = self._export_points(siemens_dir)
            files.append(points_file)

            # 2. Export equipment
            equip_file = self._export_equipment(siemens_dir)
            files.append(equip_file)

            # 3. Export controllers (Automation Stations)
            stations_file = self._export_stations(siemens_dir)
            files.append(stations_file)

            # 4. Export graphics
            graphics_dir = self._export_graphics(siemens_dir)
            files.extend(graphics_dir)

            # 5. Export alarms
            alarms_file = self._export_alarms(siemens_dir)
            files.append(alarms_file)

            # 6. Export schedules
            schedules_file = self._export_schedules(siemens_dir)
            files.append(schedules_file)

            # 7. Export trends
            trends_file = self._export_trends(siemens_dir)
            files.append(trends_file)

        except Exception as e:
            errors.append(f"Export failed: {e}")

        return ExportResult(
            success=len(errors) == 0,
            message=f"Siemens export {'completed' if len(errors) == 0 else 'failed'}",
            files=files,
            errors=errors,
            warnings=warnings,
        )

    def _export_points(self, output_dir: Path) -> Path:
        """Export points in Siemens Desigo PX format (CSV)."""
        path = output_dir / "desigo_points.csv"

        # Siemens CSV format
        headers = [
            "PointName", "Description", "ObjectType", "Instance",
            "Units", "RangeMin", "RangeMax", "Equipment", "Station",
            "BACnetDeviceID", "ReadWrite", "COVIncrement", "Reliability",
            "AlarmHighLimit", "AlarmLowLimit", "AlarmDeadband",
            "TrendLog", "TrendInterval", "TrendRetention",
            "Source", "SourceReference", "ValidationStatus", "ProvenanceParser",
            "ProvenanceSourceDoc", "MappedController", "MappedEquipment", "SequenceReference",
        ]

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for point in self.project.points:
                effective_equipment_id = self.project.effective_point_equipment_id(point) or point.equipment_id
                effective_controller_id = self.project.effective_point_controller_id(point)
                ctrl = self.project.get_controller(effective_controller_id) if effective_controller_id else None
                equip = self.project.get_equipment(effective_equipment_id)

                # Siemens object types
                obj_type_map = {
                    PointKind.SENSOR: "AI",
                    PointKind.ACTUATOR: "AO",
                    PointKind.SETPOINT: "AV",
                    PointKind.STATUS: "BI",
                    PointKind.ALARM: "AV",
                    PointKind.TREND: "AI",
                    PointKind.SCHEDULE: "SC",
                    PointKind.CALCULATED: "AV",
                    PointKind.PARAMETER: "AV",
                    PointKind.DERIVED: "AV",
                }
                obj_type = obj_type_map.get(point.kind, "AI")

                instance = point.bacnet_instance or (hash(point.name) % 4194303) + 1

                row = [
                    point.name,
                    point.description or "",
                    obj_type,
                    instance,
                    point.units or "",
                    point.range_min or "",
                    point.range_max or "",
                    equip.id if equip else effective_equipment_id,
                    ctrl.id if ctrl else "",
                    ctrl.bacnet_device_instance if ctrl and hasattr(ctrl, 'bacnet_device_instance') else "",
                    "R" if point.direction.value == "input" else "W",
                    "",  # COV increment
                    "noFaultDetected",
                    point.range_max or "",
                    point.range_min or "",
                    "",  # deadband
                    "true" if point.kind == PointKind.TREND else "false",
                    "900" if point.kind == PointKind.TREND else "",  # 15 min
                    "2592000" if point.kind == PointKind.TREND else "",  # 30 days
                    point.source.value,
                    point.source_reference or "",
                    point.validation_status,
                    point.provenance.get("parser", ""),
                    point.provenance.get("source_doc_id", ""),
                    "yes" if (point.controller_id or "") != (effective_controller_id or "") else "no",
                    "yes" if point.equipment_id != effective_equipment_id else "no",
                    equip.sequence_ref if equip and equip.sequence_ref else "",
                ]
                writer.writerow(row)

        return path

    def _export_equipment(self, output_dir: Path) -> Path:
        """Export equipment definitions."""
        path = output_dir / "equipment.csv"

        headers = [
            "EquipmentID", "EquipmentType", "Description", "Building", "Floor", "Room",
            "ServedArea", "Station", "ParentEquipment", "DesignCFM", "DesignTonnage",
            "DesignGPM", "DesignKW", "Voltage", "Phase", "Status",
            "SequenceReference", "ProvenanceParser", "ProvenanceSourceDoc",
        ]

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for equip in self.project.equipment:
                effective_controller_id = self.project.effective_equipment_controller_id(equip)
                ctrl = self.project.get_controller(effective_controller_id) if effective_controller_id else None
                row = [
                    equip.id,
                    equip.type.value,
                    equip.served_area or "",
                    equip.building or "",
                    equip.floor or "",
                    equip.room or "",
                    equip.served_area or "",
                    ctrl.id if ctrl else "",
                    equip.parent_equipment_id or "",
                    equip.design_cfm or "",
                    equip.design_tonnage or "",
                    equip.design_gpm or "",
                    equip.design_kw or "",
                    equip.voltage or "",
                    equip.phase or "",
                    equip.status,
                    equip.sequence_ref or "",
                    equip.provenance.get("parser", ""),
                    equip.provenance.get("source_doc_id", ""),
                ]
                writer.writerow(row)

        return path

    def _export_stations(self, output_dir: Path) -> Path:
        """Export automation stations (controllers)."""
        path = output_dir / "stations.csv"

        headers = [
            "StationName", "StationType", "Vendor", "Model", "Firmware",
            "IPAddress", "BACnetDeviceID", "NetworkNumber", "Port",
            "Location", "Panel", "Circuit", "Status"
        ]

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for ctrl in self.project.controllers:
                ip = ""
                for addr in ctrl.network_addresses:
                    if "BACnet" in addr.protocol.value or "Modbus" in addr.protocol.value:
                        ip = addr.address
                        break

                bacnet_id = ""
                if hasattr(ctrl, 'bacnet_device_instance'):
                    bacnet_id = ctrl.bacnet_device_instance
                else:
                    bacnet_id = ctrl.network_addresses[0].network_number if ctrl.network_addresses else ""

                row = [
                    ctrl.id,
                    ctrl.type,
                    ctrl.vendor or "Siemens",
                    ctrl.model or "PXC",
                    ctrl.firmware_version or "",
                    ip,
                    bacnet_id,
                    ctrl.network_addresses[0].network_number if ctrl.network_addresses else "1",
                    "47808" if any("BACnet" in a.protocol.value for a in ctrl.network_addresses) else "502",
                    ctrl.panel_location or "",
                    ctrl.electrical_panel or "",
                    ctrl.circuit or "",
                    ctrl.status,
                ]
                writer.writerow(row)

        return path

    def _export_graphics(self, output_dir: Path) -> list[Path]:
        """Export Siemens PX graphics."""
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
                "width": 1024,
                "height": 768,
                "metadata": {
                    "equipmentId": equip.id,
                    "sequenceReference": equip.sequence_ref or "",
                    "provenanceParser": equip.provenance.get("parser", ""),
                },
                "objects": []
            }

            # Equipment object
            graphic["objects"].append({
                "type": "rect",
                "x": 50, "y": 50, "width": 200, "height": 150,
                "fill": "#e0e0e0", "stroke": "#333", "strokeWidth": 2,
            })
            graphic["objects"].append({
                "type": "text", "x": 150, "y": 125,
                "text": equip.id, "fontSize": 16, "fontFamily": "Arial",
            })

            # Point objects
            x, y = 300, 100
            for point in points:
                graphic["objects"].append({
                    "type": "point",
                    "point": point.name,
                    "label": point.name,
                    "x": x, "y": y,
                    "format": ".1f",
                    "source": point.source.value,
                    "sourceReference": point.source_reference or "",
                    "validationStatus": point.validation_status,
                    "provenanceParser": point.provenance.get("parser", ""),
                })
                y += 30
                if y > 700:
                    y = 100
                    x += 200

            path = graphics_dir / f"g_{equip.id}.json"
            with open(path, "w") as f:
                json.dump(graphic, f, indent=2)
            files.append(path)

        return files

    def _export_alarms(self, output_dir: Path) -> Path:
        """Export alarm configuration."""
        path = output_dir / "alarms.csv"

        headers = [
            "AlarmName", "PointName", "Description", "Priority",
            "HighLimit", "LowLimit", "Deadband", "Delay", "AckRequired"
        ]

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for point in self.project.points:
                if point.kind == PointKind.ALARM or point.range_min is not None or point.range_max is not None:
                    deadband = ""
                    if point.range_min is not None and point.range_max is not None:
                        deadband = (point.range_max - point.range_min) * 0.01

                    row = [
                        f"{point.name}_Alarm",
                        point.name,
                        point.description or "",
                        "3",  # Priority 3 (standard)
                        point.range_max or "",
                        point.range_min or "",
                        deadband,
                        "30",  # 30 second delay
                        "true",
                    ]
                    writer.writerow(row)

        return path

    def _export_schedules(self, output_dir: Path) -> Path:
        """Export schedule configuration."""
        path = output_dir / "schedules.csv"

        headers = [
            "ScheduleName", "Description", "Type",
            "MonStart", "MonEnd", "TueStart", "TueEnd", "WedStart", "WedEnd",
            "ThuStart", "ThuEnd", "FriStart", "FriEnd", "SatStart", "SatEnd",
            "SunStart", "SunEnd", "HolStart", "HolEnd"
        ]

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            # Default occupancy schedule
            row = [
                "Occupancy_Default",
                "Default occupancy schedule",
                "weekly",
                "07:00", "19:00",
                "07:00", "19:00",
                "07:00", "19:00",
                "07:00", "19:00",
                "07:00", "19:00",
                "08:00", "14:00",
                "", "",
                "", "",
            ]
            writer.writerow(row)

        return path

    def _export_trends(self, output_dir: Path) -> Path:
        """Export trend log configuration."""
        path = output_dir / "trends.csv"

        headers = [
            "TrendName", "PointName", "Description", "Interval",
            "Retention", "Enabled", "TriggerType", "StartTime", "EndTime"
        ]

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for point in self.project.points:
                if point.kind in (PointKind.SENSOR, PointKind.TREND, PointKind.SETPOINT):
                    row = [
                        f"{point.name}_Trend",
                        point.name,
                        point.description or "",
                        "900",  # 15 minutes
                        "2592000",  # 30 days
                        "true",
                        "interval",
                        "",
                        "",
                    ]
                    writer.writerow(row)

        return path


def export_siemens(project: Project, output_dir: Path) -> ExportResult:
    """Convenience function to export to Siemens format."""
    exporter = SiemensExporter(project)
    return exporter.export(output_dir)


__all__ = ["SiemensExporter", "export_siemens"]
