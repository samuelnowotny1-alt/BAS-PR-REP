"""Graphics generator - graphics definitions, bindings, SVG/JSON output."""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from ..models import Equipment, EquipmentType, Point, PointKind, Project


class GraphicType(str, Enum):
    """Standard BAS graphic types."""

    EQUIPMENT = "equipment"          # Single equipment graphic
    SYSTEM = "system"                # Multi-equipment system graphic
    FLOOR_PLAN = "floor_plan"        # Floor plan with equipment locations
    RISER = "riser"                  # Riser diagram
    SCHEMATIC = "schematic"          # P&ID / schematic
    DASHBOARD = "dashboard"          # Summary dashboard
    ALARM = "alarm"                  # Alarm summary
    TREND = "trend"                  # Trend view


class BindingType(str, Enum):
    """Point binding types for graphics."""

    VALUE = "value"              # Current value display
    SETPOINT = "setpoint"        # Adjustable setpoint
    STATUS = "status"            # On/Off, Open/Closed status
    ALARM = "alarm"              # Alarm indicator
    TREND = "trend"              # Mini-trend sparkline
    OVERRIDE = "override"        # Operator override
    COMMAND = "command"          # Command button


@dataclass
class GraphicBinding:
    """A point binding on a graphic."""

    point_name: str
    binding_type: BindingType
    x: float  # Normalized 0-1
    y: float  # Normalized 0-1
    label: str | None = None
    format: str | None = None  # e.g., ".1f", ".0f", "on/off"
    color_map: dict | None = None  # For status/alarm colors
    min_max: tuple[float, float] | None = None  # For trends/bars


@dataclass
class GraphicElement:
    """A graphic element (symbol, text, shape)."""

    element_type: str  # rect, circle, line, text, image, symbol
    x: float
    y: float
    width: float = 0
    height: float = 0
    rotation: float = 0
    fill: str | None = None
    stroke: str | None = None
    stroke_width: float = 1
    text: str | None = None
    font_size: float = 12
    font_family: str = "Arial"
    symbol_name: str | None = None  # For predefined symbols
    point_binding: GraphicBinding | None = None
    layer: str = "default"


@dataclass
class GraphicDefinition:
    """Complete graphic definition."""

    graphic_id: str
    name: str
    graphic_type: GraphicType
    equipment_id: str | None = None
    width: int = 1200
    height: int = 800
    background: str = "white"
    elements: list[GraphicElement] = field(default_factory=list)
    bindings: list[GraphicBinding] = field(default_factory=list)
    navigation: list[str] = field(default_factory=list)  # Links to other graphics
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GraphicSection:
    section_id: str
    label: str
    fill: str
    stroke: str
    section_type: str = "process"
    width_weight: float = 1.0


class GraphicsGenerator:
    """Generates graphics definitions from project data."""

    AHU_SECTION_DETAIL_Y = {
        "outside_air": 0.5,
        "mixed_air": 0.5,
        "filter": 0.5,
        "cooling_coil": 0.46,
        "heating_coil": 0.54,
        "humidifier": 0.54,
        "supply_fan": 0.5,
        "return_fan": 0.5,
        "relief_fan": 0.5,
        "energy_recovery": 0.5,
        "discharge": 0.5,
    }

    AHU_SECTION_LIBRARY = {
        "outside_air": GraphicSection("outside_air", "OA", "#ffffff", "#455a64", "air", 1.05),
        "mixed_air": GraphicSection("mixed_air", "MA", "#eceff1", "#607d8b", "air", 1.2),
        "filter": GraphicSection("filter", "FILTER", "#e8eaf6", "#3f51b5", width_weight=0.85),
        "cooling_coil": GraphicSection("cooling_coil", "CC", "#cce5ff", "#1976d2", width_weight=1.15),
        "heating_coil": GraphicSection("heating_coil", "HC", "#ffccbc", "#ef6c00", width_weight=1.05),
        "humidifier": GraphicSection("humidifier", "HUM", "#e0f2f1", "#009688", width_weight=0.8),
        "supply_fan": GraphicSection("supply_fan", "SF", "#e3f2fd", "#1976d2", width_weight=1.0),
        "return_fan": GraphicSection("return_fan", "RF", "#fff3e0", "#ef6c00", width_weight=1.0),
        "relief_fan": GraphicSection("relief_fan", "EF", "#f3e5f5", "#7b1fa2", width_weight=0.95),
        "energy_recovery": GraphicSection("energy_recovery", "ERV", "#ede7f6", "#5e35b1", width_weight=1.2),
        "discharge": GraphicSection("discharge", "SA", "#fafafa", "#546e7a", "air", 0.9),
    }

    AHU_SECTION_ALIASES = {
        "oa": "outside_air",
        "outdoor_air": "outside_air",
        "mixing_box": "mixed_air",
        "mixed": "mixed_air",
        "filter_bank": "filter",
        "cooling": "cooling_coil",
        "cc": "cooling_coil",
        "heating": "heating_coil",
        "hc": "heating_coil",
        "hum": "humidifier",
        "sf": "supply_fan",
        "rf": "return_fan",
        "ef": "relief_fan",
        "erv": "energy_recovery",
        "sa": "discharge",
    }

    AHU_SECTION_PRESETS = {
        "Std AHU": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
        "AHU + RF": "outside_air,mixed_air,filter,cooling_coil,heating_coil,supply_fan,return_fan,discharge",
        "AHU + HUM": "outside_air,filter,cooling_coil,heating_coil,humidifier,supply_fan,discharge",
        "AHU + ERV": "outside_air,energy_recovery,filter,cooling_coil,heating_coil,supply_fan,discharge",
    }

    COMPONENT_ANCHORS = {
        "AHU": {
            "supply_temp": (0.98, 0.35),
            "discharge_temp": (0.98, 0.35),
            "mixed_temp": (0.33, 0.52),
            "return_temp": (0.98, 0.65),
            "outside_temp": (0.08, 0.05),
            "supply_fan": (0.15, 0.5),
            "return_fan": (0.85, 0.5),
            "cooling_valve": (0.5, 0.12),
            "heating_valve": (0.5, 0.88),
            "cooling_coil": (0.5, 0.22),
            "heating_coil": (0.5, 0.78),
            "outside_damper": (0.12, 0.05),
            "return_damper": (0.88, 0.05),
            "exhaust_damper": (0.88, 0.95),
            "filter": (0.25, 0.45),
            "humidity": (0.72, 0.75),
            "static_pressure": (0.96, 0.22),
            "generic_sensor": (0.05, 0.3),
            "generic_actuator": (0.95, 0.3),
            "generic_setpoint": (0.3, 0.05),
            "generic_status": (0.3, 0.95),
            "generic_alarm": (0.05, 0.95),
        },
        "RTU": {
            "supply_temp": (0.98, 0.35),
            "discharge_temp": (0.98, 0.35),
            "mixed_temp": (0.33, 0.5),
            "return_temp": (0.98, 0.65),
            "outside_temp": (0.08, 0.05),
            "supply_fan": (0.15, 0.5),
            "cooling_valve": (0.5, 0.2),
            "heating_valve": (0.5, 0.8),
            "cooling_coil": (0.5, 0.25),
            "heating_coil": (0.5, 0.75),
            "outside_damper": (0.12, 0.05),
            "return_damper": (0.88, 0.05),
            "filter": (0.25, 0.45),
            "static_pressure": (0.96, 0.22),
            "generic_sensor": (0.05, 0.3),
            "generic_actuator": (0.95, 0.3),
            "generic_setpoint": (0.3, 0.05),
            "generic_status": (0.3, 0.95),
            "generic_alarm": (0.05, 0.95),
        },
        "VAV": {
            "supply_temp": (0.85, 0.5),
            "discharge_temp": (0.85, 0.5),
            "damper": (0.25, 0.5),
            "reheat_valve": (0.55, 0.5),
            "heating_coil": (0.55, 0.5),
            "airflow": (0.75, 0.22),
            "room_temp": (0.95, 0.25),
            "generic_sensor": (0.95, 0.3),
            "generic_actuator": (0.95, 0.55),
            "generic_setpoint": (0.35, 0.05),
            "generic_status": (0.35, 0.95),
            "generic_alarm": (0.08, 0.95),
        },
    }

    COMPONENT_KEYWORDS = {
        "supply_temp": ("sat", "supply air temp", "supply temp", "discharge air temp", "dat"),
        "discharge_temp": ("dat", "discharge air temp", "leaving air temp"),
        "mixed_temp": ("mat", "mixed air temp", "mixed temp"),
        "return_temp": ("rat", "return air temp", "return temp"),
        "outside_temp": ("oat", "oa temp", "outside air temp", "outdoor air temp"),
        "supply_fan": ("sf", "supply fan"),
        "return_fan": ("rf", "return fan"),
        "cooling_valve": ("ccv", "chw valve", "cooling valve", "cool valve"),
        "heating_valve": ("hcv", "hw valve", "heating valve", "heat valve", "htg valve"),
        "reheat_valve": ("rhv", "reheat valve", "rht vlv", "rht valve", "reheat vlv"),
        "cooling_coil": ("cooling coil", "cc"),
        "heating_coil": ("heating coil", "hc", "reheat"),
        "outside_damper": ("oad", "oa damper", "outside damper"),
        "return_damper": ("rad", "ra damper", "return damper"),
        "exhaust_damper": ("ead", "ea damper", "exhaust damper", "relief damper"),
        "damper": ("dmp", "dmpr", "damper"),
        "filter": ("filter", "filt", "dp"),
        "humidity": ("hum", "humidity", "rh"),
        "static_pressure": ("sp", "static", "duct pressure"),
        "airflow": ("cfm", "flow", "airflow", "vel"),
        "room_temp": ("space temp", "room temp", "zone temp"),
    }

    @classmethod
    def normalize_ahu_section_name(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
        normalized = "_".join(part for part in normalized.split("_") if part)
        return cls.AHU_SECTION_ALIASES.get(normalized, normalized)

    @classmethod
    def parse_ahu_graphic_sections(cls, raw_value: str) -> tuple[list[str], list[str]]:
        valid: list[str] = []
        invalid: list[str] = []
        seen: set[str] = set()
        for part in raw_value.split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            normalized = cls.normalize_ahu_section_name(cleaned)
            if normalized not in cls.AHU_SECTION_LIBRARY:
                invalid.append(cleaned)
                continue
            if normalized not in seen:
                valid.append(normalized)
                seen.add(normalized)
        return valid, invalid

    @classmethod
    def ahu_section_presets(cls) -> dict[str, str]:
        return dict(cls.AHU_SECTION_PRESETS)

    # Standard symbol templates - detailed BAS equipment graphics
# Standard symbol templates - detailed BAS equipment graphics
    SYMBOLS = {
        "ahu": {"width": 200, "height": 120, "elements": [
            # AHU casing
            {"type": "rect", "x": 0.05, "y": 0.1, "width": 0.9, "height": 0.8, "fill": "#f5f5f5", "stroke": "#333", "stroke_width": 2, "layer": "casing"},
            # Supply fan (left side)
            {"type": "circle", "x": 0.15, "y": 0.5, "radius": 0.12, "fill": "#e3f2fd", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.15, "y": 0.5, "text": "SF", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            # Return fan (right side)
            {"type": "circle", "x": 0.85, "y": 0.5, "radius": 0.12, "fill": "#fff3e0", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.5, "text": "RF", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            # Cooling coil (upper middle)
            {"type": "rect", "x": 0.35, "y": 0.15, "width": 0.3, "height": 0.15, "fill": "#cce5ff", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.225, "text": "CC", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # Heating coil (lower middle)
            {"type": "rect", "x": 0.35, "y": 0.7, "width": 0.3, "height": 0.15, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.775, "text": "HC", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # OA Damper (top-left)
            {"type": "rect", "x": 0.05, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.05, "y1": 0.05, "x2": 0.2, "y2": 0.05, "stroke": "#1976d2", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.125, "y": 0.05, "text": "OA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # RA Damper (top-right)
            {"type": "rect", "x": 0.8, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.05, "x2": 0.95, "y2": 0.05, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.05, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # EA Damper (bottom-right)
            {"type": "rect", "x": 0.8, "y": 0.92, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.95, "x2": 0.95, "y2": 0.95, "stroke": "#757575", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.95, "text": "EA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Filter bank (left of cooling coil)
            {"type": "rect", "x": 0.2, "y": 0.2, "width": 0.1, "height": 0.5, "fill": "#e8eaf6", "stroke": "#3f51b5", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.25, "y": 0.45, "text": "FILT", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Humidifier (right of heating coil)
            {"type": "ellipse", "x": 0.7, "y": 0.75, "width": 0.15, "height": 0.1, "fill": "#e0f2f1", "stroke": "#009688", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.7, "y": 0.75, "text": "HUM", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Supply duct connection (right side)
            {"type": "line", "x1": 0.95, "y1": 0.35, "x2": 1.0, "y2": 0.35, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.3, "text": "SA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Return duct connection (right side)
            {"type": "line", "x1": 0.95, "y1": 0.65, "x2": 1.0, "y2": 0.65, "stroke": "#ef6c00", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.6, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Equipment name
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
        "vav": {"width": 80, "height": 60, "elements": [
            # VAV box casing
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#fff", "stroke": "#333", "stroke_width": 2, "layer": "casing"},
            # Damper
            {"type": "rect", "x": 0.2, "y": 0.35, "width": 0.1, "height": 0.3, "fill": "#e0e0e0", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.2, "y1": 0.5, "x2": 0.3, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.25, "y": 0.3, "text": "DMPR", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Reheat coil
            {"type": "rect", "x": 0.4, "y": 0.3, "width": 0.3, "height": 0.4, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "RH", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # Discharge air sensor
            {"type": "circle", "x": 0.85, "y": 0.5, "radius": 0.05, "fill": "#fff", "stroke": "#1976d2", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.5, "text": "\u2022", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Inlet duct
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.1, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 2, "layer": "piping"},
            # Outlet duct
            {"type": "line", "x1": 0.9, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.95, "y": 0.45, "text": "SA", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Equipment name
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "rtu": {"width": 180, "height": 120, "elements": [
            # RTU casing
            {"type": "rect", "x": 0.05, "y": 0.1, "width": 0.9, "height": 0.8, "fill": "#f5f5f5", "stroke": "#333", "stroke_width": 2, "layer": "casing"},
            # Supply fan
            {"type": "circle", "x": 0.15, "y": 0.5, "radius": 0.12, "fill": "#e3f2fd", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.15, "y": 0.5, "text": "SF", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            # DX Cooling coil
            {"type": "rect", "x": 0.35, "y": 0.15, "width": 0.3, "height": 0.2, "fill": "#cce5ff", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.25, "text": "DX CC", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # Gas heating section
            {"type": "rect", "x": 0.35, "y": 0.65, "width": 0.3, "height": 0.2, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.75, "text": "GAS HT", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # OA/RA dampers
            {"type": "rect", "x": 0.05, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.05, "y1": 0.05, "x2": 0.2, "y2": 0.05, "stroke": "#1976d2", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.125, "y": 0.05, "text": "OA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.8, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.05, "x2": 0.95, "y2": 0.05, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.05, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Filter
            {"type": "rect", "x": 0.2, "y": 0.2, "width": 0.1, "height": 0.5, "fill": "#e8eaf6", "stroke": "#3f51b5", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.25, "y": 0.45, "text": "FILT", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Duct connections
            {"type": "line", "x1": 0.95, "y1": 0.35, "x2": 1.0, "y2": 0.35, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.3, "text": "SA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.95, "y1": 0.65, "x2": 1.0, "y2": 0.65, "stroke": "#ef6c00", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.6, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
        "chiller": {"width": 180, "height": 100, "elements": [
            # Chiller casing
            {"type": "rect", "x": 0.05, "y": 0.15, "width": 0.9, "height": 0.7, "fill": "#e3f2fd", "stroke": "#1976d2", "stroke_width": 2, "layer": "casing"},
            # Compressor
            {"type": "ellipse", "x": 0.2, "y": 0.5, "width": 0.2, "height": 0.25, "fill": "#fff", "stroke": "#333", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.2, "y": 0.5, "text": "COMP", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # Evaporator
            {"type": "rect", "x": 0.45, "y": 0.3, "width": 0.2, "height": 0.4, "fill": "#cce5ff", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "EVAP", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # Condenser
            {"type": "rect", "x": 0.7, "y": 0.3, "width": 0.2, "height": 0.4, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.8, "y": 0.5, "text": "COND", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # Expansion valve
            {"type": "rect", "x": 0.45, "y": 0.15, "width": 0.08, "height": 0.1, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.45, "y1": 0.2, "x2": 0.53, "y2": 0.2, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.49, "y": 0.15, "text": "EXV", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Chilled water out
            {"type": "line", "x1": 0.45, "y1": 0.5, "x2": 0.0, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.0, "y": 0.45, "text": "CHWS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.55, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 1.0, "y": 0.45, "text": "CHWR", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Condenser water
            {"type": "line", "x1": 0.7, "y1": 0.2, "x2": 0.7, "y2": 0.0, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.7, "y": 0.05, "text": "CWS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.7, "y1": 0.8, "x2": 0.7, "y2": 1.0, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.7, "y": 0.95, "text": "CWR", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
        "boiler": {"width": 140, "height": 90, "elements": [
            # Boiler casing
            {"type": "rect", "x": 0.05, "y": 0.2, "width": 0.9, "height": 0.6, "fill": "#fff8e1", "stroke": "#ef6c00", "stroke_width": 2, "layer": "casing"},
            # Burner
            {"type": "ellipse", "x": 0.15, "y": 0.5, "width": 0.15, "height": 0.2, "fill": "#fff", "stroke": "#333", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.15, "y": 0.5, "text": "BURNER", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Heat exchanger
            {"type": "rect", "x": 0.4, "y": 0.3, "width": 0.3, "height": 0.4, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "HX", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            # Flue
            {"type": "rect", "x": 0.8, "y": 0.0, "width": 0.1, "height": 0.2, "fill": "#757575", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.1, "text": "FLUE", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Hot water supply/return
            {"type": "line", "x1": 0.55, "y1": 0.3, "x2": 1.0, "y2": 0.3, "stroke": "#ef6c00", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 1.0, "y": 0.25, "text": "HWS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.55, "y1": 0.7, "x2": 1.0, "y2": 0.7, "stroke": "#ef6c00", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 1.0, "y": 0.65, "text": "HWR", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Gas connection
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.15, "y2": 0.5, "stroke": "#757575", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.0, "y": 0.45, "text": "GAS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
        "pump": {"width": 60, "height": 60, "elements": [
            # Pump casing
            {"type": "circle", "x": 0.5, "y": 0.5, "radius": 0.3, "fill": "#e3f2fd", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            # Impeller
            {"type": "circle", "x": 0.5, "y": 0.5, "radius": 0.15, "fill": "#bbdefb", "stroke": "#1976d2", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.5, "text": "PMP", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            # Suction
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.2, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.1, "y": 0.45, "text": "SUC", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Discharge
            {"type": "line", "x1": 0.8, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.9, "y": 0.45, "text": "DIS", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Suction valve
            {"type": "rect", "x": 0.15, "y": 0.4, "width": 0.08, "height": 0.2, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.15, "y1": 0.5, "x2": 0.23, "y2": 0.5, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            # Discharge valve
            {"type": "rect", "x": 0.77, "y": 0.4, "width": 0.08, "height": 0.2, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.77, "y1": 0.5, "x2": 0.85, "y2": 0.5, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            # Check valve
            {"type": "line", "x1": 0.85, "y1": 0.45, "x2": 0.85, "y2": 0.55, "stroke": "#333", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.85, "y": 0.38, "text": "CV", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "cooling_tower": {"width": 100, "height": 100, "elements": [
            # Tower casing
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#e0f2f1", "stroke": "#009688", "stroke_width": 2, "layer": "casing"},
            # Fan
            {"type": "circle", "x": 0.5, "y": 0.25, "radius": 0.2, "fill": "#f3e5f5", "stroke": "#7b1fa2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.25, "text": "FAN", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            # Fill media
            {"type": "rect", "x": 0.2, "y": 0.5, "width": 0.6, "height": 0.3, "fill": "#b2dfdb", "stroke": "#009688", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.65, "text": "FILL", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # Basin
            {"type": "rect", "x": 0.15, "y": 0.85, "width": 0.7, "height": 0.08, "fill": "#cce5ff", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.89, "text": "BASIN", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # CW supply/return
            {"type": "line", "x1": 0.5, "y1": 0.0, "x2": 0.5, "y2": 0.1, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.5, "y": -0.02, "text": "CWS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.1, "y1": 0.89, "x2": 0.0, "y2": 0.89, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": -0.02, "y": 0.87, "text": "CWR", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Makeup water
            {"type": "line", "x1": 0.9, "y1": 0.89, "x2": 1.0, "y2": 0.89, "stroke": "#009688", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 1.0, "y": 0.87, "text": "MU", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Overflow
            {"type": "line", "x1": 0.1, "y1": 0.95, "x2": 0.0, "y2": 1.0, "stroke": "#757575", "stroke_width": 1, "layer": "piping"},
            {"type": "text", "x": 0.0, "y": 0.98, "text": "OF", "font_size": 6, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.98, "text": "{name}", "font_size": 10, "font_family": "Arial", "layer": "labels"},
        ]},

        # Manufacturer-specific AHU templates
        "ahu_trane": {"width": 200, "height": 120, "elements": [
            # Trane-style AHU with specific component layout
            {"type": "rect", "x": 0.05, "y": 0.1, "width": 0.9, "height": 0.8, "fill": "#e8eaf6", "stroke": "#3f51b5", "stroke_width": 2, "layer": "casing"},
            # Supply fan - Trane style (twin fans)
            {"type": "circle", "x": 0.12, "y": 0.4, "radius": 0.1, "fill": "#c5cae9", "stroke": "#3f51b5", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.12, "y": 0.4, "text": "SF1", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.12, "y": 0.6, "radius": 0.1, "fill": "#c5cae9", "stroke": "#3f51b5", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.12, "y": 0.6, "text": "SF2", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Return fan
            {"type": "circle", "x": 0.88, "y": 0.5, "radius": 0.12, "fill": "#fff3e0", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.88, "y": 0.5, "text": "RF", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            # Cooling coil (Trane dual-circuit)
            {"type": "rect", "x": 0.32, "y": 0.15, "width": 0.36, "height": 0.18, "fill": "#bbdefb", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.24, "text": "CC-1/CC-2", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Heating coil
            {"type": "rect", "x": 0.32, "y": 0.67, "width": 0.36, "height": 0.18, "fill": "#ffe0b2", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.76, "text": "HC", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            # OA/RA/EA dampers
            {"type": "rect", "x": 0.05, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.05, "y1": 0.05, "x2": 0.2, "y2": 0.05, "stroke": "#1976d2", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.125, "y": 0.05, "text": "OA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.8, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.05, "x2": 0.95, "y2": 0.05, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.05, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.8, "y": 0.92, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.95, "x2": 0.95, "y2": 0.95, "stroke": "#757575", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.95, "text": "EA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Filters (Trane - high efficiency)
            {"type": "rect", "x": 0.22, "y": 0.18, "width": 0.08, "height": 0.64, "fill": "#e8eaf6", "stroke": "#3f51b5", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.26, "y": 0.5, "text": "FILT\nMERV13", "font_size": 6, "font_family": "Arial", "layer": "labels"},
            # Humidifier
            {"type": "ellipse", "x": 0.72, "y": 0.75, "width": 0.15, "height": 0.1, "fill": "#e0f2f1", "stroke": "#009688", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.72, "y": 0.75, "text": "HUM", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            # Supply/Return connections
            {"type": "line", "x1": 0.95, "y1": 0.35, "x2": 1.0, "y2": 0.35, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.3, "text": "SA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.95, "y1": 0.65, "x2": 1.0, "y2": 0.65, "stroke": "#ef6c00", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.6, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            # Equipment name
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
        "vav_trane": {"width": 80, "height": 60, "elements": [
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#fff", "stroke": "#3f51b5", "stroke_width": 2, "layer": "casing"},
            {"type": "rect", "x": 0.2, "y": 0.35, "width": 0.1, "height": 0.3, "fill": "#c5cae9", "stroke": "#3f51b5", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.2, "y1": 0.5, "x2": 0.3, "y2": 0.5, "stroke": "#3f51b5", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.25, "y": 0.3, "text": "DMPR", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.4, "y": 0.3, "width": 0.3, "height": 0.4, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "RH", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.85, "y": 0.5, "radius": 0.05, "fill": "#fff", "stroke": "#3f51b5", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.5, "text": "•", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.1, "y2": 0.5, "stroke": "#3f51b5", "stroke_width": 2, "layer": "piping"},
            {"type": "line", "x1": 0.9, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#3f51b5", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.95, "y": 0.45, "text": "SA", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "vav_carrier": {"width": 80, "height": 60, "elements": [
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#fff", "stroke": "#e65100", "stroke_width": 2, "layer": "casing"},
            {"type": "rect", "x": 0.2, "y": 0.35, "width": 0.1, "height": 0.3, "fill": "#fff3e0", "stroke": "#e65100", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.2, "y1": 0.5, "x2": 0.3, "y2": 0.5, "stroke": "#e65100", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.25, "y": 0.3, "text": "DMPR", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.4, "y": 0.3, "width": 0.3, "height": 0.4, "fill": "#ffccbc", "stroke": "#e65100", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "RH", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.85, "y": 0.5, "radius": 0.05, "fill": "#fff", "stroke": "#e65100", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.5, "text": "•", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.1, "y2": 0.5, "stroke": "#e65100", "stroke_width": 2, "layer": "piping"},
            {"type": "line", "x1": 0.9, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#e65100", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.95, "y": 0.45, "text": "SA", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "chiller_trane": {"width": 180, "height": 100, "elements": [
            {"type": "rect", "x": 0.05, "y": 0.15, "width": 0.9, "height": 0.7, "fill": "#e8eaf6", "stroke": "#3f51b5", "stroke_width": 2, "layer": "casing"},
            {"type": "ellipse", "x": 0.2, "y": 0.5, "width": 0.2, "height": 0.25, "fill": "#c5cae9", "stroke": "#3f51b5", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.2, "y": 0.5, "text": "COMP", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.45, "y": 0.3, "width": 0.2, "height": 0.4, "fill": "#bbdefb", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "EVAP", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.7, "y": 0.3, "width": 0.2, "height": 0.4, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.8, "y": 0.5, "text": "COND", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.45, "y": 0.15, "width": 0.08, "height": 0.1, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.45, "y1": 0.2, "x2": 0.53, "y2": 0.2, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.49, "y": 0.15, "text": "EXV", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.45, "y1": 0.5, "x2": 0.0, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.0, "y": 0.45, "text": "CHWS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.55, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 1.0, "y": 0.45, "text": "CHWR", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.7, "y1": 0.2, "x2": 0.7, "y2": 0.0, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.7, "y": 0.05, "text": "CWS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.7, "y1": 0.8, "x2": 0.7, "y2": 1.0, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.7, "y": 0.95, "text": "CWR", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
        "boiler_carrier": {"width": 140, "height": 90, "elements": [
            {"type": "rect", "x": 0.05, "y": 0.2, "width": 0.9, "height": 0.6, "fill": "#fff3e0", "stroke": "#e65100", "stroke_width": 2, "layer": "casing"},
            {"type": "ellipse", "x": 0.15, "y": 0.5, "width": 0.15, "height": 0.2, "fill": "#ffe0b2", "stroke": "#e65100", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.15, "y": 0.5, "text": "BURNER", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.4, "y": 0.3, "width": 0.3, "height": 0.4, "fill": "#ffccbc", "stroke": "#e65100", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "HX", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.8, "y": 0.0, "width": 0.1, "height": 0.2, "fill": "#757575", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.1, "text": "FLUE", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.55, "y1": 0.3, "x2": 1.0, "y2": 0.3, "stroke": "#e65100", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 1.0, "y": 0.25, "text": "HWS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.55, "y1": 0.7, "x2": 1.0, "y2": 0.7, "stroke": "#e65100", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 1.0, "y": 0.65, "text": "HWR", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.15, "y2": 0.5, "stroke": "#757575", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.0, "y": 0.45, "text": "GAS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},

        "ahu_siemens": {"width": 200, "height": 120, "elements": [
            {"type": "rect", "x": 0.05, "y": 0.1, "width": 0.9, "height": 0.8, "fill": "#fce4ec", "stroke": "#c2185b", "stroke_width": 2, "layer": "casing"},
            {"type": "circle", "x": 0.12, "y": 0.4, "radius": 0.1, "fill": "#f8bbd0", "stroke": "#c2185b", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.12, "y": 0.4, "text": "SF1", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.12, "y": 0.6, "radius": 0.1, "fill": "#f8bbd0", "stroke": "#c2185b", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.12, "y": 0.6, "text": "SF2", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.88, "y": 0.5, "radius": 0.12, "fill": "#fff3e0", "stroke": "#e65100", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.88, "y": 0.5, "text": "RF", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.32, "y": 0.15, "width": 0.36, "height": 0.18, "fill": "#f8bbd0", "stroke": "#c2185b", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.24, "text": "CC-1/CC-2", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.32, "y": 0.67, "width": 0.36, "height": 0.18, "fill": "#ffe0b2", "stroke": "#e65100", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.76, "text": "HC", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.05, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.05, "y1": 0.05, "x2": 0.2, "y2": 0.05, "stroke": "#c2185b", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.125, "y": 0.05, "text": "OA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.8, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.05, "x2": 0.95, "y2": 0.05, "stroke": "#e65100", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.05, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.8, "y": 0.92, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.95, "x2": 0.95, "y2": 0.95, "stroke": "#757575", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.95, "text": "EA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.22, "y": 0.18, "width": 0.08, "height": 0.64, "fill": "#fce4ec", "stroke": "#c2185b", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.26, "y": 0.5, "text": "FILT\nMERV13", "font_size": 6, "font_family": "Arial", "layer": "labels"},
            {"type": "ellipse", "x": 0.72, "y": 0.75, "width": 0.15, "height": 0.1, "fill": "#e0f2f1", "stroke": "#009688", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.72, "y": 0.75, "text": "HUM", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.95, "y1": 0.35, "x2": 1.0, "y2": 0.35, "stroke": "#c2185b", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.3, "text": "SA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.95, "y1": 0.65, "x2": 1.0, "y2": 0.65, "stroke": "#e65100", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.6, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
        "vav_siemens": {"width": 80, "height": 60, "elements": [
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#fff", "stroke": "#c2185b", "stroke_width": 2, "layer": "casing"},
            {"type": "rect", "x": 0.2, "y": 0.35, "width": 0.1, "height": 0.3, "fill": "#f8bbd0", "stroke": "#c2185b", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.2, "y1": 0.5, "x2": 0.3, "y2": 0.5, "stroke": "#c2185b", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.25, "y": 0.3, "text": "DMPR", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.4, "y": 0.3, "width": 0.3, "height": 0.4, "fill": "#ffe0b2", "stroke": "#e65100", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "RH", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.85, "y": 0.5, "radius": 0.05, "fill": "#fff", "stroke": "#c2185b", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.5, "text": "•", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.1, "y2": 0.5, "stroke": "#c2185b", "stroke_width": 2, "layer": "piping"},
            {"type": "line", "x1": 0.9, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#c2185b", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.95, "y": 0.45, "text": "SA", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "ahu_honeywell": {"width": 200, "height": 120, "elements": [
            {"type": "rect", "x": 0.05, "y": 0.1, "width": 0.9, "height": 0.8, "fill": "#e3f2fd", "stroke": "#1565c0", "stroke_width": 2, "layer": "casing"},
            {"type": "circle", "x": 0.15, "y": 0.5, "radius": 0.12, "fill": "#bbdefb", "stroke": "#1565c0", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.15, "y": 0.5, "text": "SF", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.85, "y": 0.5, "radius": 0.12, "fill": "#fff3e0", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.5, "text": "RF", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.35, "y": 0.15, "width": 0.3, "height": 0.15, "fill": "#bbdefb", "stroke": "#1565c0", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.225, "text": "CC", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.35, "y": 0.7, "width": 0.3, "height": 0.15, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.775, "text": "HC", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.05, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.05, "y1": 0.05, "x2": 0.2, "y2": 0.05, "stroke": "#1565c0", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.125, "y": 0.05, "text": "OA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.8, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.05, "x2": 0.95, "y2": 0.05, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.05, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.8, "y": 0.92, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.95, "x2": 0.95, "y2": 0.95, "stroke": "#757575", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.95, "text": "EA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.22, "y": 0.2, "width": 0.08, "height": 0.5, "fill": "#e3f2fd", "stroke": "#1565c0", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.26, "y": 0.45, "text": "FILT", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "ellipse", "x": 0.72, "y": 0.75, "width": 0.15, "height": 0.1, "fill": "#e0f2f1", "stroke": "#009688", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.72, "y": 0.75, "text": "HUM", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.95, "y1": 0.35, "x2": 1.0, "y2": 0.35, "stroke": "#1565c0", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.3, "text": "SA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.95, "y1": 0.65, "x2": 1.0, "y2": 0.65, "stroke": "#ef6c00", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.6, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
        "vav_honeywell": {"width": 80, "height": 60, "elements": [
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#fff", "stroke": "#1565c0", "stroke_width": 2, "layer": "casing"},
            {"type": "rect", "x": 0.2, "y": 0.35, "width": 0.1, "height": 0.3, "fill": "#bbdefb", "stroke": "#1565c0", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.2, "y1": 0.5, "x2": 0.3, "y2": 0.5, "stroke": "#1565c0", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.25, "y": 0.3, "text": "DMPR", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.4, "y": 0.3, "width": 0.3, "height": 0.4, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "RH", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.85, "y": 0.5, "radius": 0.05, "fill": "#fff", "stroke": "#1565c0", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.5, "text": "•", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.1, "y2": 0.5, "stroke": "#1565c0", "stroke_width": 2, "layer": "piping"},
            {"type": "line", "x1": 0.9, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#1565c0", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.95, "y": 0.45, "text": "SA", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "rtu_aaon": {"width": 180, "height": 120, "elements": [
            {"type": "rect", "x": 0.05, "y": 0.1, "width": 0.9, "height": 0.8, "fill": "#f3e5f5", "stroke": "#7b1fa2", "stroke_width": 2, "layer": "casing"},
            {"type": "circle", "x": 0.15, "y": 0.5, "radius": 0.12, "fill": "#e1bee7", "stroke": "#7b1fa2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.15, "y": 0.5, "text": "SF", "font_size": 10, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.35, "y": 0.15, "width": 0.3, "height": 0.2, "fill": "#e1bee7", "stroke": "#7b1fa2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.25, "text": "DX CC", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.35, "y": 0.65, "width": 0.3, "height": 0.2, "fill": "#ffe0b2", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.75, "text": "GAS HT", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.05, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.05, "y1": 0.05, "x2": 0.2, "y2": 0.05, "stroke": "#7b1fa2", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.125, "y": 0.05, "text": "OA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.8, "y": 0.02, "width": 0.15, "height": 0.06, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.8, "y1": 0.05, "x2": 0.95, "y2": 0.05, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.875, "y": 0.05, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.2, "y": 0.2, "width": 0.1, "height": 0.5, "fill": "#f3e5f5", "stroke": "#7b1fa2", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.25, "y": 0.45, "text": "FILT", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.95, "y1": 0.35, "x2": 1.0, "y2": 0.35, "stroke": "#7b1fa2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.3, "text": "SA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.95, "y1": 0.65, "x2": 1.0, "y2": 0.65, "stroke": "#ef6c00", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.98, "y": 0.6, "text": "RA", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
        "vav_daikin": {"width": 80, "height": 60, "elements": [
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#fff", "stroke": "#00695c", "stroke_width": 2, "layer": "casing"},
            {"type": "rect", "x": 0.2, "y": 0.35, "width": 0.1, "height": 0.3, "fill": "#b2dfdb", "stroke": "#00695c", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.2, "y1": 0.5, "x2": 0.3, "y2": 0.5, "stroke": "#00695c", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.25, "y": 0.3, "text": "DMPR", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.4, "y": 0.3, "width": 0.3, "height": 0.4, "fill": "#ffe0b2", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "RH", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.85, "y": 0.5, "radius": 0.05, "fill": "#fff", "stroke": "#00695c", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.5, "text": "•", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.1, "y2": 0.5, "stroke": "#00695c", "stroke_width": 2, "layer": "piping"},
            {"type": "line", "x1": 0.9, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#00695c", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.95, "y": 0.45, "text": "SA", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "vav_mitsubishi": {"width": 80, "height": 60, "elements": [
            {"type": "rect", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8, "fill": "#fff", "stroke": "#c62828", "stroke_width": 2, "layer": "casing"},
            {"type": "rect", "x": 0.2, "y": 0.35, "width": 0.1, "height": 0.3, "fill": "#ffcdd2", "stroke": "#c62828", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.2, "y1": 0.5, "x2": 0.3, "y2": 0.5, "stroke": "#c62828", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.25, "y": 0.3, "text": "DMPR", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.4, "y": 0.3, "width": 0.3, "height": 0.4, "fill": "#ffe0b2", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "RH", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "circle", "x": 0.85, "y": 0.5, "radius": 0.05, "fill": "#fff", "stroke": "#c62828", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.85, "y": 0.5, "text": "•", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.0, "y1": 0.5, "x2": 0.1, "y2": 0.5, "stroke": "#c62828", "stroke_width": 2, "layer": "piping"},
            {"type": "line", "x1": 0.9, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#c62828", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.95, "y": 0.45, "text": "SA", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "chiller_york": {"width": 180, "height": 100, "elements": [
            {"type": "rect", "x": 0.05, "y": 0.15, "width": 0.9, "height": 0.7, "fill": "#e8eaf6", "stroke": "#3f51b5", "stroke_width": 2, "layer": "casing"},
            {"type": "ellipse", "x": 0.2, "y": 0.5, "width": 0.2, "height": 0.25, "fill": "#c5cae9", "stroke": "#3f51b5", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.2, "y": 0.5, "text": "COMP", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.45, "y": 0.3, "width": 0.2, "height": 0.4, "fill": "#bbdefb", "stroke": "#1976d2", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.55, "y": 0.5, "text": "EVAP", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.7, "y": 0.3, "width": 0.2, "height": 0.4, "fill": "#ffccbc", "stroke": "#ef6c00", "stroke_width": 2, "layer": "equipment"},
            {"type": "text", "x": 0.8, "y": 0.5, "text": "COND", "font_size": 9, "font_family": "Arial", "layer": "labels"},
            {"type": "rect", "x": 0.45, "y": 0.15, "width": 0.08, "height": 0.1, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.45, "y1": 0.2, "x2": 0.53, "y2": 0.2, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.49, "y": 0.15, "text": "EXV", "font_size": 7, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.45, "y1": 0.5, "x2": 0.0, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 0.0, "y": 0.45, "text": "CHWS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.55, "y1": 0.5, "x2": 1.0, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 3, "layer": "piping"},
            {"type": "text", "x": 1.0, "y": 0.45, "text": "CHWR", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.7, "y1": 0.2, "x2": 0.7, "y2": 0.0, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.7, "y": 0.05, "text": "CWS", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "line", "x1": 0.7, "y1": 0.8, "x2": 0.7, "y2": 1.0, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.7, "y": 0.95, "text": "CWR", "font_size": 8, "font_family": "Arial", "layer": "labels"},
            {"type": "text", "x": 0.5, "y": 0.95, "text": "{name}", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
"fan": {"width": 60, "height": 60, "elements": [
            {"type": "circle", "x": 0.5, "y": 0.5, "radius": 0.35, "fill": "#f3e5f5", "stroke": "#7b1fa2", "stroke_width": 2, "layer": "equipment"},
            # Fan blades
            {"type": "line", "x1": 0.5, "y1": 0.15, "x2": 0.5, "y2": 0.85, "stroke": "#7b1fa2", "stroke_width": 2, "layer": "equipment"},
            {"type": "line", "x1": 0.15, "y1": 0.5, "x2": 0.85, "y2": 0.5, "stroke": "#7b1fa2", "stroke_width": 2, "layer": "equipment"},
            {"type": "line", "x1": 0.25, "y1": 0.25, "x2": 0.75, "y2": 0.75, "stroke": "#7b1fa2", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.75, "y1": 0.25, "x2": 0.25, "y2": 0.75, "stroke": "#7b1fa2", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "damper": {"width": 40, "height": 40, "elements": [
            {"type": "rect", "x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.2, "y1": 0.5, "x2": 0.8, "y2": 0.5, "stroke": "#1976d2", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "valve": {"width": 40, "height": 40, "elements": [
            {"type": "rect", "x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "line", "x1": 0.5, "y1": 0.2, "x2": 0.5, "y2": 0.8, "stroke": "#ef6c00", "stroke_width": 2, "layer": "piping"},
            {"type": "text", "x": 0.5, "y": 0.9, "text": "{name}", "font_size": 9, "font_family": "Arial", "layer": "labels"},
        ]},
        "sensor": {"width": 30, "height": 30, "elements": [
            {"type": "circle", "x": 0.5, "y": 0.5, "radius": 0.4, "fill": "#fff", "stroke": "#333", "stroke_width": 1, "layer": "equipment"},
            {"type": "text", "x": 0.5, "y": 0.5, "text": "\u2022", "font_size": 12, "font_family": "Arial", "layer": "labels"},
        ]},
    }

    def __init__(self, project: Project):
        self.project = project
        self.graphics: dict[str, GraphicDefinition] = {}

    def generate_all(self) -> dict[str, GraphicDefinition]:
        """Generate graphics for all equipment."""
        for equip in self.project.equipment:
            self._generate_equipment_graphic(equip)

        # Generate system graphics
        self._generate_system_graphics()

        return self.graphics

    def _generate_equipment_graphic(self, equip: Equipment) -> GraphicDefinition:
        """Generate a standard equipment graphic."""
        points = self.project.get_points_for_equipment(equip.id)
        # Check for manufacturer-specific template
        manufacturer = getattr(equip, "manufacturer", None) or getattr(equip, "vendor", None)
        symbol_key = equip.type.value.lower()

        # Try manufacturer-specific template first
        if manufacturer:
            mfr_key = f"{symbol_key}_{manufacturer.lower().replace(' ', '_')}"
            if mfr_key in self.SYMBOLS:
                symbol_key = mfr_key

        # Fall back to standard template
        if symbol_key not in self.SYMBOLS:
            symbol_key = equip.type.value.lower()

        graphic = GraphicDefinition(
            graphic_id=f"graphic_{equip.id.lower()}",
            name=f"{equip.id} - {equip.type.value}",
            graphic_type=GraphicType.EQUIPMENT,
            equipment_id=equip.id,
            metadata={"equipment_type": equip.type.value, "generated_by": "BAS Assistant"},
        )

        if equip.type == EquipmentType.AHU:
            self._apply_ahu_configured_layout(graphic, equip, points)
        # Use template or generic
        elif symbol_key in self.SYMBOLS:
            self._apply_symbol_template(graphic, equip, points, symbol_key)
        else:
            self._apply_generic_template(graphic, equip, points)

        # Add standard navigation
        graphic.navigation = [
            f"graphic_{equip.id.lower()}",
            "dashboard_main",
        ]

        self.graphics[graphic.graphic_id] = graphic
        return graphic

    def _apply_symbol_template(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
        symbol_key: str,
    ) -> None:
        """Apply a symbol template to the graphic."""
        template = self.SYMBOLS[symbol_key]

        # Add symbol elements
        for elem_data in template["elements"]:
            elem = self._create_element_from_template(elem_data, equip.id)
            graphic.elements.append(elem)

        # Add point bindings around the symbol
        self._add_point_bindings(graphic, equip, points)

    def _apply_ahu_configured_layout(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
    ) -> None:
        """Build AHU graphics from an ordered section configuration."""
        sections = self._resolve_ahu_sections(equip, points)
        anchors = self._build_ahu_sections(graphic, equip, sections)
        graphic.metadata["graphic_sections"] = [section.section_id for section in sections]
        self._add_point_bindings(graphic, equip, points, anchors)

    def _resolve_ahu_sections(self, equip: Equipment, points: list[Point]) -> list[GraphicSection]:
        configured = self._configured_ahu_sections(equip)
        if configured:
            return configured

        inferred = [
            self.AHU_SECTION_LIBRARY["outside_air"],
            self.AHU_SECTION_LIBRARY["mixed_air"],
            self.AHU_SECTION_LIBRARY["filter"],
            self.AHU_SECTION_LIBRARY["cooling_coil"],
        ]
        if self._ahu_has_component(points, ("heating_valve", "heating_coil", "reheat_valve")):
            inferred.append(self.AHU_SECTION_LIBRARY["heating_coil"])
        if self._ahu_has_component(points, ("humidity",)):
            inferred.append(self.AHU_SECTION_LIBRARY["humidifier"])
        inferred.append(self.AHU_SECTION_LIBRARY["supply_fan"])
        inferred.append(self.AHU_SECTION_LIBRARY["discharge"])
        if self._ahu_has_component(points, ("return_fan",)):
            inferred.append(self.AHU_SECTION_LIBRARY["return_fan"])
        return inferred

    def _configured_ahu_sections(self, equip: Equipment) -> list[GraphicSection]:
        raw_values: list[str] = []
        if equip.template and equip.template.parameters:
            explicit = equip.template.parameters.get("graphic_sections") or equip.template.parameters.get("ahu_sections")
            if explicit:
                raw_values.extend(part.strip() for part in explicit.split(",") if part.strip())
        raw_values.extend(tag.strip().lower() for tag in equip.tags if tag.lower().startswith("section:"))
        parsed: list[GraphicSection] = []
        for raw in raw_values:
            section_name = raw.split(":", 1)[-1]
            normalized = self.normalize_ahu_section_name(section_name)
            section = self.AHU_SECTION_LIBRARY.get(normalized)
            if section and section.section_id not in {item.section_id for item in parsed}:
                parsed.append(section)
        return parsed

    def _ahu_has_component(self, points: list[Point], components: tuple[str, ...]) -> bool:
        for point in points:
            if self._classify_point_component(point, EquipmentType.AHU) in components:
                return True
        return False

    def _build_ahu_sections(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        sections: list[GraphicSection],
    ) -> dict[str, tuple[float, float]]:
        anchors = dict(self.COMPONENT_ANCHORS["AHU"])
        casing = (0.06, 0.18, 0.88, 0.6)
        x0, y0, width, height = casing
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x0,
            y=y0,
            width=width,
            height=height,
            fill="#f5f5f5",
            stroke="#333",
            stroke_width=2,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=0.5,
            y=0.9,
            text=equip.id,
            font_size=14,
            font_family="Arial",
            layer="labels",
        ))
        airflow_y = y0 + (height * 0.5)
        total_weight = sum(section.width_weight for section in sections) or 1.0
        cursor_x = x0

        for index, section in enumerate(sections):
            section_width = width * (section.width_weight / total_weight)
            sx = cursor_x
            body_x = sx + 0.008
            body_y = y0 + 0.09
            body_width = max(section_width - 0.016, 0.04)
            body_height = height - 0.18
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=body_x,
                y=body_y,
                width=body_width,
                height=body_height,
                fill=section.fill,
                stroke=section.stroke,
                stroke_width=2,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="text",
                x=sx + (section_width / 2),
                y=y0 + 0.11,
                text=section.label,
                font_size=10,
                font_family="Arial",
                layer="labels",
            ))
            if index:
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=sx,
                    y=y0 + 0.1,
                    width=0,
                    height=height - 0.2,
                    stroke="#cbd5e1",
                    stroke_width=1,
                    layer="symbol",
                ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=sx,
                y=airflow_y,
                width=section_width,
                height=0,
                stroke="#1976d2",
                stroke_width=3,
                layer="symbol",
            ))
            center_x = sx + (section_width / 2)
            anchors[section.section_id] = (center_x, y0 + (height * self.AHU_SECTION_DETAIL_Y.get(section.section_id, 0.5)))
            self._append_ahu_section_detail(
                graphic,
                section=section,
                sx=sx,
                y0=y0,
                section_width=section_width,
                height=height,
            )

            if section.section_id == "outside_air":
                anchors["outside_damper"] = (center_x, y0 - 0.02)
                anchors["outside_temp"] = (center_x - 0.04, y0 - 0.05)
            elif section.section_id == "mixed_air":
                anchors["mixed_temp"] = (center_x, y0 + 0.47)
                anchors["return_damper"] = (center_x, y0 - 0.02)
            elif section.section_id == "filter":
                anchors["filter"] = (center_x, y0 + 0.35)
                anchors["static_pressure"] = (center_x + 0.02, y0 + 0.16)
            elif section.section_id == "cooling_coil":
                anchors["cooling_coil"] = (center_x, y0 + 0.3)
                anchors["cooling_valve"] = (center_x, y0 - 0.03)
            elif section.section_id == "heating_coil":
                anchors["heating_coil"] = (center_x, y0 + 0.42)
                anchors["heating_valve"] = (center_x, y0 + height + 0.04)
            elif section.section_id == "humidifier":
                anchors["humidity"] = (center_x, y0 + 0.32)
            elif section.section_id == "supply_fan":
                anchors["supply_fan"] = (center_x, y0 + 0.3)
                anchors["status"] = (center_x, y0 + height + 0.04)
            elif section.section_id == "return_fan":
                anchors["return_fan"] = (center_x, y0 + 0.3)
                anchors["return_temp"] = (center_x + 0.04, y0 + 0.48)
            elif section.section_id == "relief_fan":
                anchors["exhaust_damper"] = (center_x, y0 + height + 0.02)
            elif section.section_id == "discharge":
                anchors["supply_temp"] = (center_x + 0.03, y0 + 0.22)
                anchors["discharge_temp"] = (center_x + 0.03, y0 + 0.22)
            cursor_x += section_width

        graphic.elements.append(GraphicElement(
            element_type="text",
            x=x0 - 0.01,
            y=airflow_y - 0.04,
            text="OA",
            font_size=9,
            font_family="Arial",
            layer="labels",
        ))
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=x0 + width + 0.02,
            y=airflow_y - 0.04,
            text="SA",
            font_size=9,
            font_family="Arial",
            layer="labels",
        ))
        anchors["generic_sensor"] = (x0 - 0.01, y0 + 0.18)
        anchors["generic_actuator"] = (x0 + width + 0.01, y0 + 0.18)
        anchors["generic_setpoint"] = (x0 + 0.18, y0 - 0.06)
        anchors["generic_status"] = (x0 + 0.18, y0 + height + 0.08)
        anchors["generic_alarm"] = (x0 - 0.01, y0 + height + 0.08)
        return anchors

    def _append_ahu_section_detail(
        self,
        graphic: GraphicDefinition,
        *,
        section: GraphicSection,
        sx: float,
        y0: float,
        section_width: float,
        height: float,
    ) -> None:
        center_x = sx + (section_width / 2)
        body_y = y0 + 0.18
        body_height = height - 0.28

        if section.section_id in {"outside_air", "mixed_air"}:
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=sx + 0.03,
                y=body_y + (body_height * 0.28),
                width=max(section_width - 0.06, 0.03),
                height=body_height * 0.44,
                stroke=section.stroke,
                stroke_width=2,
                layer="symbol",
            ))
            return

        if section.section_id == "filter":
            for offset in (0.22, 0.42, 0.62):
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=sx + (section_width * offset),
                    y=body_y + 0.02,
                    width=section_width * 0.08,
                    height=body_height - 0.04,
                    stroke=section.stroke,
                    stroke_width=2,
                    layer="symbol",
                ))
            return

        if section.section_id in {"cooling_coil", "heating_coil"}:
            for row in (0.22, 0.5, 0.78):
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=sx + 0.03,
                    y=body_y + (body_height * row),
                    width=max(section_width - 0.06, 0.03),
                    height=0,
                    stroke=section.stroke,
                    stroke_width=2,
                    layer="symbol",
                ))
            return

        if section.section_id in {"supply_fan", "return_fan", "relief_fan"}:
            fan_size = min(section_width * 0.48, height * 0.26)
            graphic.elements.append(GraphicElement(
                element_type="circle",
                x=center_x,
                y=y0 + (height * 0.5),
                width=fan_size,
                height=fan_size,
                fill="#ffffff",
                stroke=section.stroke,
                stroke_width=2,
                layer="symbol",
            ))
            return

        if section.section_id == "humidifier":
            graphic.elements.append(GraphicElement(
                element_type="ellipse",
                x=center_x,
                y=y0 + (height * 0.57),
                width=min(section_width * 0.42, 0.08),
                height=0.08,
                fill="#ffffff",
                stroke=section.stroke,
                stroke_width=2,
                layer="symbol",
            ))
            return

        if section.section_id == "energy_recovery":
            for offset in (-0.12, 0.12):
                graphic.elements.append(GraphicElement(
                    element_type="circle",
                    x=center_x + (section_width * offset),
                    y=y0 + (height * 0.5),
                    width=0.07,
                    height=0.07,
                    fill="#ffffff",
                    stroke=section.stroke,
                    stroke_width=2,
                    layer="symbol",
                ))

    def _apply_generic_template(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
    ) -> None:
        """Apply generic equipment template."""
        # Equipment box
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=0.2, y=0.2, width=0.6, height=0.6,
            fill="#f5f5f5", stroke="#333", stroke_width=2,
            layer="equipment",
        ))
        # Equipment name
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=0.5, y=0.5, text=equip.id,
            font_size=16, font_family="Arial",
            layer="labels",
        ))
        # Type label
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=0.5, y=0.7, text=equip.type.value,
            font_size=12, font_family="Arial",
            layer="labels",
        ))

        self._add_point_bindings(graphic, equip, points)

    def _create_element_from_template(self, elem_data: dict, equip_id: str) -> GraphicElement:
        """Create a GraphicElement from template data."""
        elem_type = elem_data["type"]

        if elem_type == "rect":
            return GraphicElement(
                element_type="rect",
                x=elem_data["x"], y=elem_data["y"],
                width=elem_data["width"], height=elem_data["height"],
                fill=elem_data.get("fill"), stroke=elem_data.get("stroke"),
                stroke_width=elem_data.get("stroke_width", 1),
                layer="symbol",
            )
        if elem_type == "circle":
            return GraphicElement(
                element_type="circle",
                x=elem_data["x"], y=elem_data["y"],
                width=elem_data["radius"] * 2, height=elem_data["radius"] * 2,
                fill=elem_data.get("fill"), stroke=elem_data.get("stroke"),
                stroke_width=elem_data.get("stroke_width", 1),
                layer="symbol",
            )
        if elem_type == "ellipse":
            return GraphicElement(
                element_type="ellipse",
                x=elem_data["x"], y=elem_data["y"],
                width=elem_data["width"], height=elem_data["height"],
                fill=elem_data.get("fill"), stroke=elem_data.get("stroke"),
                stroke_width=elem_data.get("stroke_width", 1),
                layer="symbol",
            )
        if elem_type == "line":
            return GraphicElement(
                element_type="line",
                x=elem_data["x1"], y=elem_data["y1"],
                width=elem_data["x2"] - elem_data["x1"],
                height=elem_data["y2"] - elem_data["y1"],
                stroke=elem_data.get("stroke", "#333"),
                stroke_width=elem_data.get("stroke_width", 1),
                layer="symbol",
            )
        if elem_type == "text":
            return GraphicElement(
                element_type="text",
                x=elem_data["x"], y=elem_data["y"],
                text=elem_data["text"].format(name=equip_id),
                font_size=elem_data.get("font_size", 12),
                font_family=elem_data.get("font_family", "Arial"),
                layer="labels",
            )
        return GraphicElement(element_type="rect", x=0, y=0, layer="symbol")

    def _add_point_bindings(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
        anchors: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        """Add point bindings near their likely physical component."""
        anchors = anchors or self.COMPONENT_ANCHORS.get(equip.type.value, {})
        fallback_counters: dict[str, int] = defaultdict(int)
        component_counters: dict[str, int] = defaultdict(int)

        for point in points:
            binding_type = self._binding_type_for_point(point)
            component = self._classify_point_component(point, equip.type)
            x, y = self._binding_position_for_point(point, component, anchors, component_counters, fallback_counters)
            graphic.bindings.append(GraphicBinding(
                point_name=point.name,
                binding_type=binding_type,
                x=x,
                y=y,
                label=self._label_for_point(point),
                format=self._binding_format_for_point(point, binding_type),
                color_map=self._color_map_for_point(point, binding_type),
                min_max=(point.range_min, point.range_max)
                if point.range_min is not None and point.range_max is not None
                else None,
            ))

    def _binding_type_for_point(self, point: Point) -> BindingType:
        if point.kind == PointKind.SETPOINT:
            return BindingType.SETPOINT
        if point.kind == PointKind.STATUS:
            return BindingType.STATUS
        if point.kind == PointKind.ALARM:
            return BindingType.ALARM
        if point.kind == PointKind.ACTUATOR and point.direction.value == "output":
            return BindingType.COMMAND
        return BindingType.VALUE

    def _label_for_point(self, point: Point) -> str:
        if point.kind == PointKind.ALARM:
            return f"ALM {point.name}"
        return point.name

    def _binding_format_for_point(self, point: Point, binding_type: BindingType) -> str | None:
        if binding_type == BindingType.STATUS:
            return "on/off"
        return self._get_format(point)

    def _color_map_for_point(self, point: Point, binding_type: BindingType) -> dict | None:
        if binding_type == BindingType.STATUS:
            return {"on": "#4caf50", "off": "#f44336", "open": "#4caf50", "closed": "#f44336"}
        if binding_type == BindingType.ALARM:
            return {"normal": "#4caf50", "alarm": "#f44336", "fault": "#ff9800"}
        return None

    def _classify_point_component(self, point: Point, equipment_type: EquipmentType) -> str | None:
        normalized = self._normalize_point_text(point)
        if equipment_type == EquipmentType.VAV and "reheat" in normalized and "valve" in normalized:
            return "reheat_valve"
        for component, keywords in self.COMPONENT_KEYWORDS.items():
            if any(keyword in normalized for keyword in keywords):
                return component
        return None

    def _normalize_point_text(self, point: Point) -> str:
        parts = [point.name, point.description or "", " ".join(point.tags)]
        normalized = " ".join(parts).lower()
        for char in "-_/()[],":
            normalized = normalized.replace(char, " ")
        return " ".join(normalized.split())

    def _binding_position_for_point(
        self,
        point: Point,
        component: str | None,
        anchors: dict[str, tuple[float, float]],
        component_counters: dict[str, int],
        fallback_counters: dict[str, int],
    ) -> tuple[float, float]:
        if component and component in anchors:
            index = component_counters[component]
            component_counters[component] += 1
            return self._spread_anchor(anchors[component], index, horizontal=False)

        fallback_key = self._fallback_anchor_key(point)
        index = fallback_counters[fallback_key]
        fallback_counters[fallback_key] += 1
        return self._spread_anchor(anchors.get(fallback_key, (0.05, 0.3)), index, horizontal=fallback_key in {"generic_setpoint", "generic_status", "generic_alarm"})

    def _fallback_anchor_key(self, point: Point) -> str:
        if point.kind == PointKind.ACTUATOR:
            return "generic_actuator"
        if point.kind == PointKind.SETPOINT:
            return "generic_setpoint"
        if point.kind == PointKind.STATUS:
            return "generic_status"
        if point.kind == PointKind.ALARM:
            return "generic_alarm"
        return "generic_sensor"

    def _spread_anchor(self, anchor: tuple[float, float], index: int, horizontal: bool) -> tuple[float, float]:
        if index == 0:
            return anchor
        step = 0.045
        offset = ((index + 1) // 2) * step
        direction = 1 if index % 2 else -1
        if horizontal:
            return (self._clamp(anchor[0] + direction * offset), self._clamp(anchor[1]))
        return (self._clamp(anchor[0]), self._clamp(anchor[1] + direction * offset))

    def _clamp(self, value: float) -> float:
        return max(0.02, min(0.98, value))

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

    def _generate_system_graphics(self) -> None:
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

        self.graphics[graphic.graphic_id] = graphic
        return graphic

    # Export methods

    def to_json(self, output_dir: Path) -> list[Path]:
        """Export graphics as JSON files."""
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []

        for graphic in self.graphics.values():
            path = output_dir / f"{graphic.graphic_id}.json"
            with open(path, "w") as f:
                json.dump(self._graphic_to_dict(graphic), f, indent=2, default=str)
            paths.append(path)

        return paths

    def to_svg(self, output_dir: Path) -> list[Path]:
        """Export graphics as SVG files (basic)."""
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []

        for graphic in self.graphics.values():
            path = output_dir / f"{graphic.graphic_id}.svg"
            svg = self._graphic_to_svg(graphic)
            with open(path, "w") as f:
                f.write(svg)
            paths.append(path)

        return paths

    def _graphic_to_dict(self, graphic: GraphicDefinition) -> dict:
        """Convert graphic to dictionary."""
        return {
            "graphic_id": graphic.graphic_id,
            "name": graphic.name,
            "type": graphic.graphic_type.value,
            "equipment_id": graphic.equipment_id,
            "width": graphic.width,
            "height": graphic.height,
            "background": graphic.background,
            "elements": [
                {
                    "type": e.element_type,
                    "x": e.x, "y": e.y,
                    "width": e.width, "height": e.height,
                    "rotation": e.rotation,
                    "fill": e.fill, "stroke": e.stroke,
                    "stroke_width": e.stroke_width,
                    "text": e.text,
                    "font_size": e.font_size,
                    "font_family": e.font_family,
                    "symbol_name": e.symbol_name,
                    "layer": e.layer,
                }
                for e in graphic.elements
            ],
            "bindings": [
                {
                    "point_name": b.point_name,
                    "binding_type": b.binding_type.value,
                    "x": b.x, "y": b.y,
                    "label": b.label,
                    "format": b.format,
                    "color_map": b.color_map,
                    "min_max": b.min_max,
                }
                for b in graphic.bindings
            ],
            "navigation": graphic.navigation,
            "metadata": graphic.metadata,
        }

    def _graphic_to_svg(self, graphic: GraphicDefinition) -> str:
        """Generate basic SVG representation."""
        lines = [
            f'<svg width="{graphic.width}" height="{graphic.height}" '
            f'viewBox="0 0 {graphic.width} {graphic.height}" '
            f'xmlns="http://www.w3.org/2000/svg">',
            f'  <rect width="100%" height="100%" fill="{graphic.background}"/>',
        ]

        # Group by layer
        layers = {}
        for elem in graphic.elements:
            layers.setdefault(elem.layer, []).append(elem)

        layer_order = ["piping", "symbol", "equipment", "labels", "bindings"]
        for layer in layer_order:
            if layer in layers:
                lines.append(f'  <g class="layer-{layer}">')
                for elem in layers[layer]:
                    lines.append(self._element_to_svg(elem, graphic.width, graphic.height))
                lines.append('  </g>')

        # Bindings as markers
        lines.append('  <g class="layer-bindings">')
        for binding in graphic.bindings:
            px = binding.x * graphic.width
            py = binding.y * graphic.height
            lines.append(
                f'    <circle cx="{px}" cy="{py}" r="8" '
                f'fill="none" stroke="#2196f3" stroke-width="2" '
                f'data-point="{binding.point_name}" data-type="{binding.binding_type.value}"/>'
            )
            if binding.label:
                lines.append(
                    f'    <text x="{px + 12}" y="{py + 4}" '
                    f'font-size="10" fill="#333">{binding.label}</text>'
                )
        lines.append('  </g>')

        lines.append('</svg>')
        return "\n".join(lines)

    def _element_to_svg(self, elem: GraphicElement, width: int, height: int) -> str:
        """Convert element to SVG."""
        px = elem.x * width
        py = elem.y * height
        pw = elem.width * width
        ph = elem.height * height

        if elem.element_type == "rect":
            return (f'    <rect x="{px}" y="{py}" width="{pw}" height="{ph}" '
                    f'fill="{elem.fill or "none"}" stroke="{elem.stroke or "none"}" '
                    f'stroke-width="{elem.stroke_width}"/>')
        if elem.element_type == "circle":
            r = pw / 2
            return (f'    <circle cx="{px}" cy="{py}" r="{r}" '
                    f'fill="{elem.fill or "none"}" stroke="{elem.stroke or "none"}" '
                    f'stroke-width="{elem.stroke_width}"/>')
        if elem.element_type == "ellipse":
            rx = pw / 2
            ry = ph / 2
            return (f'    <ellipse cx="{px}" cy="{py}" rx="{rx}" ry="{ry}" '
                    f'fill="{elem.fill or "none"}" stroke="{elem.stroke or "none"}" '
                    f'stroke-width="{elem.stroke_width}"/>')
        if elem.element_type == "line":
            x2 = px + pw
            y2 = py + ph
            return (f'    <line x1="{px}" y1="{py}" x2="{x2}" y2="{y2}" '
                    f'stroke="{elem.stroke or "black"}" stroke-width="{elem.stroke_width}"/>')
        if elem.element_type == "text":
            return (f'    <text x="{px}" y="{py}" '
                    f'font-size="{elem.font_size}" font-family="{elem.font_family}" '
                    f'text-anchor="middle" dominant-baseline="middle">{elem.text}</text>')
        return ""

    def to_niagara_json(self, output_path: Path) -> Path:
        """Export graphics in Niagara-compatible JSON format."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Niagara PX page format (simplified)
        niagara_pages = []
        for graphic in self.graphics.values():
            page = {
                "name": graphic.graphic_id,
                "title": graphic.name,
                "width": graphic.width,
                "height": graphic.height,
                "background": graphic.background,
                "components": [],
                "bindings": [],
            }

            # Convert elements to Niagara components
            for elem in graphic.elements:
                comp = {
                    "type": self._element_to_niagara_type(elem),
                    "x": int(elem.x * graphic.width),
                    "y": int(elem.y * graphic.height),
                    "width": int(elem.width * graphic.width),
                    "height": int(elem.height * graphic.height),
                }
                if elem.text:
                    comp["text"] = elem.text
                if elem.fill:
                    comp["background"] = elem.fill
                if elem.stroke:
                    comp["borderColor"] = elem.stroke
                page["components"].append(comp)

            # Convert bindings
            for binding in graphic.bindings:
                page["bindings"].append({
                    "point": binding.point_name,
                    "type": binding.binding_type.value,
                    "x": int(binding.x * graphic.width),
                    "y": int(binding.y * graphic.height),
                    "format": binding.format,
                })

            niagara_pages.append(page)

        with open(output_path, "w") as f:
            json.dump({"pages": niagara_pages}, f, indent=2)

        return output_path

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


def generate_graphics(project: Project, output_dir: Path) -> dict:
    """Convenience function to generate all graphics outputs."""
    generator = GraphicsGenerator(project)
    generator.generate_all()

    return {
        "json": generator.to_json(output_dir / "graphics_json"),
        "svg": generator.to_svg(output_dir / "graphics_svg"),
        "niagara": generator.to_niagara_json(output_dir / "graphics_niagara.json"),
    }



    def _graphic_to_niagara_px(self, graphic: GraphicDefinition) -> dict:
        """Convert graphic to proper Niagara PX page format (.ord/.px structure)."""
        # Build components with proper Niagara structure
        components = []

        for elem in graphic.elements:
            x = int(elem.x * graphic.width) if elem.x <= 1 else int(elem.x)
            y = int(elem.y * graphic.height) if elem.y <= 1 else int(elem.y)
            w = int(elem.width * graphic.width) if elem.width <= 1 else int(elem.width)
            h = int(elem.height * graphic.height) if elem.height <= 1 else int(elem.height)

            comp = {
                "ord": f"px:{graphic.graphic_id}:{elem.element_type}_{id(elem)}",
                "type": self._element_to_niagara_type(elem),
                "x": x, "y": y,
                "width": w, "height": h,
                "background": elem.fill or "#ffffff",
                "borderColor": elem.stroke or "#000000",
                "borderWidth": elem.stroke_width or 1,
                "slots": {}
            }

            if elem.element_type == "text" and elem.text:
                comp["slots"]["text"] = {
                    "value": elem.text,
                    "fontSize": elem.font_size or 12,
                    "fontFamily": elem.font_family or "Arial"
                }

            components.append(comp)

        # Add bindings as point components
        for binding in graphic.bindings:
            bx = int(binding.x * graphic.width)
            by = int(binding.y * graphic.height)

            comp = {
                "ord": f"px:{graphic.graphic_id}:binding_{binding.point_name}",
                "type": "point",
                "x": bx, "y": by,
                "width": 24, "height": 24,
                "background": "#2196f3",
                "borderColor": "#1976d2",
                "slots": {
                    "pointName": {"value": binding.point_name},
                    "pointType": {"value": binding.binding_type.value},
                    "format": {"value": binding.format},
                    "label": {"value": binding.label or binding.point_name}
                }
            }

            if binding.color_map:
                comp["slots"]["colorMap"] = {"value": binding.color_map}

            components.append(comp)

        # Build PX page with proper Niagara structure
        page = {
            "ord": f"px:{graphic.graphic_id}",
            "name": graphic.graphic_id,
            "displayName": graphic.name,
            "width": graphic.width,
            "height": graphic.height,
            "backgroundColor": graphic.background,
            "components": components,
            "navigation": graphic.navigation,
            "metadata": graphic.metadata,
            "facets": {
                "displayName": {"value": graphic.name, "type": "String"},
                "description": {"value": f"BAS Assistant generated: {graphic.metadata.get('equipment_type', 'Equipment')}", "type": "String"}
            }
        }

        return page

    def to_niagara_px_json(self, output_dir: Path) -> Path:
        """Export graphics as proper Niagara PX JSON format."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "graphics_px.json"

        pages = []
        for graphic in self.graphics.values():
            pages.append(self._graphic_to_niagara_px(graphic))

        px_data = {
            "version": "4.12",
            "timestamp": datetime.now().isoformat(),
            "generator": "BAS Assistant",
            "pages": pages
        }

        with open(path, "w") as f:
            json.dump(px_data, f, indent=2, default=str)

        return path


__all__ = [
    "BindingType",
    "GraphicBinding",
    "GraphicDefinition",
    "GraphicElement",
    "GraphicType",
    "GraphicsGenerator",
    "generate_graphics",
]
