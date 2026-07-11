"""BACnet exporter - EDE (Engineering Data Exchange) and CSV formats."""

import csv
from pathlib import Path
from typing import Optional
from datetime import datetime

from ..models import Project, Equipment, Point, Controller, PointKind, EquipmentType
from .base import BaseExporter, ExportResult, ExportContext


class BACnetExporter(BaseExporter):
    """Exports BAS project to BACnet EDE format and CSV."""

    vendor_name = "BACnet"
    file_extension = ".csv"

    def export(self, output_dir: Path, **kwargs) -> ExportResult:
        """Export to BACnet formats."""
        self._ensure_output_dir(output_dir)
        errors = []
        warnings = []
        files = []

        try:
            # 1. Export device list
            devices_file = self._export_devices(output_dir)
            files.append(devices_file)

            # 2. Export object list (all points)
            objects_file = self._export_objects(output_dir)
            files.append(objects_file)

            # 3. Export network addresses
            network_file = self._export_network(output_dir)
            files.append(network_file)

            # 4. Export EDE format (XML)
            ede_file = self._export_ede(output_dir)
            files.append(ede_file)

            # 5. Export CSV for tools
            csv_dir = output_dir / "csv"
            csv_dir.mkdir(exist_ok=True)
            self._export_csv(csv_dir)
            files.extend(csv_dir.glob("*.csv"))

        except Exception as e:
            errors.append(f"Export failed: {e}")

        return ExportResult(
            success=len(errors) == 0,
            message=f"BACnet export {'completed' if len(errors) == 0 else 'failed'}",
            files=files,
            errors=errors,
            warnings=warnings,
        )

    def _export_devices(self, output_dir: Path) -> Path:
        """Export BACnet device list."""
        path = output_dir / "devices.csv"

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Device Name", "Device Instance", "Vendor ID", "Vendor Name",
                "Model Name", "Firmware Revision", "Application Software Version",
                "Location", "Description", "Protocol Services Supported",
                "Protocol Object Types Supported", "Segmentation Supported",
                "Max APDU Length Accepted", "Max APDU Length",
                "Max Segments Accepted", "Local Time", "Local Date",
                "UTC Offset", "Daylight Savings Status", "APDU Timeout",
                "Number of APDU Retries", "Device Address Binding",
                "Database Revision", "Profile Name"
            ])

            for ctrl in self.project.controllers:
                # Get BACnet device instance
                device_instance = 0
                ip_address = ""
                for addr in ctrl.network_addresses:
                    if "BACnet" in addr.protocol.value:
                        if addr.network_number:
                            device_instance = addr.network_number
                        ip_address = addr.address

                writer.writerow([
                    ctrl.id,
                    device_instance,
                    999,  # Vendor ID (generic)
                    ctrl.vendor or "Generic",
                    ctrl.model or "",
                    ctrl.firmware_version or "1.0",
                    "1.0",
                    ctrl.panel_location or "",
                    ctrl.notes or "",
                    "subscribeCOV, readProperty, writeProperty, deviceCommunicationControl, reinitializeDevice",
                    "device, analogInput, analogOutput, analogValue, binaryInput, binaryOutput, binaryValue, multiStateInput, multiStateOutput, multiStateValue, schedule, calendar, trendLog, notificationClass",
                    "noSegmentation",
                    1476,
                    1476,
                    0,
                    "",
                    "",
                    0,
                    False,
                    3000,
                    3,
                    "",
                    1,
                    "",
                ])

        return path

    def _export_objects(self, output_dir: Path) -> Path:
        """Export BACnet object list (all points as objects)."""
        path = output_dir / "objects.csv"

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Object Name", "Object Type", "Object Instance", "Description",
                "Present Value", "Status Flags", "Event State", "Reliability",
                "Out of Service", "Units", "COV Increment", "Time Delay",
                "Notification Class", "High Limit", "Low Limit", "Deadband",
                "Limit Enable", "Event Enable", "Acked Transitions",
                "Notify Type", "Event Time Stamps", "Event Message Texts",
                "Profile Name"
            ])

            for point in self.project.points:
                ctrl = self.project.get_controller(point.controller_id) if point.controller_id else None
                device_instance = 0
                if ctrl:
                    for addr in ctrl.network_addresses:
                        if "BACnet" in addr.protocol.value and addr.network_number:
                            device_instance = addr.network_number

                # Map point kind to BACnet object type
                obj_type_map = {
                    PointKind.SENSOR: ("analogInput", "AI"),
                    PointKind.ACTUATOR: ("analogOutput", "AO"),
                    PointKind.SETPOINT: ("analogValue", "AV"),
                    PointKind.STATUS: ("binaryInput", "BI"),
                    PointKind.ALARM: ("notificationClass", "NC"),
                    PointKind.TREND: ("trendLog", "TL"),
                    PointKind.SCHEDULE: ("schedule", "SCH"),
                    PointKind.CALCULATED: ("analogValue", "AV"),
                    PointKind.PARAMETER: ("analogValue", "AV"),
                    PointKind.DERIVED: ("analogValue", "AV"),
                }
                obj_type, prefix = obj_type_map.get(point.kind, ("analogInput", "AI"))

                instance = point.bacnet_instance or (hash(point.name) % 4194303) + 1

                writer.writerow([
                    point.name,
                    obj_type,
                    instance,
                    point.description or "",
                    "",
                    "0",
                    "normal",
                    "noFaultDetected",
                    "false",
                    point.units or "",
                    "1.0" if point.kind == PointKind.SENSOR else "",
                    "0",
                    "0",
                    str(point.range_max or ""),
                    str(point.range_min or ""),
                    "1.0",
                    "true,true",
                    "true,true,true",
                    "true,true,true",
                    "event",
                    "",
                    "",
                    "",
                ])

        return path

    def _export_network(self, output_dir: Path) -> Path:
        """Export BACnet network configuration."""
        path = output_dir / "network.csv"

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Network Number", "Network Name", "Media", "Speed", "Description",
                "Router Address", "Router Port", "BBMD Address", "BBMD Port", "BBMD TTL"
            ])

            networks = set()
            for ctrl in self.project.controllers:
                for addr in ctrl.network_addresses:
                    if "BACnet" in addr.protocol.value and addr.network_number:
                        networks.add(addr.network_number)

            for net_num in networks:
                writer.writerow([
                    net_num,
                    f"Network_{net_num}",
                    "BACnet/IP",
                    "100000000",
                    f"BACnet network {net_num}",
                    "",
                    "47808",
                    "",
                    "47808",
                    "60000",
                ])

        return path

    def _export_ede(self, output_dir: Path) -> Path:
        """Export BACnet EDE (Engineering Data Exchange) XML format."""
        path = output_dir / "project.ede"

        # Simple EDE XML structure
        xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml.append('<EDE xmlns="http://www.bacnet.org/EDE/1.0">')
        xml.append(f'  <Project name="{self.project.metadata.name}" id="{self.project.metadata.project_id}">')
        xml.append(f'    <Client>{self.project.metadata.client or ""}</Client>')
        xml.append(f'    <Location>{self.project.metadata.location or ""}</Location>')
        xml.append(f'    <Created>{datetime.now().isoformat()}</Created>')

        # Devices
        xml.append('    <Devices>')
        for ctrl in self.project.controllers:
            xml.append(f'      <Device name="{ctrl.id}" instance="0" vendor="{ctrl.vendor or "Generic"}" model="{ctrl.model or ""}" firmware="{ctrl.firmware_version or "1.0"}"/>')
        xml.append('    </Devices>')

        # Objects
        xml.append('    <Objects>')
        for point in self.project.points:
            obj_type_map = {
                PointKind.SENSOR: "analogInput",
                PointKind.ACTUATOR: "analogOutput",
                PointKind.SETPOINT: "analogValue",
                PointKind.STATUS: "binaryInput",
                PointKind.ALARM: "notificationClass",
                PointKind.TREND: "trendLog",
                PointKind.SCHEDULE: "schedule",
                PointKind.CALCULATED: "analogValue",
                PointKind.PARAMETER: "analogValue",
                PointKind.DERIVED: "analogValue",
            }
            obj_type = obj_type_map.get(point.kind, "analogInput")
            instance = point.bacnet_instance or (hash(point.name) % 4194303) + 1

            xml.append(f'      <Object name="{point.name}" type="{obj_type}" instance="{instance}" units="{point.units or ""}" description="{point.description or ""}"/>')
        xml.append('    </Objects>')

        xml.append('  </Project>')
        xml.append('</EDE>')

        with open(path, "w") as f:
            f.write("\n".join(xml))

        return path

    def _export_csv(self, output_dir: Path) -> None:
        """Export simplified CSV files for common tools."""

        # Points CSV
        points_path = output_dir / "points.csv"
        with open(points_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Point Name", "Equipment", "Controller", "Object Type", "Instance",
                "Units", "Description", "Range Min", "Range Max",
                "BACnet Object Type", "BACnet Instance", "Modbus Register", "Modbus Type"
            ])
            for point in self.project.points:
                ctrl = self.project.get_controller(point.controller_id) if point.controller_id else None
                writer.writerow([
                    point.name,
                    point.equipment_id,
                    ctrl.id if ctrl else "",
                    point.kind.value,
                    "",
                    point.units or "",
                    point.description or "",
                    point.range_min or "",
                    point.range_max or "",
                    point.bacnet_object_type or "",
                    point.bacnet_instance or "",
                    point.modbus_register or "",
                    point.modbus_type or "",
                ])

        # Equipment CSV
        equip_path = output_dir / "equipment.csv"
        with open(equip_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Equipment ID", "Type", "Building", "Floor", "Room", "Served Area",
                "Controller", "Design CFM", "Design Tonnage", "Design GPM", "Status"
            ])
            for equip in self.project.equipment:
                writer.writerow([
                    equip.id,
                    equip.type.value,
                    equip.building or "",
                    equip.floor or "",
                    equip.room or "",
                    equip.served_area or "",
                    equip.controller_id or "",
                    equip.design_cfm or "",
                    equip.design_tonnage or "",
                    equip.design_gpm or "",
                    equip.status,
                ])

        # Controllers CSV
        ctrl_path = output_dir / "controllers.csv"
        with open(ctrl_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Controller ID", "Name", "Vendor", "Model", "Firmware", "Type",
                "Protocols", "Panel Location", "Status"
            ])
            for ctrl in self.project.controllers:
                writer.writerow([
                    ctrl.id,
                    ctrl.name or "",
                    ctrl.vendor or "",
                    ctrl.model or "",
                    ctrl.firmware_version or "",
                    ctrl.type,
                    ", ".join(p.value for p in ctrl.protocols),
                    ctrl.panel_location or "",
                    ctrl.status,
                ])


def export_bacnet(project: Project, output_dir: Path) -> ExportResult:
    """Convenience function to export to BACnet format."""
    exporter = BACnetExporter(project)
    return exporter.export(output_dir)


__all__ = ["BACnetExporter", "export_bacnet"]
