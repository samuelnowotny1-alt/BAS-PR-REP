"""JCI (Johnson Controls) Metasys exporter."""

import json
from pathlib import Path

from ..models import Controller, PointKind, Project
from .base import BaseExporter, ExportResult


class JCIExporter(BaseExporter):
    """Exports BAS project to JCI Metasys format (ADS/NAE)."""

    vendor_name = "JCI"
    file_extension = ".xml"

    def export(self, output_dir: Path, **kwargs) -> ExportResult:
        """Export to JCI Metasys format."""
        self._ensure_output_dir(output_dir)
        errors = []
        warnings = []
        files = []

        try:
            jci_dir = output_dir / f"{self.project.metadata.project_id}_jci"
            jci_dir.mkdir(exist_ok=True)

            # 1. Export NAE configuration
            nae_file = self._export_nae(jci_dir)
            files.append(nae_file)

            # 2. Export points database
            points_file = self._export_points(jci_dir)
            files.append(points_file)

            # 3. Export equipment
            equip_file = self._export_equipment(jci_dir)
            files.append(equip_file)

            # 4. Export graphics
            graphics_dir = self._export_graphics(jci_dir)
            files.extend(graphics_dir)

            # 5. Export alarms
            alarms_file = self._export_alarms(jci_dir)
            files.append(alarms_file)

            # 6. Export schedules
            schedules_file = self._export_schedules(jci_dir)
            files.append(schedules_file)

        except Exception as e:
            errors.append(f"Export failed: {e}")

        return ExportResult(
            success=len(errors) == 0,
            message=f"JCI export {'completed' if len(errors) == 0 else 'failed'}",
            files=files,
            errors=errors,
            warnings=warnings,
        )

    def _export_nae(self, output_dir: Path) -> Path:
        """Export NAE (Network Automation Engine) configuration."""
        path = output_dir / "nae_config.xml"

        xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml.append('<MetasysConfiguration xmlns="urn:jci:metasys:config:1.0">')
        xml.append(f'  <Site name="{self.project.metadata.name}" id="{self.project.metadata.project_id}">')
        xml.append(f'    <Client>{self.project.metadata.client or ""}</Client>')
        xml.append(f'    <Location>{self.project.metadata.location or ""}</Location>')

        # NAEs (Network Automation Engines) - one per controller
        xml.append('    <NAEs>')
        for ctrl in self.project.controllers:
            xml.append(f'      <NAE name="{ctrl.id}" ip="{self._get_ctrl_ip(ctrl)}" vendor="{ctrl.vendor or "JCI"}" model="{ctrl.model or "NAE55"}"/>')
        xml.append('    </NAEs>')

        # Networks
        xml.append('    <Networks>')
        for ctrl in self.project.controllers:
            for addr in ctrl.network_addresses:
                if "BACnet" in addr.protocol.value:
                    xml.append(f'      <Network number="{addr.network_number or 1}" name="BACnet Network {addr.network_number or 1}" type="BACnetIP"/>')
                    break
        xml.append('    </Networks>')

        xml.append('  </Site>')
        xml.append('</MetasysConfiguration>')

        with open(path, "w") as f:
            f.write("\n".join(xml))
        return path

    def _get_ctrl_ip(self, ctrl: Controller) -> str:
        for addr in ctrl.network_addresses:
            if "BACnet" in addr.protocol.value or "Modbus" in addr.protocol.value:
                return addr.address
        return "192.168.1.100"

    def _export_points(self, output_dir: Path) -> Path:
        """Export points database."""
        path = output_dir / "points.xml"

        xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml.append('<PointsDatabase xmlns="urn:jci:metasys:points:1.0">')

        for point in self.project.points:
            ctrl = self.project.get_controller(point.controller_id) if point.controller_id else None
            equip = self.project.get_equipment(point.equipment_id)

            # JCI object types
            jci_type_map = {
                PointKind.SENSOR: "AI",
                PointKind.ACTUATOR: "AO",
                PointKind.SETPOINT: "AV",
                PointKind.STATUS: "BI",
                PointKind.ALARM: "AV",  # Alarm values
                PointKind.TREND: "AI",
                PointKind.SCHEDULE: "SCH",
                PointKind.CALCULATED: "AV",
                PointKind.PARAMETER: "AV",
                PointKind.DERIVED: "AV",
            }
            jci_type = jci_type_map.get(point.kind, "AI")

            instance = point.bacnet_instance or (hash(point.name) % 4194303) + 1

            xml.append(f'  <Point name="{point.name}" type="{jci_type}" instance="{instance}">')
            xml.append(f'    <Description>{point.description or ""}</Description>')
            xml.append(f'    <Equipment>{equip.id if equip else point.equipment_id}</Equipment>')
            xml.append(f'    <Controller>{ctrl.id if ctrl else ""}</Controller>')
            xml.append(f'    <Units>{point.units or ""}</Units>')
            xml.append(f'    <Range min="{point.range_min or ""}" max="{point.range_max or ""}"/>')

            # BACnet config
            if point.bacnet_object_type:
                xml.append(f'    <BACnet objectType="{point.bacnet_object_type}" instance="{point.bacnet_instance}"/>')

            # Modbus config
            if point.modbus_register:
                xml.append(f'    <Modbus register="{point.modbus_register}" type="{point.modbus_type or "holding_register"}"/>')

            xml.append('  </Point>')

        xml.append('</PointsDatabase>')

        with open(path, "w") as f:
            f.write("\n".join(xml))
        return path

    def _export_equipment(self, output_dir: Path) -> Path:
        """Export equipment definitions."""
        path = output_dir / "equipment.xml"

        xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml.append('<EquipmentDatabase xmlns="urn:jci:metasys:equipment:1.0">')

        for equip in self.project.equipment:
            ctrl = self.project.get_controller(equip.controller_id) if equip.controller_id else None
            xml.append(f'  <Equipment id="{equip.id}" type="{equip.type.value}">')
            xml.append(f'    <Description>{equip.served_area or ""}</Description>')
            xml.append(f'    <Location building="{equip.building or ""}" floor="{equip.floor or ""}" room="{equip.room or ""}"/>')
            xml.append(f'    <Controller>{ctrl.id if ctrl else ""}</Controller>')
            xml.append(f'    <Design cfm="{equip.design_cfm or ""}" tonnage="{equip.design_tonnage or ""}" gpm="{equip.design_gpm or ""}" kw="{equip.design_kw or ""}"/>')
            xml.append(f'    <Electrical voltage="{equip.voltage or ""}" phase="{equip.phase or ""}"/>')
            xml.append(f'    <Status>{equip.status}</Status>')

            # Child equipment
            if equip.child_equipment_ids:
                xml.append('    <Children>')
                for child_id in equip.child_equipment_ids:
                    xml.append(f'      <Child ref="{child_id}"/>')
                xml.append('    </Children>')

            xml.append('  </Equipment>')

        xml.append('</EquipmentDatabase>')

        with open(path, "w") as f:
            f.write("\n".join(xml))
        return path

    def _export_graphics(self, output_dir: Path) -> list[Path]:
        """Export JCI graphics (UI pages)."""
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
                "type": "metasys",
                "width": 1024,
                "height": 768,
                "objects": []
            }

            # Equipment object
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
        path = output_dir / "alarms.xml"

        xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml.append('<AlarmConfiguration xmlns="urn:jci:metasys:alarms:1.0">')

        for point in self.project.points:
            if point.kind == PointKind.ALARM or point.range_min is not None or point.range_max is not None:
                xml.append(f'  <Alarm point="{point.name}" name="{point.name}_Alarm">')
                xml.append(f'    <Description>{point.description or ""}</Description>')
                xml.append('    <Priority>3</Priority>')
                xml.append('    <AckRequired>true</AckRequired>')

                if point.range_min is not None:
                    xml.append(f'    <LowLimit value="{point.range_min}"/>')
                if point.range_max is not None:
                    xml.append(f'    <HighLimit value="{point.range_max}"/>')
                if point.range_min is not None and point.range_max is not None:
                    deadband = (point.range_max - point.range_min) * 0.01
                    xml.append(f'    <Deadband value="{deadband}"/>')

                xml.append('  </Alarm>')

        xml.append('</AlarmConfiguration>')

        with open(path, "w") as f:
            f.write("\n".join(xml))
        return path

    def _export_schedules(self, output_dir: Path) -> Path:
        """Export schedule configuration."""
        path = output_dir / "schedules.xml"

        xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml.append('<Schedules xmlns="urn:jci:metasys:schedules:1.0">')

        # Default occupancy schedule
        xml.append('  <Schedule name="Occupancy_Default" type="weekly">')
        xml.append('    <Description>Default occupancy schedule</Description>')
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for i, day in enumerate(days):
            if i < 5:
                xml.append(f'    <Day name="{day}" occupied="07:00" unoccupied="19:00"/>')
            elif i == 5:
                xml.append(f'    <Day name="{day}" occupied="08:00" unoccupied="14:00"/>')
            else:
                xml.append(f'    <Day name="{day}" occupied="" unoccupied=""/>')
        xml.append('  </Schedule>')

        xml.append('</Schedules>')

        with open(path, "w") as f:
            f.write("\n".join(xml))
        return path


def export_jci(project: Project, output_dir: Path) -> ExportResult:
    """Convenience function to export to JCI format."""
    exporter = JCIExporter(project)
    return exporter.export(output_dir)


__all__ = ["JCIExporter", "export_jci"]
