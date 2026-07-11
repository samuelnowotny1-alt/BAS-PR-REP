"""Niagara Framework exporter - WXF (Workbench Export Format) and station archive."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Optional
from datetime import datetime
import uuid

from ..models import Project, Equipment, Point, Controller, PointKind, EquipmentType
from .base import BaseExporter, ExportResult, ExportContext


class NiagaraExporter(BaseExporter):
    """Exports BAS project to Niagara WXF format and station archive (.bog)."""

    vendor_name = "Niagara"
    file_extension = ".wxf"

    SYMBOLS = {
        "ahu": {"elements": [
            {"type": "rect", "x": 0.1, "y": 0.2, "width": 0.8, "height": 0.6, "fill": "#e0e0e0", "stroke": "#333"},
            {"type": "text", "x": 0.5, "y": 0.5, "text": "{name}", "font_size": 14},
        ]},
        "vav": {"elements": [
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#fff", "stroke": "#333"},
            {"type": "text", "x": 0.5, "y": 0.5, "text": "{name}", "font_size": 10},
        ]},
        "chiller": {"elements": [
            {"type": "ellipse", "x": 0.1, "y": 0.2, "width": 0.8, "height": 0.6, "fill": "#cce5ff", "stroke": "#333"},
            {"type": "text", "x": 0.5, "y": 0.5, "text": "{name}", "font_size": 14},
        ]},
        "boiler": {"elements": [
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#ffe0b2", "stroke": "#333"},
            {"type": "text", "x": 0.5, "y": 0.5, "text": "{name}", "font_size": 14},
        ]},
        "pump": {"elements": [
            {"type": "circle", "x": 0.1, "y": 0.1, "radius": 0.4, "fill": "#fff", "stroke": "#333"},
            {"type": "text", "x": 0.5, "y": 0.5, "text": "{name}", "font_size": 10},
        ]},
    }

    # Niagara slot types mapping
    POINT_KIND_TO_SLOT = {
        PointKind.SENSOR: "numericSensor",
        PointKind.ACTUATOR: "numericActuator",
        PointKind.SETPOINT: "numericSetpoint",
        PointKind.STATUS: "booleanSensor",
        PointKind.ALARM: "alarm",
        PointKind.TREND: "trend",
        PointKind.SCHEDULE: "schedule",
        PointKind.CALCULATED: "numericSensor",
        PointKind.PARAMETER: "numericSetpoint",
        PointKind.DERIVED: "numericSensor",
    }

    EQUIPMENT_TYPE_TO_NAV = {
        EquipmentType.AHU: "airHandlingUnit",
        EquipmentType.RTU: "rooftopUnit",
        EquipmentType.VAV: "vavBox",
        EquipmentType.CHILLER: "chiller",
        EquipmentType.BOILER: "boiler",
        EquipmentType.COOLING_TOWER: "coolingTower",
        EquipmentType.PUMP_HW: "pump",
        EquipmentType.PUMP_CHW: "pump",
        EquipmentType.PUMP_CW: "pump",
        EquipmentType.FAN_COIL: "fanCoilUnit",
    }

    def __init__(self, project: Project):
        super().__init__(project)
        self._uids = {}  # Map from model IDs to Niagara UIDs

    def _uid(self, prefix: str, key: str) -> str:
        """Generate deterministic UUID for an object."""
        if key not in self._uids:
            # Deterministic UUID based on prefix + key
            namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
            self._uids[key] = str(uuid.uuid5(namespace, f"{prefix}:{key}"))
        return self._uids[key]

    def export(self, output_dir: Path, **kwargs) -> ExportResult:
        """Export to Niagara WXF format."""
        self._ensure_output_dir(output_dir)
        errors = []
        warnings = []
        files = []

        try:
            # Generate WXF files
            wxf_dir = output_dir / f"{self.project.metadata.project_id}_wxf"
            wxf_dir.mkdir(exist_ok=True)

            # 1. Export stations
            station_file = self._export_station(wxf_dir)
            files.append(station_file)

            # 2. Export equipment navigation
            nav_file = self._export_navigation(wxf_dir)
            files.append(nav_file)

            # 3. Export points
            points_file = self._export_points(wxf_dir)
            files.append(points_file)

            # 4. Export controllers (devices)
            devices_file = self._export_devices(wxf_dir)
            files.append(devices_file)

            # 5. Export alarms
            alarms_file = self._export_alarms(wxf_dir)
            files.append(alarms_file)

            # 6. Export schedules
            schedules_file = self._export_schedules(wxf_dir)
            files.append(schedules_file)

            # 7. Export histories/trends
            trends_file = self._export_trends(wxf_dir)
            files.append(trends_file)

            # 8. Export graphics (PX pages)
            graphics_dir = self._export_graphics(wxf_dir)
            files.extend(graphics_dir)

            # Create station archive (.bog)
            bog_path = output_dir / f"{self.project.metadata.project_id}.bog"
            self._create_bog_archive(wxf_dir, bog_path)
            files.append(bog_path)

        except Exception as e:
            errors.append(f"Export failed: {e}")

        return ExportResult(
            success=len(errors) == 0,
            message=f"Niagara export {'completed' if len(errors) == 0 else 'failed'}",
            files=files,
            errors=errors,
            warnings=warnings,
        )

    def _export_station(self, output_dir: Path) -> Path:
        """Export station.json - root station configuration."""
        station = {
            "station": {
                "name": self.project.metadata.name,
                "id": self._uid("station", self.project.metadata.project_id),
                "description": self.project.metadata.client or "",
                "timezone": self.project.metadata.timezone or "UTC",
                "created": self.project.metadata.created_at.isoformat() if self.project.metadata.created_at else datetime.now().isoformat(),
                "modified": self.project.metadata.updated_at.isoformat() if self.project.metadata.updated_at else datetime.now().isoformat(),
                "version": "4.12",
                "vendor": "Tridium",
                "application": "BAS Assistant",
            }
        }

        path = output_dir / "station.json"
        with open(path, "w") as f:
            json.dump(station, f, indent=2)
        return path

    def _export_navigation(self, output_dir: Path) -> Path:
        """Export navigation tree (nav.json) - equipment hierarchy."""
        nav = {
            "navigation": {
                "name": "Navigation",
                "id": self._uid("nav", "root"),
                "children": []
            }
        }

        # Group equipment by building/floor
        buildings = {}
        for equip in self.project.equipment:
            bldg = equip.building or "Default Building"
            floor = equip.floor or "Default Floor"
            key = (bldg, floor)
            if key not in buildings:
                buildings[key] = {"building": bldg, "floor": floor, "equipment": []}
            buildings[key]["equipment"].append(equip)

        for (bldg, floor), data in buildings.items():
            bldg_id = self._uid("building", bldg)
            floor_id = self._uid("floor", f"{bldg}:{floor}")

            # Building folder
            building_node = {
                "name": data["building"],
                "id": bldg_id,
                "type": "folder",
                "children": []
            }

            # Floor folder
            floor_node = {
                "name": f"Floor {data['floor']}",
                "id": floor_id,
                "type": "folder",
                "children": []
            }

            # Equipment
            for equip in data["equipment"]:
                equip_id = self._uid("equip", equip.id)
                nav_type = self.EQUIPMENT_TYPE_TO_NAV.get(equip.type, "equipment")
                equip_node = {
                    "name": equip.id,
                    "id": equip_id,
                    "type": nav_type,
                    "displayName": equip.id,
                    "description": equip.served_area or "",
                    "children": []
                }

                # Add point children
                points = self.project.get_points_for_equipment(equip.id)
                for point in points:
                    point_id = self._uid("point", point.name)
                    point_node = {
                        "name": point.name,
                        "id": point_id,
                        "type": "point",
                        "pointType": point.kind.value,
                        "units": point.units or "",
                    }
                    equip_node["children"].append(point_node)

                floor_node["children"].append(equip_node)

            building_node["children"].append(floor_node)
            nav["navigation"]["children"].append(building_node)

        path = output_dir / "navigation.json"
        with open(path, "w") as f:
            json.dump(nav, f, indent=2)
        return path

    def _export_points(self, output_dir: Path) -> Path:
        """Export all points as Niagara numeric/boolean points."""
        points_data = {"points": []}

        for point in self.project.points:
            equip = self.project.get_equipment(point.equipment_id)
            ctrl = self.project.get_controller(point.controller_id) if point.controller_id else None

            slot_type = self.POINT_KIND_TO_SLOT.get(point.kind, "numericSensor")
            point_id = self._uid("point", point.name)

            point_data = {
                "name": point.name,
                "id": point_id,
                "type": slot_type,
                "description": point.description or "",
                "units": point.units or "",
                "equipment": equip.id if equip else "",
                "controller": ctrl.id if ctrl else "",
                "writable": point.direction.value in ("output", "bidirectional"),
            }

            # Add BACnet configuration
            if point.bacnet_object_type:
                point_data["bacnet"] = {
                    "objectType": point.bacnet_object_type,
                    "instance": point.bacnet_instance,
                    "deviceInstance": ctrl.bacnet_device_instance if ctrl and hasattr(ctrl, 'bacnet_device_instance') else 0,
                }

            # Add Modbus configuration
            if point.modbus_register:
                point_data["modbus"] = {
                    "register": point.modbus_register,
                    "type": point.modbus_type or "holding_register",
                    "slaveId": ctrl.modbus_slave_id if ctrl and hasattr(ctrl, 'modbus_slave_id') else 1,
                }

            # Range limits
            if point.range_min is not None or point.range_max is not None:
                point_data["range"] = {
                    "min": point.range_min,
                    "max": point.range_max,
                }

            points_data["points"].append(point_data)

        path = output_dir / "points.json"
        with open(path, "w") as f:
            json.dump(points_data, f, indent=2)
        return path

    def _export_devices(self, output_dir: Path) -> Path:
        """Export controllers as Niagara devices."""
        devices_data = {"devices": []}

        for ctrl in self.project.controllers:
            device_id = self._uid("device", ctrl.id)
            device_data = {
                "name": ctrl.id,
                "id": device_id,
                "type": "device",
                "vendor": ctrl.vendor or "Generic",
                "model": ctrl.model or "",
                "firmware": ctrl.firmware_version or "",
                "protocol": [p.value for p in ctrl.protocols],
                "points": [p for p in ctrl.owned_point_names],
            }

            # Network addresses
            for addr in ctrl.network_addresses:
                if addr.protocol.value == "BACnet/IP":
                    device_data["bacnet"] = {
                        "ip": addr.address,
                        "port": 47808,
                        "deviceInstance": addr.network_number or 0,
                    }
                elif addr.protocol.value == "Modbus/TCP":
                    device_data["modbus"] = {
                        "ip": addr.address,
                        "port": 502,
                        "slaveId": 1,
                    }

            devices_data["devices"].append(device_data)

        path = output_dir / "devices.json"
        with open(path, "w") as f:
            json.dump(devices_data, f, indent=2)
        return path

    def _export_alarms(self, output_dir: Path) -> Path:
        """Export alarm configuration."""
        alarms_data = {"alarms": []}

        # Generate alarms from points with alarm kind or ranges
        for point in self.project.points:
            if point.kind == PointKind.ALARM or point.range_min is not None or point.range_max is not None:
                alarm_id = self._uid("alarm", f"{point.name}_alm")
                alarm_data = {
                    "name": f"{point.name}_Alarm",
                    "id": alarm_id,
                    "point": point.name,
                    "type": "limit",
                    "priority": 3,
                    "ackRequired": True,
                }

                if point.range_min is not None:
                    alarm_data["lowLimit"] = point.range_min
                if point.range_max is not None:
                    alarm_data["highLimit"] = point.range_max
                if point.range_min is not None and point.range_max is not None:
                    alarm_data["deadband"] = (point.range_max - point.range_min) * 0.01

                alarms_data["alarms"].append(alarm_data)

        path = output_dir / "alarms.json"
        with open(path, "w") as f:
            json.dump(alarms_data, f, indent=2)
        return path

    def _export_schedules(self, output_dir: Path) -> Path:
        """Export schedule configuration."""
        schedules_data = {"schedules": []}

        # Create default occupancy schedule
        schedule_id = self._uid("schedule", "occupancy_default")
        schedule_data = {
            "name": "Occupancy_Default",
            "id": schedule_id,
            "type": "schedule",
            "description": "Default occupancy schedule",
            "schedule": {
                "monday": {"occupied": "07:00", "unoccupied": "19:00"},
                "tuesday": {"occupied": "07:00", "unoccupied": "19:00"},
                "wednesday": {"occupied": "07:00", "unoccupied": "19:00"},
                "thursday": {"occupied": "07:00", "unoccupied": "19:00"},
                "friday": {"occupied": "07:00", "unoccupied": "19:00"},
                "saturday": {"occupied": "08:00", "unoccupied": "14:00"},
                "sunday": {"occupied": "", "unoccupied": ""},
                "holiday": {"occupied": "", "unoccupied": ""},
            },
        }
        schedules_data["schedules"].append(schedule_data)

        path = output_dir / "schedules.json"
        with open(path, "w") as f:
            json.dump(schedules_data, f, indent=2)
        return path

    def _export_trends(self, output_dir: Path) -> Path:
        """Export trend log configuration."""
        trends_data = {"trends": []}

        for point in self.project.points:
            if point.kind in (PointKind.SENSOR, PointKind.TREND):
                trend_id = self._uid("trend", f"{point.name}_trend")
                trend_data = {
                    "name": f"{point.name}_Trend",
                    "id": trend_id,
                    "point": point.name,
                    "interval": "15m",
                    "retention": "30d",
                    "enabled": True,
                    "type": "interval",
                }
                trends_data["trends"].append(trend_data)

        path = output_dir / "trends.json"
        with open(path, "w") as f:
            json.dump(trends_data, f, indent=2)
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

            graphic_id = self._uid("graphic", f"g_{equip.id}")
            graphic = {
                "name": f"g_{equip.id}",
                "id": graphic_id,
                "type": "px",
                "equipment": equip.id,
                "title": equip.id,
                "width": 1200,
                "height": 800,
                "components": [],
                "bindings": [],
                "navigation": [
                    f"g_{equip.id}",
                    "dashboard_main",
                ],
                "metadata": {"equipment_type": equip.type.value, "generated_by": "BAS Assistant"},
            }

            # Use template or generic
            symbol_key = equip.type.value.lower()
            if symbol_key in self.SYMBOLS:
                self._apply_symbol_template(graphic, equip, symbol_key)
            else:
                self._apply_generic_template(graphic, equip, points)

            # Add standard navigation
            graphic["navigation"].extend([
                f"g_{equip.id}",
                "dashboard_main",
            ])

            path = graphics_dir / f"{graphic_id}.json"
            with open(path, "w") as f:
                json.dump(graphic, f, indent=2)
            files.append(path)

        return files

    def _apply_symbol_template(self, graphic: dict, equip: Equipment, symbol_key: str) -> None:
        """Apply a symbol template to the graphic."""
        template = self.SYMBOLS[symbol_key]

        # Add symbol elements
        for elem_data in template["elements"]:
            elem = self._create_element_from_template(elem_data, equip.id)
            graphic["components"].append(elem)

        # Add point bindings around the symbol
        self._add_point_bindings(graphic, equip)

    def _apply_generic_template(self, graphic: dict, equip: Equipment, points: list) -> None:
        """Apply generic equipment template."""
        # Equipment box
        graphic["components"].append({
            "type": "rect", "x": 0.1, "y": 0.2, "width": 0.8, "height": 0.6,
            "fill": "#e0e0e0", "stroke": "#333", "strokeWidth": 2, "layer": "equipment",
        })
        # Equipment name
        graphic["components"].append({
            "type": "text", "x": 0.5, "y": 0.5, "text": equip.id,
            "fontSize": 16, "fontFamily": "Arial", "layer": "labels",
        })
        # Type label
        graphic["components"].append({
            "type": "text", "x": 0.5, "y": 0.7, "text": equip.type.value,
            "fontSize": 12, "fontFamily": "Arial", "layer": "labels",
        })

        self._add_point_bindings(graphic, equip)

    def _create_element_from_template(self, elem_data: dict, equip_id: str) -> dict:
        """Create a GraphicElement from template data."""
        elem_type = elem_data["type"]

        if elem_type == "rect":
            return {
                "type": "rect",
                "x": elem_data["x"], "y": elem_data["y"],
                "width": elem_data["width"], "height": elem_data["height"],
                "fill": elem_data.get("fill"), "stroke": elem_data.get("stroke"),
                "strokeWidth": elem_data.get("stroke_width", 1),
                "layer": "symbol",
            }
        elif elem_type == "circle":
            return {
                "type": "circle",
                "x": elem_data["x"], "y": elem_data["y"],
                "width": elem_data["radius"] * 2, "height": elem_data["radius"] * 2,
                "fill": elem_data.get("fill"), "stroke": elem_data.get("stroke"),
                "strokeWidth": elem_data.get("stroke_width", 1),
                "layer": "symbol",
            }
        elif elem_type == "ellipse":
            return {
                "type": "ellipse",
                "x": elem_data["x"], "y": elem_data["y"],
                "width": elem_data["width"], "height": elem_data["height"],
                "fill": elem_data.get("fill"), "stroke": elem_data.get("stroke"),
                "strokeWidth": elem_data.get("stroke_width", 1),
                "layer": "symbol",
            }
        elif elem_type == "line":
            return {
                "type": "line",
                "x": elem_data["x1"], "y": elem_data["y1"],
                "width": elem_data["x2"] - elem_data["x1"],
                "height": elem_data["y2"] - elem_data["y1"],
                "stroke": elem_data.get("stroke", "#333"),
                "strokeWidth": elem_data.get("stroke_width", 1),
                "layer": "symbol",
            }
        elif elem_type == "text":
            return {
                "type": "text",
                "x": elem_data["x"], "y": elem_data["y"],
                "text": elem_data["text"].format(name=equip_id),
                "fontSize": elem_data.get("font_size", 12),
                "fontFamily": elem_data.get("font_family", "Arial"),
                "layer": "labels",
            }
        return {"type": "rect", "x": 0, "y": 0, "width": 0, "height": 0, "layer": "symbol"}

    def _add_point_bindings(self, graphic: dict, equip: Equipment) -> None:
        """Add point bindings around equipment symbol."""
        points = self.project.get_points_for_equipment(equip.id)

        # Group points by kind for layout
        sensors = [p for p in points if p.kind == PointKind.SENSOR]
        actuators = [p for p in points if p.kind == PointKind.ACTUATOR]
        setpoints = [p for p in points if p.kind == PointKind.SETPOINT]
        status = [p for p in points if p.kind == PointKind.STATUS]
        alarms = [p for p in points if p.kind == PointKind.ALARM]

        positions = {
            "sensors": {"start": (0.05, 0.3), "step": (0, 0.1)},
            "actuators": {"start": (0.95, 0.3), "step": (0, 0.1)},
            "setpoints": {"start": (0.3, 0.05), "step": (0.15, 0)},
            "status": {"start": (0.3, 0.95), "step": (0.15, 0)},
            "alarms": {"start": (0.05, 0.95), "step": (0.1, 0)},
        }

        # Add sensor bindings (left side)
        for i, point in enumerate(sensors):
            pos = positions["sensors"]
            x = pos["start"][0] + i * pos["step"][0]
            y = pos["start"][1] + i * pos["step"][1]
            graphic["bindings"].append({
                "point_name": point.name,
                "binding_type": "value",
                "x": x, "y": y,
                "label": point.name,
                "format": self._get_format(point),
                "min_max": (point.range_min, point.range_max) if point.range_min is not None and point.range_max is not None else None,
            })

        # Add actuator bindings (right side)
        for i, point in enumerate(actuators):
            pos = positions["actuators"]
            x = pos["start"][0] + i * pos["step"][0]
            y = pos["start"][1] + i * pos["step"][1]
            graphic["bindings"].append({
                "point_name": point.name,
                "binding_type": "command" if point.direction.value == "output" else "value",
                "x": x, "y": y,
                "label": point.name,
                "format": self._get_format(point),
            })

        # Add setpoint bindings (top)
        for i, point in enumerate(setpoints):
            pos = positions["setpoints"]
            x = pos["start"][0] + i * pos["step"][0]
            y = pos["start"][1] + i * pos["step"][1]
            graphic["bindings"].append({
                "point_name": point.name,
                "binding_type": "setpoint",
                "x": x, "y": y,
                "label": point.name,
                "format": self._get_format(point),
            })

        # Add status bindings (bottom)
        for i, point in enumerate(status):
            pos = positions["status"]
            x = pos["start"][0] + i * pos["step"][0]
            y = pos["start"][1] + i * pos["step"][1]
            graphic["bindings"].append({
                "point_name": point.name,
                "binding_type": "status",
                "x": x, "y": y,
                "label": point.name,
                "format": "on/off",
                "color_map": {"on": "#4caf50", "off": "#f44336", "open": "#4caf50", "closed": "#f44336"},
            })

        # Add alarm bindings (bottom-left)
        for i, point in enumerate(alarms):
            pos = positions["alarms"]
            x = pos["start"][0] + i * pos["step"][0]
            y = pos["start"][1] + i * pos["step"][1]
            graphic["bindings"].append({
                "point_name": point.name,
                "binding_type": "alarm",
                "x": x, "y": y,
                "label": f"⚠ {point.name}",
                "color_map": {"normal": "#4caf50", "alarm": "#f44336", "fault": "#ff9800"},
            })

    def _get_format(self, point: Point) -> str:
        """Get display format for a point."""
        if point.units:
            if "deg" in point.units.lower() or "temp" in point.units.lower():
                return ".1f"
            if any(u in point.units.lower() for u in ["cfm", "gpm", "lps", "flow"]):
                return ".0f"
            if any(u in point.units.lower() for u in ["inwc", "wc", "psi", "pa", "kpa", "pressure"]):
                return ".2f"
            if "%" in point.units:
                return ".0f"
        return ".1f"

    def _export_system_graphics(self) -> None:
        """Generate system-level graphics (AHU systems, plant, etc.)."""
        # Group equipment by type for system graphics
        ahu_systems = {}
        for equip in self.project.equipment:
            if equip.type == EquipmentType.AHU:
                # Find children (VAVs, etc.)
                children = [e for e in self.project.equipment
                            if e.parent_equipment_id == equip.id]
                ahu_systems[equip.id] = {
                    "ahu": equip,
                    "children": children,
                }

        for ahu_id, system in ahu_systems.items():
            self._generate_ahu_system_graphic(system)

    def _generate_ahu_system_graphic(self, system: dict) -> GraphicDefinition:
        """Generate AHU system graphic with VAVs."""
        ahu = system["ahu"]
        children = system["children"]

        graphic = GraphicDefinition(
            graphic_id=f"graphic_system_{ahu.id.lower()}",
            name=f"{ahu.id} System",
            graphic_type=GraphicType.SYSTEM,
            equipment_id=ahu.id,
            width=1600,
            height=1000,
            metadata={"system_type": "AHU", "ahu": ahu.id},
        )

        # AHU symbol (center-left)
        graphic.elements.append(GraphicElement(
            element_type="rect", x=0.1, y=0.3, width=0.25, height=0.4,
            fill="#e0e0e0", stroke="#333", stroke_width=2, layer="equipment",
        ))
        graphic.elements.append(GraphicElement(
            element_type="text", x=0.225, y=0.5, text=ahu.id,
            font_size=16, layer="labels",
        ))

        # Supply duct line
        graphic.elements.append(GraphicElement(
            element_type="line", x=0.35, y=0.5, width=0.3, height=0,
            stroke="#1976d2", stroke_width=3, layer="piping",
        ))

        # VAV boxes along duct
        for i, vav in enumerate(children):
            y = 0.2 + (i * 0.6 / max(len(children), 1))
            # VAV box
            graphic.elements.append(GraphicElement(
                element_type="rect", x=0.7, y=y, width=0.15, height=0.1,
                fill="#fff", stroke="#333", stroke_width=1, layer="equipment",
            ))
            graphic.elements.append(GraphicElement(
                element_type="text", x=0.775, y=y + 0.05, text=vav.id,
                font_size=10, layer="labels",
            ))
            # Duct connection
            graphic.elements.append(GraphicElement(
                element_type="line", x=0.65, y=y + 0.05, width=0.05, height=0,
                stroke="#1976d2", stroke_width=2, layer="piping",
            ))

            # Add VAV point bindings
            vav_points = self.project.get_points_for_equipment(vav.id)
            for point in vav_points:
                if point.kind in (PointKind.SENSOR, PointKind.SETPOINT):
                    graphic.bindings.append(GraphicBinding(
                        point_name=point.name,
                        binding_type=BindingType.VALUE if point.kind == PointKind.SENSOR else BindingType.SETPOINT,
                        x=0.7 + 0.15, y=y + 0.05,
                        label=point.name,
                        format=self._get_format(point),
                    ))

        # Return duct
        graphic.elements.append(GraphicElement(
            element_type="line", x=0.35, y=0.7, width=0.3, height=0,
            stroke="#ef6c00", stroke_width=3, layer="piping",
        ))

        return graphic

    def _element_to_niagara_type(self, elem: GraphicElement) -> str:
        """Map element type to Niagara component type."""
        mapping = {
            "rect": "rectangle",
            "circle": "ellipse",
            "ellipse": "ellipse",
            "line": "line",
            "text": "label",
        }
        return mapping.get(elem.element_type, "rectangle")

    def _export_alarms(self, output_dir: Path) -> Path:
        """Export alarm configuration."""
        path = output_dir / "alarms.json"

        alarms_data = {"alarms": []}
        for point in self.project.points:
            if point.kind == PointKind.ALARM or point.range_min is not None or point.range_max is not None:
                alarm_id = self._uid("alarm", f"{point.name}_alm")
                alarm_data = {
                    "name": f"{point.name}_Alarm",
                    "id": alarm_id,
                    "point": point.name,
                    "type": "limit",
                    "priority": 3,
                    "ackRequired": True,
                }

                if point.range_min is not None:
                    alarm_data["lowLimit"] = point.range_min
                if point.range_max is not None:
                    alarm_data["highLimit"] = point.range_max
                if point.range_min is not None and point.range_max is not None:
                    alarm_data["deadband"] = (point.range_max - point.range_min) * 0.01

                alarms_data["alarms"].append(alarm_data)

        with open(output_dir / "alarms.json", "w") as f:
            json.dump(alarms_data, f, indent=2)
        return output_dir / "alarms.json"

    def _export_schedules(self, output_dir: Path) -> Path:
        """Export schedule configuration."""
        path = output_dir / "schedules.json"

        schedules_data = {"schedules": []}

        # Default occupancy schedule
        schedule_id = self._uid("schedule", "occupancy_default")
        schedule_data = {
            "name": "Occupancy_Default",
            "id": schedule_id,
            "type": "schedule",
            "description": "Default occupancy schedule",
            "schedule": {
                "monday": {"occupied": "07:00", "unoccupied": "19:00"},
                "tuesday": {"occupied": "07:00", "unoccupied": "19:00"},
                "wednesday": {"occupied": "07:00", "unoccupied": "19:00"},
                "thursday": {"occupied": "07:00", "unoccupied": "19:00"},
                "friday": {"occupied": "07:00", "unoccupied": "19:00"},
                "saturday": {"occupied": "08:00", "unoccupied": "14:00"},
                "sunday": {"occupied": "", "unoccupied": ""},
                "holiday": {"occupied": "", "unoccupied": ""},
            },
        }
        schedules_data["schedules"].append(schedule_data)

        with open(output_dir / "schedules.json", "w") as f:
            json.dump(schedules_data, f, indent=2)
        return output_dir / "schedules.json"

    def _export_trends(self, output_dir: Path) -> Path:
        """Export trend log configuration."""
        path = output_dir / "trends.json"

        trends_data = {"trends": []}
        for point in self.project.points:
            if point.kind in (PointKind.SENSOR, PointKind.TREND):
                trend_id = self._uid("trend", f"{point.name}_trend")
                trend_data = {
                    "name": f"{point.name}_Trend",
                    "id": trend_id,
                    "point": point.name,
                    "interval": "15m",
                    "retention": "30d",
                    "enabled": True,
                    "type": "interval",
                }
                trends_data["trends"].append(trend_data)

        with open(path, "w") as f:
            json.dump(trends_data, f, indent=2)
        return path

    def _create_bog_archive(self, wxf_dir: Path, bog_path: Path) -> None:
        """Create Niagara station archive (.bog) from WXF directory."""
        import zipfile
        with zipfile.ZipFile(bog_path, 'w', zipfile.ZIP_DEFLATED) as bog:
            for file_path in wxf_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(wxf_dir)
                    bog.write(file_path, arcname)


def export_niagara(project: Project, output_dir: Path) -> ExportResult:
    """Convenience function to export to Niagara format."""
    exporter = NiagaraExporter(project)
    return exporter.export(output_dir)


__all__ = ["NiagaraExporter", "export_niagara"]
