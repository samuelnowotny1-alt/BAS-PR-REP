"""Honeywell EBI/Excel 5000 exporter."""

import csv
import json
from pathlib import Path

from ..models import PointKind, Project
from .base import BaseExporter, ExportResult


class HoneywellExporter(BaseExporter):
    """Exports BAS project to Honeywell EBI/Excel 5000 format."""

    vendor_name = "Honeywell"
    file_extension = ".csv"

    def export(self, output_dir: Path, **kwargs) -> ExportResult:
        """Export to Honeywell format."""
        self._ensure_output_dir(output_dir)
        errors = []
        warnings = []
        files = []

        try:
            hw_dir = output_dir / f"{self.project.metadata.project_id}_honeywell"
            hw_dir.mkdir(exist_ok=True)

            # 1. Export points (Honeywell Point Database)
            points_file = self._export_points(hw_dir)
            files.append(points_file)

            # 2. Export equipment
            equip_file = self._export_equipment(hw_dir)
            files.append(equip_file)

            # 3. Export controllers (Excel 5000 PMs / EBI Controllers)
            controllers_file = self._export_controllers(hw_dir)
            files.append(controllers_file)

            # 4. Export graphics
            graphics_dir = self._export_graphics(hw_dir)
            files.extend(graphics_dir)

            # 5. Export alarms
            alarms_file = self._export_alarms(hw_dir)
            files.append(alarms_file)

            # 6. Export schedules
            schedules_file = self._export_schedules(hw_dir)
            files.append(schedules_file)

            # 6. Export trends
            trends_file = self._export_trends(hw_dir)
            files.append(trends_file)

        except Exception as e:
            errors.append(f"Export failed: {e}")

        return ExportResult(
            success=len(errors) == 0,
            message=f"Honeywell export {'completed' if len(errors) == 0 else 'failed'}",
            files=files,
            errors=errors,
            warnings=warnings,
        )

    def _export_points(self, output_dir: Path) -> Path:
        """Export Honeywell point database (EBI format)."""
        path = output_dir / "points.csv"

        # Honeywell EBI point database format
        headers = [
            "Point Name", "Full Reference", "Description", "Object Type",
            "Instance", "Units", "Equipment", "Controller", "Address",
            "Range Low", "Range High", "Default Value", "Writable",
            "Alarm High", "Alarm Low", "Alarm Deadband", "Alarm Delay",
            "Trend Enable", "Trend Interval", "Trend Retention",
            "COV Increment", "Scan Rate", "Reliability"
        ]

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for point in self.project.points:
                ctrl = self.project.get_controller(point.controller_id) if point.controller_id else None
                equip = self.project.get_equipment(point.equipment_id)

                # Honeywell object types
                obj_type_map = {
                    PointKind.SENSOR: "AI",
                    PointKind.ACTUATOR: "AO",
                    PointKind.SETPOINT: "AV",
                    PointKind.STATUS: "BI",
                    PointKind.ALARM: "AV",
                    PointKind.TREND: "AI",
                    PointKind.SCHEDULE: "SCH",
                    PointKind.CALCULATED: "AV",
                    PointKind.PARAMETER: "AV",
                    PointKind.DERIVED: "AV",
                }
                obj_type = obj_type_map.get(point.kind, "AI")

                instance = point.bacnet_instance or (hash(point.name) % 4194303) + 1
                address = f"{obj_type}{instance}"

                row = [
                    point.name,
                    f"{ctrl.id}.{point.name}" if ctrl else point.name,
                    point.description or "",
                    obj_type,
                    instance,
                    point.units or "",
                    equip.id if equip else point.equipment_id,
                    ctrl.id if ctrl else "",
                    address,
                    point.range_min or "",
                    point.range_max or "",
                    "",
                    "Yes" if point.direction.value in ("output", "bidirectional") else "No",
                    point.range_max or "",
                    point.range_min or "",
                    "",  # deadband
                    "30",  # delay
                    "Yes" if point.kind == PointKind.TREND else "No",
                    "900" if point.kind == PointKind.TREND else "",  # 15 min
                    "2592000" if point.kind == PointKind.TREND else "",  # 30 days
                    "1.0",  # COV increment
                    "5",  # scan rate (seconds)
                    "No Fault",
                ]
                writer.writerow(row)

        return path

    def _export_equipment(self, output_dir: Path) -> Path:
        """Export equipment definitions."""
        path = output_dir / "equipment.csv"

        headers = [
            "Equipment Name", "Equipment Type", "Description", "Area",
            "Building", "Floor", "Room", "Controller", "Parent Equipment",
            "Design CFM", "Design Tonnage", "Design GPM", "Design KW",
            "Voltage", "Phase", "Status"
        ]

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for equip in self.project.equipment:
                ctrl = self.project.get_controller(equip.controller_id) if equip.controller_id else None
                row = [
                    equip.id,
                    equip.type.value,
                    equip.served_area or "",
                    equip.served_area or "",
                    equip.building or "",
                    equip.floor or "",
                    equip.room or "",
                    ctrl.id if ctrl else "",
                    equip.parent_equipment_id or "",
                    equip.design_cfm or "",
                    equip.design_tonnage or "",
                    equip.design_gpm or "",
                    equip.design_kw or "",
                    equip.voltage or "",
                    equip.phase or "",
                    equip.status,
                ]
                writer.writerow(row)

        return path

    def _export_controllers(self, output_dir: Path) -> Path:
        """Export Honeywell controllers (PMs/EMs)."""
        path = output_dir / "controllers.csv"

        headers = [
            "Controller Name", "Controller Type", "Description", "IP Address",
            "Model", "Firmware", "Network", "Node ID", "Device ID",
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

                device_id = ""
                if hasattr(ctrl, 'bacnet_device_instance'):
                    device_id = ctrl.bacnet_device_instance
                else:
                    device_id = ctrl.network_addresses[0].network_number if ctrl.network_addresses else ""

                row = [
                    ctrl.id,
                    ctrl.type,
                    ctrl.name or "",
                    ip,
                    ctrl.model or "EBI Controller",
                    ctrl.firmware_version or "",
                    "BACnet/IP" if any("BACnet" in a.protocol.value for a in ctrl.network_addresses) else "Modbus/TCP",
                    "",  # Node ID
                    device_id,
                    ctrl.panel_location or "",
                    ctrl.electrical_panel or "",
                    ctrl.circuit or "",
                    ctrl.status,
                ]
                writer.writerow(row)

        return path

    def _export_graphics(self, output_dir: Path) -> list[Path]:
        """Export Honeywell EBI graphics."""
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
                "type": "ebi",
                "width": 1024,
                "height": 768,
                "objects": []
            }

            # Equipment symbol
            graphic["objects"].append({
                "type": "equipment",
                "id": equip.id,
                "x": 50, "y": 50, "width": 200, "height": 150,
                "label": equip.id,
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
                    "editable": point.direction.value in ("output", "bidirectional"),
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
        """Export Honeywell alarm configuration."""
        path = output_dir / "alarms.csv"

        headers = [
            "Alarm Name", "Point Name", "Description", "Priority",
            "High Limit", "Low Limit", "Deadband", "Delay", "Ack Required",
            "Message", "Return to Normal"
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
                        "3",  # Priority
                        point.range_max or "",
                        point.range_min or "",
                        deadband,
                        "30",  # 30 seconds
                        "Yes",
                        f"{point.name} alarm",
                        "Yes",
                    ]
                    writer.writerow(row)

        return path

    def _export_schedules(self, output_dir: Path) -> Path:
        """Export Honeywell schedules."""
        path = output_dir / "schedules.csv"

        headers = [
            "Schedule Name", "Description", "Type",
            "Mon On", "Mon Off", "Tue On", "Tue Off", "Wed On", "Wed Off",
            "Thu On", "Thu Off", "Fri On", "Fri Off", "Sat On", "Sat Off",
            "Sun On", "Sun Off", "Hol On", "Hol Off"
        ]

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            row = [
                "Occupancy_Default",
                "Default occupancy schedule",
                "Weekly",
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
        """Export Honeywell trend logs."""
        path = output_dir / "trends.csv"

        headers = [
            "Trend Name", "Point Name", "Description", "Interval",
            "Retention", "Enabled", "Storage Type", "Compression"
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
                        "Yes",
                        "Database",
                        "None",
                    ]
                    writer.writerow(row)

        return path


def export_honeywell(project: Project, output_dir: Path) -> ExportResult:
    """Convenience function to export to Honeywell format."""
    exporter = HoneywellExporter(project)
    return exporter.export(output_dir)


__all__ = ["HoneywellExporter", "export_honeywell"]
