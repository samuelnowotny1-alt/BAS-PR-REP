"""Niagara Framework exporter - Niagara-like JSON station structure and archive."""

from __future__ import annotations

import json
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ..generators.graphics import GraphicDefinition, GraphicElement, GraphicsGenerator
from ..models import Controller, Equipment, EquipmentType, Point, PointKind, Project
from .base import BaseExporter, ExportResult


class NiagaraExporter(BaseExporter):
    """Export a BAS project into a Niagara-inspired station structure."""

    vendor_name = "Niagara"
    file_extension = ".wxf"

    SYMBOLS = {
        "ahu": [
            {"type": "rect", "x": 120, "y": 130, "width": 300, "height": 190, "fill": "#e0e0e0", "stroke": "#333"},
            {"type": "text", "x": 270, "y": 225, "text": "{name}", "fontSize": 18},
        ],
        "vav": [
            {"type": "rect", "x": 160, "y": 120, "width": 220, "height": 160, "fill": "#ffffff", "stroke": "#333"},
            {"type": "text", "x": 270, "y": 200, "text": "{name}", "fontSize": 14},
        ],
        "chiller": [
            {"type": "ellipse", "x": 120, "y": 130, "width": 300, "height": 190, "fill": "#cce5ff", "stroke": "#333"},
            {"type": "text", "x": 270, "y": 225, "text": "{name}", "fontSize": 18},
        ],
        "boiler": [
            {"type": "rect", "x": 120, "y": 130, "width": 300, "height": 190, "fill": "#ffe0b2", "stroke": "#333"},
            {"type": "text", "x": 270, "y": 225, "text": "{name}", "fontSize": 18},
        ],
        "pump": [
            {"type": "circle", "x": 190, "y": 120, "radius": 85, "fill": "#ffffff", "stroke": "#333"},
            {"type": "text", "x": 275, "y": 210, "text": "{name}", "fontSize": 14},
        ],
    }

    POINT_KIND_TO_SLOT = {
        PointKind.SENSOR: "control:NumericPoint",
        PointKind.ACTUATOR: "control:NumericWritable",
        PointKind.SETPOINT: "control:NumericWritable",
        PointKind.STATUS: "control:BooleanPoint",
        PointKind.ALARM: "alarm:AlarmSourceExt",
        PointKind.TREND: "history:BooleanTrendExt",
        PointKind.SCHEDULE: "schedule:SchedulePoint",
        PointKind.CALCULATED: "control:NumericPoint",
        PointKind.PARAMETER: "control:NumericWritable",
        PointKind.DERIVED: "control:NumericPoint",
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
        self._uids: dict[str, str] = {}
        self._graphics_generator: GraphicsGenerator | None = None
        self._graphic_cache: dict[str, GraphicDefinition] | None = None

    def _uid(self, prefix: str, key: str) -> str:
        if key not in self._uids:
            namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
            self._uids[key] = str(uuid.uuid5(namespace, f"{prefix}:{key}"))
        return self._uids[key]

    def _sanitize_name(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_:-]+", "_", value.strip())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned or "unnamed"

    def _slot_path(self, *segments: str) -> str:
        normalized = [self._sanitize_name(segment) for segment in segments if segment]
        return "/" + "/".join(normalized)

    def _ord(self, *segments: str) -> str:
        return f"station:|slot:{self._slot_path(*segments)}"

    def _facet_block(
        self,
        *,
        units: str | None = None,
        precision: int | None = None,
        writable: bool | None = None,
        summary: str | None = None,
    ) -> dict[str, object]:
        facets: dict[str, object] = {
            "BFacets": True,
            "summary": summary or "",
        }
        if units:
            facets["units"] = units
        if precision is not None:
            facets["precision"] = precision
        if writable is not None:
            facets["writable"] = writable
        return facets

    def _action_block(self, view_ord: str | None = None) -> list[dict[str, str]]:
        actions = [{"name": "open", "displayName": "Open"}]
        if view_ord:
            actions.append({"name": "pxView", "displayName": "Open Px", "ord": view_ord})
        return actions

    def _component_node(
        self,
        *,
        name: str,
        slot_type: str,
        slot_path: str,
        display_name: str,
        parent_path: str | None,
        facets: dict[str, object] | None = None,
        annotations: dict[str, object] | None = None,
        actions: list[dict[str, str]] | None = None,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        node = {
            "id": self._uid("slot", slot_path),
            "name": self._sanitize_name(name),
            "displayName": display_name,
            "slotType": slot_type,
            "slotPath": slot_path,
            "ord": f"station:|slot:{slot_path}",
            "parentSlotPath": parent_path,
            "parentOrd": f"station:|slot:{parent_path}" if parent_path else None,
            "facets": facets or self._facet_block(summary=display_name),
            "actions": actions or self._action_block(),
            "annotations": annotations or {},
            "children": [],
        }
        if extra:
            node.update(extra)
        return node

    def _point_ord(self, point: Point) -> str:
        controller_name = self.project.effective_point_controller_id(point) or "Unassigned"
        return self._ord("Drivers", "BacnetNetwork", controller_name, "Points", point.name)

    def _point_slot_path(self, point: Point) -> str:
        controller_name = self.project.effective_point_controller_id(point) or "Unassigned"
        return self._slot_path("Drivers", "BacnetNetwork", controller_name, "Points", point.name)

    def _equipment_slot_path(self, equip: Equipment) -> str:
        return self._slot_path(
            "Config",
            "Equipment",
            equip.building or "DefaultBuilding",
            equip.floor or "DefaultFloor",
            equip.id,
        )

    def _equipment_page_ord(self, equip: Equipment) -> str:
        return self._ord("Px", "Equipment", equip.id)

    def export(self, output_dir: Path, **kwargs) -> ExportResult:
        self._ensure_output_dir(output_dir)
        errors: list[str] = []
        warnings: list[str] = []
        files: list[Path] = []

        try:
            wxf_dir = output_dir / f"{self.project.metadata.project_id}_wxf"
            wxf_dir.mkdir(exist_ok=True)

            exporters = [
                self._export_station,
                self._export_navigation,
                self._export_points,
                self._export_devices,
                self._export_alarms,
                self._export_schedules,
                self._export_trends,
            ]
            for exporter in exporters:
                exporter(wxf_dir)

            self._export_graphics(wxf_dir)

            files.extend(sorted(path for path in wxf_dir.rglob("*") if path.is_file()))

            bog_path = output_dir / f"{self.project.metadata.project_id}.bog"
            self._create_bog_archive(wxf_dir, bog_path)
            files.append(bog_path)
        except Exception as exc:
            errors.append(f"Export failed: {exc}")

        return ExportResult(
            success=len(errors) == 0,
            message=f"Niagara export {'completed' if not errors else 'failed'}",
            files=files,
            errors=errors,
            warnings=warnings,
        )

    def preview_pages(self) -> list[dict[str, object]]:
        """Return PX page payloads for browser preview."""
        pages = [self._dashboard_page()["pxPage"]]
        for equip in self.project.equipment:
            points = self.project.get_points_for_equipment(equip.id)
            if not points:
                continue
            pages.append(self._equipment_page(equip, points)["pxPage"])
        return pages

    def _export_station(self, output_dir: Path) -> Path:
        root_components = [
            self._component_node(
                name="Drivers",
                slot_type="driver:DriverContainer",
                slot_path=self._slot_path("Drivers"),
                display_name="Drivers",
                parent_path="/",
                facets=self._facet_block(summary="Protocol driver container"),
                annotations={"role": "drivers"},
            ),
            self._component_node(
                name="Config",
                slot_type="baja:Folder",
                slot_path=self._slot_path("Config"),
                display_name="Config",
                parent_path="/",
                facets=self._facet_block(summary="Station configuration"),
                annotations={"role": "config"},
            ),
            self._component_node(
                name="Px",
                slot_type="px:PxContainer",
                slot_path=self._slot_path("Px"),
                display_name="Px",
                parent_path="/",
                facets=self._facet_block(summary="Px page container"),
                annotations={"role": "px"},
            ),
            self._component_node(
                name="Alarms",
                slot_type="alarm:AlarmService",
                slot_path=self._slot_path("Services", "Alarms"),
                display_name="Alarms",
                parent_path="/",
                facets=self._facet_block(summary="Alarm service"),
                annotations={"role": "alarms"},
            ),
            self._component_node(
                name="Schedules",
                slot_type="schedule:ScheduleService",
                slot_path=self._slot_path("Services", "Schedules"),
                display_name="Schedules",
                parent_path="/",
                facets=self._facet_block(summary="Schedule service"),
                annotations={"role": "schedules"},
            ),
            self._component_node(
                name="Histories",
                slot_type="history:HistoryService",
                slot_path=self._slot_path("Services", "Histories"),
                display_name="Histories",
                parent_path="/",
                facets=self._facet_block(summary="History service"),
                annotations={"role": "histories"},
            ),
        ]

        station = {
            "station": {
                "name": self.project.metadata.name,
                "id": self._uid("station", self.project.metadata.project_id),
                "ord": "station:|slot:/",
                "slotPath": "/",
                "description": self.project.metadata.client or "",
                "timezone": self.project.metadata.timezone or "UTC",
                "created": self.project.metadata.created_at.isoformat(),
                "modified": self.project.metadata.updated_at.isoformat(),
                "version": "4.12",
                "vendor": "Tridium",
                "application": "BAS Assistant",
                "facets": self._facet_block(summary="Niagara station root"),
                "slots": root_components,
            }
        }

        return self._write_parallel_artifacts(base_path=output_dir / "station", payload=station)

    def _export_navigation(self, output_dir: Path) -> Path:
        nav_root = {
            "navigation": {
                "name": "Navigation",
                "id": self._uid("nav", "root"),
                "slotPath": self._slot_path("Config", "Navigation"),
                "ord": self._ord("Config", "Navigation"),
                "slotType": "nav:NavContainer",
                "children": [],
            }
        }

        grouped: dict[tuple[str, str], list[Equipment]] = {}
        for equip in self.project.equipment:
            key = (equip.building or "Default Building", equip.floor or "Default Floor")
            grouped.setdefault(key, []).append(equip)

        for (building, floor), equipment_items in grouped.items():
            building_path = self._slot_path("Config", "Equipment", building)
            building_node = self._component_node(
                name=building,
                slot_type="nav:NavFolder",
                slot_path=building_path,
                display_name=building,
                parent_path=self._slot_path("Config", "Navigation"),
                facets=self._facet_block(summary=f"Building folder for {building}"),
                annotations={"level": "building"},
            )

            floor_path = self._slot_path("Config", "Equipment", building, floor)
            floor_node = self._component_node(
                name=floor,
                slot_type="nav:NavFolder",
                slot_path=floor_path,
                display_name=floor,
                parent_path=building_path,
                facets=self._facet_block(summary=f"Floor folder for {floor}"),
                annotations={"level": "floor"},
            )

            for equip in equipment_items:
                equip_path = self._equipment_slot_path(equip)
                equip_node = self._component_node(
                    name=equip.id,
                    slot_type=f"equip:{self.EQUIPMENT_TYPE_TO_NAV.get(equip.type, 'equipment')}",
                    slot_path=equip_path,
                    display_name=equip.id,
                    parent_path=floor_path,
                    facets=self._facet_block(summary=equip.served_area or equip.type.value),
                    annotations={
                        "level": "equipment",
                        "equipmentType": equip.type.value,
                        "pxPageOrd": self._equipment_page_ord(equip),
                    },
                    actions=self._action_block(self._equipment_page_ord(equip)),
                    extra={
                        "navOrd": self._ord("Config", "Navigation", building, floor, equip.id),
                        "pxPageRef": {
                            "ord": self._equipment_page_ord(equip),
                            "displayName": f"{equip.id} Px Page",
                        },
                    },
                )

                for point in self.project.get_points_for_equipment(equip.id):
                    point_path = self._point_slot_path(point)
                    point_node = self._component_node(
                        name=point.name,
                        slot_type="control:ControlPoint",
                        slot_path=point_path,
                        display_name=point.name,
                        parent_path=equip_path,
                        facets=self._facet_block(
                            units=point.units,
                            precision=self._display_precision(point),
                            writable=point.direction.value in ("output", "bidirectional"),
                            summary=point.description or point.name,
                        ),
                        annotations={
                            "kind": point.kind.value,
                            "pointOrd": self._point_ord(point),
                            "equipmentOrd": self._ord(*equip_path.strip("/").split("/")),
                        },
                    )
                    equip_node["children"].append(point_node)

                floor_node["children"].append(equip_node)

            building_node["children"].append(floor_node)
            nav_root["navigation"]["children"].append(building_node)

        return self._write_parallel_artifacts(base_path=output_dir / "navigation", payload=nav_root)

    def _export_points(self, output_dir: Path) -> Path:
        payload: dict[str, list[dict[str, object]]] = {"points": []}

        for point in self.project.points:
            effective_equipment_id = self.project.effective_point_equipment_id(point) or point.equipment_id
            effective_controller_id = self.project.effective_point_controller_id(point)
            equip = self.project.get_equipment(effective_equipment_id)
            controller = self.project.get_controller(effective_controller_id) if effective_controller_id else None
            slot_path = self._point_slot_path(point)
            point_data = self._component_node(
                name=point.name,
                slot_type=self.POINT_KIND_TO_SLOT.get(point.kind, "control:NumericPoint"),
                slot_path=slot_path,
                display_name=point.name,
                parent_path=self._slot_path("Drivers", "BacnetNetwork", effective_controller_id or "Unassigned", "Points"),
                facets=self._facet_block(
                    units=point.units,
                    precision=self._display_precision(point),
                    writable=point.direction.value in ("output", "bidirectional"),
                    summary=point.description or point.name,
                ),
                annotations={
                    "kind": point.kind.value,
                    "direction": point.direction.value,
                    "equipmentOrd": self._ord(*self._equipment_slot_path(equip).strip("/").split("/")) if equip else "",
                    "controllerOrd": self._device_ord(controller) if controller else "",
                },
                extra={
                    "proxyExt": self._point_proxy(point, controller),
                    "pointBinding": {
                        "ord": self._point_ord(point),
                        "slotPath": slot_path,
                        "navName": point.name,
                    },
                    "range": {
                        "min": point.range_min,
                        "max": point.range_max,
                    },
                },
            )
            payload["points"].append(point_data)

        return self._write_parallel_artifacts(base_path=output_dir / "points", payload=payload)

    def _export_devices(self, output_dir: Path) -> Path:
        payload: dict[str, list[dict[str, object]]] = {"devices": []}

        for controller in self.project.controllers:
            device_path = self._device_slot_path(controller)
            point_children = [
                {
                    "name": self._sanitize_name(point.name),
                    "displayName": point.name,
                    "ord": self._point_ord(point),
                    "slotPath": self._point_slot_path(point),
                    "parentOrd": self._device_ord(controller),
                }
                for point in self.project.get_points_for_controller(controller.id)
            ]
            device = self._component_node(
                name=controller.id,
                slot_type="bacnet:BacnetDevice",
                slot_path=device_path,
                display_name=controller.name or controller.id,
                parent_path=self._slot_path("Drivers", "BacnetNetwork"),
                facets=self._facet_block(summary=controller.vendor or controller.type),
                annotations={
                    "vendor": controller.vendor or "Generic",
                    "model": controller.model or "",
                    "panelLocation": controller.panel_location or "",
                },
                extra={
                    "protocols": [protocol.value for protocol in controller.protocols],
                    "points": point_children,
                    "networkExt": self._device_network_ext(controller),
                    "children": point_children,
                },
            )
            payload["devices"].append(device)

        return self._write_parallel_artifacts(base_path=output_dir / "devices", payload=payload)

    def _export_alarms(self, output_dir: Path) -> Path:
        alarms: list[dict[str, object]] = []
        for point in self.project.points:
            if point.kind != PointKind.ALARM and point.range_min is None and point.range_max is None:
                continue
            deadband = None
            if point.range_min is not None and point.range_max is not None:
                deadband = (point.range_max - point.range_min) * 0.01
            alarms.append(
                {
                    "id": self._uid("alarm", f"{point.name}:alarm"),
                    "name": f"{point.name}_Alarm",
                    "ord": self._ord("Services", "Alarms", f"{point.name}_Alarm"),
                    "sourceOrd": self._point_ord(point),
                    "slotType": "alarm:AlarmExt",
                    "facets": self._facet_block(summary=f"Alarm ext for {point.name}"),
                    "limits": {
                        "low": point.range_min,
                        "high": point.range_max,
                        "deadband": deadband,
                    },
                    "ackRequired": True,
                    "priority": 3,
                }
            )

        return self._write_parallel_artifacts(
            base_path=output_dir / "alarms",
            payload={"alarms": alarms},
        )

    def _export_schedules(self, output_dir: Path) -> Path:
        schedule = {
            "id": self._uid("schedule", "occupancy_default"),
            "name": "Occupancy_Default",
            "ord": self._ord("Services", "Schedules", "Occupancy_Default"),
            "slotType": "schedule:WeeklySchedule",
            "facets": self._facet_block(summary="Default occupancy schedule"),
            "entries": {
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

        return self._write_parallel_artifacts(
            base_path=output_dir / "schedules",
            payload={"schedules": [schedule]},
        )

    def _export_trends(self, output_dir: Path) -> Path:
        trends: list[dict[str, object]] = []
        for point in self.project.points:
            if point.kind not in (PointKind.SENSOR, PointKind.TREND):
                continue
            trends.append(
                {
                    "id": self._uid("trend", f"{point.name}:trend"),
                    "name": f"{point.name}_Trend",
                    "ord": self._ord("Services", "Histories", f"{point.name}_Trend"),
                    "slotType": "history:NumericTrendExt",
                    "sourceOrd": self._point_ord(point),
                    "facets": self._facet_block(units=point.units, summary=f"Trend for {point.name}"),
                    "historyConfig": {
                        "interval": "15m",
                        "retention": "30d",
                        "enabled": True,
                    },
                }
            )

        return self._write_parallel_artifacts(
            base_path=output_dir / "trends",
            payload={"trends": trends},
        )

    def _export_graphics(self, output_dir: Path) -> list[Path]:
        graphics_dir = output_dir / "graphics"
        graphics_dir.mkdir(exist_ok=True)
        files: list[Path] = []

        dashboard = self._dashboard_page()
        dashboard_path = graphics_dir / "dashboard_main.json"
        dashboard_path.write_text(json.dumps(dashboard, indent=2))
        self._write_xml_payload(dashboard, graphics_dir / "dashboard_main.px", artifact_name="dashboard_main")
        files.append(dashboard_path)

        for equip in self.project.equipment:
            points = self.project.get_points_for_equipment(equip.id)
            if not points:
                continue
            graphic = self._equipment_page(equip, points)
            graphic_name = self._sanitize_name(equip.id)
            graphic_path = graphics_dir / f"{graphic_name}.json"
            graphic_path.write_text(json.dumps(graphic, indent=2))
            self._write_xml_payload(graphic, graphics_dir / f"{graphic_name}.px", artifact_name=graphic_name)
            files.append(graphic_path)

        return files

    def _dashboard_page(self) -> dict[str, object]:
        children = []
        bindings = []
        x = 40
        y = 110
        for index, equip in enumerate(self.project.equipment):
            if index and index % 3 == 0:
                x = 40
                y += 140
            children.append(
                {
                    "id": self._uid("px:widget", f"dashboard:{equip.id}:card"),
                    "name": f"{self._sanitize_name(equip.id)}_card",
                    "parentId": "root",
                    "slotType": "px:LinkButton",
                    "displayName": equip.id,
                    "position": {"x": x, "y": y, "width": 220, "height": 90},
                    "facets": self._facet_block(summary=f"Navigation card for {equip.id}"),
                    "navigation": {"targetOrd": self._equipment_page_ord(equip), "displayName": equip.id},
                }
            )
            bindings.append(
                {
                    "id": self._uid("binding", f"dashboard:{equip.id}"),
                    "widgetId": self._uid("px:widget", f"dashboard:{equip.id}:card"),
                    "bindingType": "navigation",
                    "targetOrd": self._equipment_page_ord(equip),
                }
            )
            x += 250

        return {
            "pxPage": {
                "id": self._uid("px", "dashboard_main"),
                "name": "dashboard_main",
                "displayName": "Dashboard",
                "slotType": "px:PxPage",
                "slotPath": self._slot_path("Px", "Dashboard", "dashboard_main"),
                "ord": self._ord("Px", "Dashboard", "dashboard_main"),
                "navigationOrd": self._ord("Config", "Navigation"),
                "facets": self._facet_block(summary="Main station dashboard"),
                "navigation": {"home": True, "children": [self._equipment_page_ord(equip) for equip in self.project.equipment]},
                "components": {
                    "root": {
                        "id": "root",
                        "slotType": "px:CanvasPane",
                        "children": children,
                    }
                },
                "bindings": bindings,
            }
        }

    def _equipment_page(self, equip: Equipment, points: list[Point]) -> dict[str, object]:
        page_id = self._uid("px", equip.id)
        components: list[dict[str, object]] = []
        bindings: list[dict[str, object]] = []
        graphic = self._graphic_definition_for_equipment(equip)
        if graphic:
            for index, element in enumerate(graphic.elements):
                components.append(self._px_component_from_graphic_element(element, equip, page_id, index, graphic))
        else:
            symbol_key = self._symbol_key(equip)
            for element in self.SYMBOLS.get(symbol_key, self.SYMBOLS["ahu"]):
                components.append(self._px_component_from_symbol(element, equip, page_id))

        components.append(
            {
                "id": self._uid("px:widget", f"{equip.id}:title"),
                "name": "title",
                "parentId": "root",
                "slotType": "px:Label",
                "displayName": equip.id,
                "position": {"x": 40, "y": 30, "width": 520, "height": 30},
                "facets": self._facet_block(summary=f"Equipment title for {equip.id}"),
            }
        )

        generated_bindings = {binding.point_name: binding for binding in graphic.bindings} if graphic else {}
        grouped = {
            "sensor": (40, 390),
            "actuator": (600, 390),
            "setpoint": (40, 520),
            "status": (600, 520),
            "alarm": (40, 650),
        }
        counts = {key: 0 for key in grouped}

        for point in points:
            family = self._binding_family(point)
            generated_binding = generated_bindings.get(point.name)
            if generated_binding:
                position = {
                    "x": int(generated_binding.x * graphic.width),
                    "y": int(generated_binding.y * graphic.height),
                    "width": 240,
                    "height": 28,
                }
            else:
                base_x, base_y = grouped.get(family, (40, 390))
                offset = counts.get(family, 0)
                counts[family] = offset + 1
                position = {"x": base_x, "y": base_y + offset * 34, "width": 260, "height": 28}
            widget_id = self._uid("px:widget", f"{equip.id}:{point.name}:widget")
            components.append(
                {
                    "id": widget_id,
                    "name": self._sanitize_name(point.name),
                    "parentId": "root",
                    "slotType": "px:BoundLabel",
                    "displayName": point.name,
                    "position": position,
                    "facets": self._facet_block(
                        units=point.units,
                        precision=self._display_precision(point),
                        writable=point.direction.value in ("output", "bidirectional"),
                        summary=point.description or point.name,
                    ),
                    "annotations": {"equipmentId": equip.id, "pointOrd": self._point_ord(point)},
                }
            )
            bindings.append(
                {
                    "id": self._uid("binding", f"{equip.id}:{point.name}"),
                    "widgetId": widget_id,
                    "bindingType": family,
                    "label": point.name,
                    "sourceOrd": self._point_ord(point),
                    "slotPath": self._point_slot_path(point),
                    "format": self._display_format(point),
                    "actions": self._action_block(self._point_ord(point)),
                }
            )

        return {
            "pxPage": {
                "id": page_id,
                "name": self._sanitize_name(equip.id),
                "displayName": equip.id,
                "slotType": "px:PxPage",
                "slotPath": self._slot_path("Px", "Equipment", equip.id),
                "ord": self._equipment_page_ord(equip),
                "equipmentOrd": self._ord(*self._equipment_slot_path(equip).strip("/").split("/")),
                "navigationOrd": self._ord("Config", "Navigation", equip.building or "Default Building", equip.floor or "Default Floor", equip.id),
                "navigation": {
                    "back": self._ord("Px", "Dashboard", "dashboard_main"),
                    "breadcrumbs": [
                        self._ord("Config", "Navigation"),
                        self._ord("Config", "Navigation", equip.building or "Default Building"),
                        self._ord("Config", "Navigation", equip.building or "Default Building", equip.floor or "Default Floor"),
                        self._equipment_page_ord(equip),
                    ],
                },
                "facets": self._facet_block(summary=f"Px page for {equip.id}"),
                "components": {
                    "root": {
                        "id": "root",
                        "slotType": "px:CanvasPane",
                        "children": components,
                    }
                },
                "bindings": bindings,
            }
        }

    def _graphic_definition_for_equipment(self, equip: Equipment) -> GraphicDefinition | None:
        if self._graphic_cache is None:
            self._graphics_generator = GraphicsGenerator(self.project)
            self._graphic_cache = self._graphics_generator.generate_all()
        return self._graphic_cache.get(f"graphic_{equip.id.lower()}")

    def _px_component_from_graphic_element(
        self,
        element: GraphicElement,
        equip: Equipment,
        page_id: str,
        index: int,
        graphic: GraphicDefinition,
    ) -> dict[str, object]:
        widget_id = self._uid("px:widget", f"{page_id}:{equip.id}:{element.element_type}:{index}")
        position = self._graphic_element_position(element, graphic)
        return {
            "id": widget_id,
            "name": self._sanitize_name(f"{equip.id}_{element.element_type}_{index}"),
            "parentId": "root",
            "slotType": f"px:{element.element_type.title()}",
            "displayName": element.text or equip.id,
            "position": position,
            "style": {
                "fill": element.fill,
                "stroke": element.stroke,
                "strokeWidth": element.stroke_width,
                "fontSize": element.font_size,
                "fontFamily": element.font_family,
            },
            "facets": self._facet_block(summary=f"{element.element_type} widget for {equip.id}"),
        }

    def _graphic_element_position(self, element: GraphicElement, graphic: GraphicDefinition) -> dict[str, int]:
        x = int(element.x * graphic.width)
        y = int(element.y * graphic.height)
        width = int(element.width * graphic.width)
        height = int(element.height * graphic.height)
        if element.element_type == "circle":
            return {"x": x - (width // 2), "y": y - (height // 2), "width": width, "height": height}
        if element.element_type == "ellipse":
            return {"x": x - (width // 2), "y": y - (height // 2), "width": width, "height": height}
        if element.element_type == "text":
            return {"x": x - 60, "y": y - 12, "width": max(width, 120), "height": max(height, 24)}
        if element.element_type == "line":
            return {
                "x": min(x, x + width),
                "y": min(y, y + height),
                "width": max(abs(width), 4),
                "height": max(abs(height), 4),
            }
        return {"x": x, "y": y, "width": max(width, 4), "height": max(height, 4)}

    def _px_component_from_symbol(self, element: dict[str, object], equip: Equipment, page_id: str) -> dict[str, object]:
        element_type = str(element["type"])
        widget_id = self._uid("px:widget", f"{page_id}:{equip.id}:{element_type}:{element.get('x')}:{element.get('y')}")
        if element_type == "circle":
            position = {
                "x": element["x"],
                "y": element["y"],
                "width": element["radius"] * 2,
                "height": element["radius"] * 2,
            }
        else:
            position = {
                "x": element["x"],
                "y": element["y"],
                "width": element.get("width", 0),
                "height": element.get("height", 0),
            }
        return {
            "id": widget_id,
            "name": self._sanitize_name(f"{equip.id}_{element_type}_{element.get('x')}_{element.get('y')}"),
            "parentId": "root",
            "slotType": f"px:{element_type.title()}",
            "displayName": str(element.get("text", "")).format(name=equip.id) or equip.id,
            "position": position,
            "style": {
                "fill": element.get("fill"),
                "stroke": element.get("stroke"),
                "strokeWidth": element.get("stroke_width"),
                "fontSize": element.get("fontSize"),
                "fontFamily": element.get("fontFamily"),
            },
            "facets": self._facet_block(summary=f"{element_type} widget for {equip.id}"),
        }

    def _point_proxy(self, point: Point, controller: Controller | None) -> dict[str, object]:
        proxy = {
            "pointOrd": self._point_ord(point),
            "slotPath": self._point_slot_path(point),
            "driverRef": self._device_ord(controller) if controller else self._ord("Drivers", "BacnetNetwork", "Unassigned"),
        }
        if point.bacnet_object_type:
            proxy["bacnetProxyExt"] = {
                "objectType": point.bacnet_object_type,
                "instance": point.bacnet_instance,
                "deviceOrd": self._device_ord(controller) if controller else "",
            }
        if point.modbus_register:
            proxy["modbusProxyExt"] = {
                "register": point.modbus_register,
                "registerType": point.modbus_type or "holding_register",
                "deviceOrd": self._device_ord(controller) if controller else "",
            }
        return proxy

    def _device_slot_path(self, controller: Controller) -> str:
        return self._slot_path("Drivers", "BacnetNetwork", controller.id)

    def _device_ord(self, controller: Controller) -> str:
        return self._ord("Drivers", "BacnetNetwork", controller.id)

    def _device_network_ext(self, controller: Controller) -> dict[str, object]:
        ext: dict[str, object] = {"addresses": []}
        for address in controller.network_addresses:
            ext["addresses"].append(
                {
                    "protocol": address.protocol.value,
                    "address": address.address,
                    "networkNumber": address.network_number,
                    "subnetMask": address.subnet_mask,
                    "gateway": address.gateway,
                }
            )
        return ext

    def _symbol_key(self, equip: Equipment) -> str:
        if equip.type in (EquipmentType.PUMP_CHW, EquipmentType.PUMP_CW, EquipmentType.PUMP_HW):
            return "pump"
        return equip.type.value.lower()

    def _binding_family(self, point: Point) -> str:
        if point.kind == PointKind.ACTUATOR:
            return "actuator"
        if point.kind == PointKind.SETPOINT:
            return "setpoint"
        if point.kind == PointKind.STATUS:
            return "status"
        if point.kind == PointKind.ALARM:
            return "alarm"
        return "sensor"

    def _display_precision(self, point: Point) -> int:
        units = (point.units or "").lower()
        if any(token in units for token in ("temp", "deg", "°")):
            return 1
        if any(token in units for token in ("cfm", "gpm", "lps", "%")):
            return 0
        if any(token in units for token in ("inwc", "psi", "pa", "kpa")):
            return 2
        return 1

    def _display_format(self, point: Point) -> str:
        precision = self._display_precision(point)
        return f".{precision}f"

    def _create_bog_archive(self, wxf_dir: Path, bog_path: Path) -> None:
        with zipfile.ZipFile(bog_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in wxf_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(wxf_dir))

    def _write_parallel_artifacts(
        self,
        *,
        base_path: Path,
        payload: dict[str, object],
        xml_suffix: str = ".wxf",
    ) -> Path:
        json_path = base_path.with_suffix(".json")
        json_path.write_text(json.dumps(payload, indent=2))
        xml_path = base_path.with_suffix(xml_suffix)
        self._write_xml_payload(payload, xml_path, artifact_name=base_path.name)
        return json_path

    def _write_xml_payload(self, payload: dict[str, object], path: Path, artifact_name: str | None = None) -> None:
        root_key, root_value = next(iter(payload.items()))
        if root_key == "station":
            root = self._station_xml(root_value)
        elif root_key == "navigation":
            root = self._navigation_xml(root_value)
        elif root_key == "points":
            root = self._points_xml(root_value)
        elif root_key == "devices":
            root = self._devices_xml(root_value)
        elif root_key == "alarms":
            root = self._alarms_xml(root_value)
        elif root_key == "schedules":
            root = self._schedules_xml(root_value)
        elif root_key == "trends":
            root = self._trends_xml(root_value)
        elif root_key == "pxPage":
            root = self._px_page_xml(root_value, artifact_name or path.stem)
        else:
            root = ET.Element(root_key)
            self._xml_append_generic(root, root_value)
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(path, encoding="utf-8", xml_declaration=True)

    def _xml_append_generic(self, parent: ET.Element, value: object, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                if isinstance(child_value, list):
                    list_node = ET.SubElement(parent, child_key)
                    for item in child_value:
                        item_node = ET.SubElement(list_node, "item")
                        self._xml_append_generic(item_node, item)
                else:
                    child = ET.SubElement(parent, child_key)
                    self._xml_append_generic(child, child_value)
            return
        if isinstance(value, list):
            for item in value:
                item_node = ET.SubElement(parent, key or "item")
                self._xml_append_generic(item_node, item)
            return
        if value is None:
            parent.text = ""
            return
        if isinstance(value, bool):
            parent.text = str(value).lower()
            return
        parent.text = str(value)

    def _text_child(self, parent: ET.Element, tag: str, value: object | None) -> ET.Element:
        child = ET.SubElement(parent, tag)
        if value is None:
            child.text = ""
        elif isinstance(value, bool):
            child.text = str(value).lower()
        else:
            child.text = str(value)
        return child

    def _xml_facets(self, parent: ET.Element, facets: dict[str, object]) -> None:
        facets_node = ET.SubElement(parent, "facets")
        for key, value in facets.items():
            facet_node = ET.SubElement(facets_node, "facet", name=key)
            facet_node.text = "" if value is None else str(value).lower() if isinstance(value, bool) else str(value)

    def _xml_annotations(self, parent: ET.Element, annotations: dict[str, object]) -> None:
        annotations_node = ET.SubElement(parent, "annotations")
        for key, value in annotations.items():
            annotation = ET.SubElement(annotations_node, "annotation", name=key)
            annotation.text = "" if value is None else str(value)

    def _xml_actions(self, parent: ET.Element, actions: list[dict[str, str]]) -> None:
        actions_node = ET.SubElement(parent, "actions")
        for action in actions:
            attrs = {"name": action.get("name", ""), "displayName": action.get("displayName", "")}
            if action.get("ord"):
                attrs["ord"] = action["ord"]
            ET.SubElement(actions_node, "action", attrs)

    def _slot_xml_attrs(self, slot: dict[str, object]) -> dict[str, str]:
        attrs = {
            "name": str(slot.get("name", "")),
            "displayName": str(slot.get("displayName", "")),
            "type": str(slot.get("slotType", "")),
            "ord": str(slot.get("ord", "")),
            "slotPath": str(slot.get("slotPath", "")),
        }
        if slot.get("parentOrd"):
            attrs["parentOrd"] = str(slot["parentOrd"])
        return attrs

    def _append_slot_metadata(self, node: ET.Element, slot: dict[str, object]) -> None:
        self._text_child(node, "id", slot.get("id"))
        if isinstance(slot.get("facets"), dict):
            self._xml_facets(node, slot["facets"])
        if isinstance(slot.get("annotations"), dict):
            self._xml_annotations(node, slot["annotations"])
        if isinstance(slot.get("actions"), list):
            self._xml_actions(node, slot["actions"])

    def _xml_slot(self, slot: dict[str, object], *, tag: str = "slot") -> ET.Element:
        node = ET.Element(tag, self._slot_xml_attrs(slot))
        self._append_slot_metadata(node, slot)
        return node

    def _station_xml(self, station: dict[str, object]) -> ET.Element:
        root = ET.Element(
            "station",
            {
                "name": str(station.get("name", "")),
                "ord": str(station.get("ord", "")),
                "version": str(station.get("version", "")),
                "vendor": str(station.get("vendor", "")),
            },
        )
        for key in ("id", "slotPath", "description", "timezone", "created", "modified", "application"):
            self._text_child(root, key, station.get(key))
        if isinstance(station.get("facets"), dict):
            self._xml_facets(root, station["facets"])
        slots_node = ET.SubElement(root, "slots")
        for slot in station.get("slots", []):
            slots_node.append(self._xml_slot(slot))
        return root

    def _navigation_item_xml(self, node: dict[str, object]) -> ET.Element:
        nav_node = self._xml_slot(node, tag="navNode")
        if isinstance(node.get("pxPageRef"), dict):
            px_ref = ET.SubElement(nav_node, "pxPageRef")
            self._text_child(px_ref, "displayName", node["pxPageRef"].get("displayName"))
            self._text_child(px_ref, "ord", node["pxPageRef"].get("ord"))
        if node.get("navOrd"):
            self._text_child(nav_node, "navOrd", node.get("navOrd"))
        children_node = ET.SubElement(nav_node, "children")
        for child in node.get("children", []):
            children_node.append(self._navigation_item_xml(child))
        return nav_node

    def _navigation_xml(self, navigation: dict[str, object]) -> ET.Element:
        root = ET.Element(
            "navigation",
            {
                "name": str(navigation.get("name", "")),
                "ord": str(navigation.get("ord", "")),
                "type": str(navigation.get("slotType", "")),
            },
        )
        self._text_child(root, "id", navigation.get("id"))
        self._text_child(root, "slotPath", navigation.get("slotPath"))
        children = ET.SubElement(root, "children")
        for child in navigation.get("children", []):
            children.append(self._navigation_item_xml(child))
        return root

    def _proxy_ext_xml(self, proxy_ext: dict[str, object]) -> ET.Element:
        proxy = ET.Element("proxyExt")
        self._text_child(proxy, "pointOrd", proxy_ext.get("pointOrd"))
        self._text_child(proxy, "slotPath", proxy_ext.get("slotPath"))
        self._text_child(proxy, "driverRef", proxy_ext.get("driverRef"))
        if isinstance(proxy_ext.get("bacnetProxyExt"), dict):
            bacnet = ET.SubElement(proxy, "bacnetProxyExt")
            self._text_child(bacnet, "objectType", proxy_ext["bacnetProxyExt"].get("objectType"))
            self._text_child(bacnet, "instance", proxy_ext["bacnetProxyExt"].get("instance"))
            self._text_child(bacnet, "deviceOrd", proxy_ext["bacnetProxyExt"].get("deviceOrd"))
        if isinstance(proxy_ext.get("modbusProxyExt"), dict):
            modbus = ET.SubElement(proxy, "modbusProxyExt")
            self._text_child(modbus, "register", proxy_ext["modbusProxyExt"].get("register"))
            self._text_child(modbus, "registerType", proxy_ext["modbusProxyExt"].get("registerType"))
            self._text_child(modbus, "deviceOrd", proxy_ext["modbusProxyExt"].get("deviceOrd"))
        return proxy

    def _point_binding_xml(self, point_binding: dict[str, object]) -> ET.Element:
        binding = ET.Element("pointBinding")
        self._text_child(binding, "ord", point_binding.get("ord"))
        self._text_child(binding, "slotPath", point_binding.get("slotPath"))
        self._text_child(binding, "navName", point_binding.get("navName"))
        return binding

    def _network_ext_xml(self, network_ext: dict[str, object]) -> ET.Element:
        network = ET.Element("networkExt")
        addresses = ET.SubElement(network, "addresses")
        for entry in network_ext.get("addresses", []):
            address = ET.SubElement(addresses, "address")
            self._text_child(address, "protocol", entry.get("protocol"))
            self._text_child(address, "host", entry.get("address"))
            self._text_child(address, "networkNumber", entry.get("networkNumber"))
            self._text_child(address, "subnetMask", entry.get("subnetMask"))
            self._text_child(address, "gateway", entry.get("gateway"))
        return network

    def _point_ref_xml(self, point_ref_data: dict[str, object]) -> ET.Element:
        point_ref = ET.Element("pointRef")
        self._text_child(point_ref, "name", point_ref_data.get("name"))
        self._text_child(point_ref, "displayName", point_ref_data.get("displayName"))
        self._text_child(point_ref, "ord", point_ref_data.get("ord"))
        self._text_child(point_ref, "slotPath", point_ref_data.get("slotPath"))
        self._text_child(point_ref, "parentOrd", point_ref_data.get("parentOrd"))
        return point_ref

    def _px_navigation_xml(self, navigation_data: dict[str, object]) -> ET.Element:
        navigation = ET.Element("navigation")
        for key, value in navigation_data.items():
            if isinstance(value, list):
                container = ET.SubElement(navigation, key)
                item_tag = "crumb" if key == "breadcrumbs" else "target"
                for item in value:
                    self._text_child(container, item_tag, item)
            else:
                self._text_child(navigation, key, value)
        return navigation

    def _range_xml(self, range_data: dict[str, object]) -> ET.Element:
        range_node = ET.Element("range")
        self._text_child(range_node, "min", range_data.get("min"))
        self._text_child(range_node, "max", range_data.get("max"))
        return range_node

    def _alarm_limits_xml(self, limits_data: dict[str, object]) -> ET.Element:
        limits = ET.Element("limits")
        self._text_child(limits, "low", limits_data.get("low"))
        self._text_child(limits, "high", limits_data.get("high"))
        self._text_child(limits, "deadband", limits_data.get("deadband"))
        return limits

    def _schedule_entries_xml(self, entries_data: dict[str, dict[str, object]]) -> ET.Element:
        entries = ET.Element("entries")
        for day, config in entries_data.items():
            day_node = ET.SubElement(entries, "day", name=day)
            self._text_child(day_node, "occupied", config.get("occupied"))
            self._text_child(day_node, "unoccupied", config.get("unoccupied"))
        return entries

    def _history_config_xml(self, history_data: dict[str, object]) -> ET.Element:
        history = ET.Element("historyConfig")
        self._text_child(history, "interval", history_data.get("interval"))
        self._text_child(history, "retention", history_data.get("retention"))
        self._text_child(history, "enabled", history_data.get("enabled"))
        return history

    def _points_xml(self, payload: list[dict[str, object]]) -> ET.Element:
        root = ET.Element("points")
        for point in payload:
            point_node = self._xml_slot(point, tag="point")
            if isinstance(point.get("proxyExt"), dict):
                point_node.append(self._proxy_ext_xml(point["proxyExt"]))
            if isinstance(point.get("pointBinding"), dict):
                point_node.append(self._point_binding_xml(point["pointBinding"]))
            if isinstance(point.get("range"), dict):
                point_node.append(self._range_xml(point["range"]))
            root.append(point_node)
        return root

    def _devices_xml(self, payload: list[dict[str, object]]) -> ET.Element:
        root = ET.Element("devices")
        for device in payload:
            device_node = self._xml_slot(device, tag="device")
            protocols = ET.SubElement(device_node, "protocols")
            for protocol in device.get("protocols", []):
                self._text_child(protocols, "protocol", protocol)
            if isinstance(device.get("networkExt"), dict):
                device_node.append(self._network_ext_xml(device["networkExt"]))
            points = ET.SubElement(device_node, "points")
            for child in device.get("children", []):
                points.append(self._point_ref_xml(child))
            root.append(device_node)
        return root

    def _alarms_xml(self, payload: list[dict[str, object]]) -> ET.Element:
        root = ET.Element("alarms")
        for alarm in payload:
            alarm_node = ET.SubElement(
                root,
                "alarmExt",
                {
                    "name": str(alarm.get("name", "")),
                    "ord": str(alarm.get("ord", "")),
                    "sourceOrd": str(alarm.get("sourceOrd", "")),
                    "type": str(alarm.get("slotType", "")),
                },
            )
            self._text_child(alarm_node, "id", alarm.get("id"))
            self._text_child(alarm_node, "priority", alarm.get("priority"))
            self._text_child(alarm_node, "ackRequired", alarm.get("ackRequired"))
            self._append_slot_metadata(
                alarm_node,
                {
                    "id": alarm.get("id"),
                    "facets": alarm.get("facets", {}),
                    "annotations": {},
                    "actions": [],
                },
            )
            alarm_node.append(self._alarm_limits_xml(alarm.get("limits", {})))
        return root

    def _schedules_xml(self, payload: list[dict[str, object]]) -> ET.Element:
        root = ET.Element("schedules")
        for schedule in payload:
            schedule_node = ET.SubElement(
                root,
                "schedule",
                {
                    "name": str(schedule.get("name", "")),
                    "ord": str(schedule.get("ord", "")),
                    "type": str(schedule.get("slotType", "")),
                },
            )
            self._append_slot_metadata(
                schedule_node,
                {
                    "id": schedule.get("id"),
                    "facets": schedule.get("facets", {}),
                    "annotations": {},
                    "actions": [],
                },
            )
            schedule_node.append(self._schedule_entries_xml(schedule.get("entries", {})))
        return root

    def _trends_xml(self, payload: list[dict[str, object]]) -> ET.Element:
        root = ET.Element("trends")
        for trend in payload:
            trend_node = ET.SubElement(
                root,
                "historyExt",
                {
                    "name": str(trend.get("name", "")),
                    "ord": str(trend.get("ord", "")),
                    "sourceOrd": str(trend.get("sourceOrd", "")),
                    "type": str(trend.get("slotType", "")),
                },
            )
            self._append_slot_metadata(
                trend_node,
                {
                    "id": trend.get("id"),
                    "facets": trend.get("facets", {}),
                    "annotations": {},
                    "actions": [],
                },
            )
            trend_node.append(self._history_config_xml(trend.get("historyConfig", {})))
        return root

    def _px_component_xml(self, component: dict[str, object]) -> ET.Element:
        node = ET.Element(
            "component",
            {
                "id": str(component.get("id", "")),
                "name": str(component.get("name", "")),
                "type": str(component.get("slotType", "")),
                "displayName": str(component.get("displayName", "")),
                "parentId": str(component.get("parentId", "")),
            },
        )
        position = ET.SubElement(node, "position")
        for key, value in component.get("position", {}).items():
            self._text_child(position, key, value)
        if isinstance(component.get("style"), dict):
            style = ET.SubElement(node, "style")
            self._xml_append_generic(style, component["style"])
        if isinstance(component.get("facets"), dict):
            self._xml_facets(node, component["facets"])
        if isinstance(component.get("annotations"), dict):
            self._xml_annotations(node, component["annotations"])
        if isinstance(component.get("navigation"), dict):
            node.append(self._px_navigation_xml(component["navigation"]))
        return node

    def _px_page_xml(self, page: dict[str, object], artifact_name: str) -> ET.Element:
        root = ET.Element(
            "pxPage",
            {
                "name": str(page.get("name", artifact_name)),
                "ord": str(page.get("ord", "")),
                "type": str(page.get("slotType", "")),
            },
        )
        for key in ("id", "displayName", "slotPath", "equipmentOrd", "navigationOrd"):
            if key in page:
                self._text_child(root, key, page.get(key))
        if isinstance(page.get("facets"), dict):
            self._xml_facets(root, page["facets"])
        if isinstance(page.get("navigation"), dict):
            root.append(self._px_navigation_xml(page["navigation"]))

        components_node = ET.SubElement(root, "components")
        root_component = page.get("components", {}).get("root", {})
        canvas = ET.SubElement(
            components_node,
            "canvas",
            {
                "id": str(root_component.get("id", "root")),
                "type": str(root_component.get("slotType", "px:CanvasPane")),
            },
        )
        children = ET.SubElement(canvas, "children")
        for component in root_component.get("children", []):
            children.append(self._px_component_xml(component))

        bindings_node = ET.SubElement(root, "bindings")
        for binding in page.get("bindings", []):
            binding_node = ET.SubElement(
                bindings_node,
                "binding",
                {
                    "id": str(binding.get("id", "")),
                    "widgetId": str(binding.get("widgetId", "")),
                    "type": str(binding.get("bindingType", "")),
                },
            )
            for key in ("label", "sourceOrd", "slotPath", "format", "targetOrd"):
                if key in binding:
                    self._text_child(binding_node, key, binding.get(key))
            if isinstance(binding.get("actions"), list):
                self._xml_actions(binding_node, binding["actions"])
        return root


def export_niagara(project: Project, output_dir: Path) -> ExportResult:
    """Convenience function to export to Niagara format."""
    exporter = NiagaraExporter(project)
    return exporter.export(output_dir)


__all__ = ["NiagaraExporter", "export_niagara"]
