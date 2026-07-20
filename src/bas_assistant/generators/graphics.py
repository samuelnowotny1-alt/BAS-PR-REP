"""Graphics generator - graphics definitions, bindings, SVG/JSON output."""

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from html import escape
from pathlib import Path

from ..models import Equipment, EquipmentType, Point, PointKind, Project, default_isometric_asset_library
from ..validation import ValidationEngine


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
    css_class: str | None = None


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
        "prefilter": 0.5,
        "filter": 0.5,
        "cooling_coil": 0.46,
        "heating_coil": 0.54,
        "uv": 0.52,
        "humidifier": 0.54,
        "supply_fan": 0.5,
        "return_fan": 0.5,
        "relief_fan": 0.5,
        "energy_recovery": 0.5,
        "sound_attenuator": 0.5,
        "discharge": 0.5,
    }

    AHU_SECTION_LIBRARY = {
        "outside_air": GraphicSection("outside_air", "OA", "#ffffff", "#455a64", "air", 1.05),
        "mixed_air": GraphicSection("mixed_air", "MA", "#eceff1", "#607d8b", "air", 1.2),
        "prefilter": GraphicSection("prefilter", "PREFILT", "#eef2ff", "#6366f1", width_weight=0.72),
        "filter": GraphicSection("filter", "FILTER", "#e8eaf6", "#3f51b5", width_weight=0.85),
        "cooling_coil": GraphicSection("cooling_coil", "CC", "#cce5ff", "#1976d2", width_weight=1.15),
        "heating_coil": GraphicSection("heating_coil", "HC", "#ffccbc", "#ef6c00", width_weight=1.05),
        "uv": GraphicSection("uv", "UV", "#ede9fe", "#7c3aed", width_weight=0.72),
        "humidifier": GraphicSection("humidifier", "HUM", "#e0f2f1", "#009688", width_weight=0.8),
        "supply_fan": GraphicSection("supply_fan", "SF", "#e3f2fd", "#1976d2", width_weight=1.0),
        "return_fan": GraphicSection("return_fan", "RF", "#fff3e0", "#ef6c00", width_weight=1.0),
        "relief_fan": GraphicSection("relief_fan", "EF", "#f3e5f5", "#7b1fa2", width_weight=0.95),
        "energy_recovery": GraphicSection("energy_recovery", "ERV", "#ede7f6", "#5e35b1", width_weight=1.2),
        "sound_attenuator": GraphicSection("sound_attenuator", "SIL", "#eceff1", "#64748b", width_weight=0.95),
        "discharge": GraphicSection("discharge", "SA", "#fafafa", "#546e7a", "air", 0.9),
    }

    AHU_SECTION_ALIASES = {
        "oa": "outside_air",
        "outdoor_air": "outside_air",
        "mixing_box": "mixed_air",
        "mixed": "mixed_air",
        "pre_filter": "prefilter",
        "prefilter_bank": "prefilter",
        "pre_filter_bank": "prefilter",
        "filter_bank": "filter",
        "cooling": "cooling_coil",
        "cc": "cooling_coil",
        "heating": "heating_coil",
        "hc": "heating_coil",
        "uv_lights": "uv",
        "uv_c": "uv",
        "uvc": "uv",
        "hum": "humidifier",
        "sf": "supply_fan",
        "rf": "return_fan",
        "ef": "relief_fan",
        "erv": "energy_recovery",
        "silencer": "sound_attenuator",
        "attenuator": "sound_attenuator",
        "sound_trap": "sound_attenuator",
        "sa": "discharge",
    }

    AHU_SECTION_PRESETS = {
        "Std AHU": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
        "AHU + RF": "outside_air,mixed_air,filter,cooling_coil,heating_coil,supply_fan,return_fan,discharge",
        "AHU + HUM": "outside_air,filter,cooling_coil,heating_coil,humidifier,supply_fan,discharge",
        "AHU + ERV": "outside_air,energy_recovery,filter,cooling_coil,heating_coil,supply_fan,discharge",
        "AHU + IAQ": "outside_air,prefilter,filter,uv,cooling_coil,heating_coil,sound_attenuator,supply_fan,discharge",
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
        "supply_temp": (
            "sat",
            "supply air temp",
            "supply temp",
            "leaving water temp",
            "lwt",
            "supply water temp",
            "supply water",
            "chws",
            "chw supply",
            "hws",
            "hw supply",
            "cws",
            "cw supply",
        ),
        "discharge_temp": ("dat", "discharge air temp", "leaving air temp", "lat"),
        "mixed_temp": ("mat", "mixed air temp", "mixed temp"),
        "return_temp": (
            "rat",
            "return air temp",
            "return temp",
            "entering water temp",
            "ewt",
            "return water temp",
            "chwr",
            "chw return",
            "hwr",
            "hw return",
            "cwr",
            "cw return",
        ),
        "outside_temp": ("oat", "oa temp", "outside air temp", "outdoor air temp"),
        "supply_fan": ("sf", "supply fan", "supply blower", "blower", "fan proof", "fan speed", "vfd speed"),
        "return_fan": ("rf", "return fan", "return blower"),
        "cooling_valve": ("ccv", "chw valve", "cooling valve", "cool valve"),
        "heating_valve": ("hcv", "hw valve", "heating valve", "heat valve", "htg valve"),
        "reheat_valve": ("rhv", "reheat valve", "rht vlv", "rht valve", "reheat vlv"),
        "cooling_coil": ("cooling coil", "cc"),
        "heating_coil": ("heating coil", "hc", "reheat"),
        "outside_damper": ("oad", "oa damper", "outside damper"),
        "return_damper": ("rad", "ra damper", "return damper"),
        "exhaust_damper": ("ead", "ea damper", "exhaust damper", "relief damper"),
        "damper": ("dmp", "dmpr", "damper"),
        "filter": ("filter", "filt", "flt", "dirty filter"),
        "humidity": ("hum", "humidity", "rh"),
        "static_pressure": ("sp", "static", "duct pressure", "differential pressure", "diff pressure", "building static", "pump dp", "head pressure"),
        "airflow": ("cfm", "flow", "airflow", "vel"),
        "room_temp": ("space temp", "room temp", "zone temp"),
        "uv": ("uv", "uv c", "uvc", "ultraviolet"),
        "energy_recovery": ("energy wheel", "wheel", "enthalpy wheel", "heat wheel", "erv", "energy recovery"),
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

    def _section_mentions(self, points: list[Point], phrases: tuple[str, ...]) -> bool:
        lowered_phrases = tuple(phrase.lower() for phrase in phrases)
        for point in points:
            normalized = self._normalize_point_text(point)
            if any(phrase in normalized for phrase in lowered_phrases):
                return True
        return False

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
        self.asset_library = {asset.asset_id: asset for asset in default_isometric_asset_library()}

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
        elif equip.type == EquipmentType.RTU:
            self._apply_rtu_isometric_layout(graphic, equip, points)
        elif equip.type == EquipmentType.VAV:
            self._apply_vav_isometric_layout(graphic, equip, points)
        elif equip.type in {EquipmentType.CHILLER, EquipmentType.BOILER, EquipmentType.COOLING_TOWER, EquipmentType.PUMP_HW, EquipmentType.PUMP_CHW, EquipmentType.PUMP_CW}:
            self._apply_plant_isometric_layout(graphic, equip, points)
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

        self._finalize_graphic_confidence(graphic, equip, points)
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
        configured_sections = self._configured_ahu_sections(equip)
        sections = configured_sections or self._resolve_ahu_sections(equip, points)
        anchors = self._build_ahu_sections(graphic, equip, sections, points)
        graphic.metadata["graphic_sections"] = [section.section_id for section in sections]
        self._record_graphics_inference(
            graphic,
            key="graphic_sections",
            value=list(graphic.metadata["graphic_sections"]),
            source="explicit_template" if configured_sections else "point_inference",
            confidence=0.98 if configured_sections else 0.76,
            evidence=[section.section_id for section in sections],
        )
        self._add_point_bindings(graphic, equip, points, anchors)

    def _apply_vav_isometric_layout(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
    ) -> None:
        anchors = dict(self.COMPONENT_ANCHORS["VAV"])
        asset_id = "vav_reheat_terminal"
        self._record_asset_placement(
            graphic,
            asset_id=asset_id,
            x=0.14,
            y=0.26,
            width=0.7,
            height=0.34,
            role="primary_equipment",
            equipment_id=equip.id,
        )
        self._append_isometric_vav_asset(
            graphic,
            x=0.14,
            y=0.26,
            width=0.7,
            height=0.34,
        )
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=0.5,
            y=0.77,
            text=equip.id,
            font_size=14,
            font_family="Arial",
            layer="labels",
        ))
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=0.19,
            y=0.54,
            text="SA IN",
            font_size=8,
            font_family="Arial",
            layer="labels",
        ))
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=0.79,
            y=0.54,
            text="SA OUT",
            font_size=8,
            font_family="Arial",
            layer="labels",
        ))
        anchors["damper"] = (0.32, 0.43)
        anchors["reheat_valve"] = (0.56, 0.43)
        anchors["heating_coil"] = (0.66, 0.43)
        anchors["discharge_temp"] = (0.84, 0.43)
        anchors["supply_temp"] = (0.84, 0.43)
        anchors["airflow"] = (0.74, 0.28)
        self._add_point_bindings(graphic, equip, points, anchors)

    def _apply_rtu_isometric_layout(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
    ) -> None:
        sections = [
            self.AHU_SECTION_LIBRARY["outside_air"],
            self.AHU_SECTION_LIBRARY["filter"],
            self.AHU_SECTION_LIBRARY["cooling_coil"],
            self.AHU_SECTION_LIBRARY["heating_coil"],
            self.AHU_SECTION_LIBRARY["supply_fan"],
            self.AHU_SECTION_LIBRARY["discharge"],
        ]
        anchors = self._build_ahu_sections(graphic, equip, sections, points)
        graphic.metadata["graphic_sections"] = [section.section_id for section in sections]
        graphic.metadata["equipment_variant"] = "packaged_rooftop"
        self._record_graphics_inference(
            graphic,
            key="equipment_variant",
            value="packaged_rooftop",
            source="equipment_type_default",
            confidence=0.95,
            evidence=[equip.type.value],
        )
        graphic.metadata.setdefault("asset_placements", [])
        graphic.metadata["asset_placements"][0]["asset_id"] = "rtu_packaged_rooftop"
        self._record_asset_placement(
            graphic,
            asset_id="supply_fan_scroll",
            x=0.68,
            y=0.04,
            width=0.1,
            height=0.12,
            role="condenser_fan",
            equipment_id=equip.id,
        )
        self._record_asset_placement(
            graphic,
            asset_id="supply_fan_scroll",
            x=0.8,
            y=0.04,
            width=0.1,
            height=0.12,
            role="condenser_fan",
            equipment_id=equip.id,
        )
        self._append_fan_symbol(graphic, x=0.73, y=0.095, size=0.09, stroke="#475569")
        self._append_fan_symbol(graphic, x=0.85, y=0.095, size=0.09, stroke="#475569")
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=0.79,
            y=0.03,
            text="COND FANS",
            font_size=8,
            font_family="Arial",
            layer="labels",
        ))
        self._add_point_bindings(graphic, equip, points, anchors)

    def _apply_plant_isometric_layout(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
    ) -> None:
        asset_id, source, confidence, evidence = self._plant_asset_id(equip, points)
        graphic.metadata["equipment_variant"] = asset_id
        self._record_graphics_inference(
            graphic,
            key="equipment_variant",
            value=asset_id,
            source=source,
            confidence=confidence,
            evidence=evidence,
        )
        anchors = self._build_plant_scene(graphic, equip, points, asset_id=asset_id)
        self._add_point_bindings(graphic, equip, points, anchors)

    def _plant_asset_id(self, equip: Equipment, points: list[Point]) -> tuple[str, str, float, list[str]]:
        subtype = (equip.subtype or "").lower()
        tags = " ".join(tag.lower() for tag in equip.tags)
        point_text = " ".join(self._normalize_point_text(point) for point in points)
        source = " ".join(part for part in (subtype, tags, point_text) if part)

        if equip.type == EquipmentType.CHILLER:
            if any(phrase in source for phrase in ("water cooled", "water-cooled", "centrifugal", "condenser water", "cw supply", "cw return")):
                return "chiller_centrifugal_water_cooled", "subtype_or_point_inference", 0.88, ["water cooled", "centrifugal", "cw supply/cw return"]
            return "chiller_air_cooled", "equipment_type_default", 0.68, ["no water-side evidence"]
        if equip.type == EquipmentType.BOILER:
            if any(phrase in source for phrase in ("firetube", "fire tube", "scotch marine", "scotch-marine", "burner management")):
                return "boiler_firetube", "subtype_or_point_inference", 0.86, ["firetube", "burner management"]
            return "boiler_condensing", "equipment_type_default", 0.7, ["no firetube evidence"]
        if equip.type in {EquipmentType.PUMP_HW, EquipmentType.PUMP_CHW, EquipmentType.PUMP_CW}:
            if any(phrase in source for phrase in ("vertical inline", "vertical-inline", "in line", "inline pump")):
                return "pump_vertical_inline", "subtype_or_tag_inference", 0.84, ["vertical inline"]
            return "pump_end_suction", "equipment_type_default", 0.7, ["no vertical-inline evidence"]
        if equip.type == EquipmentType.COOLING_TOWER:
            if any(phrase in source for phrase in ("induced draft", "induced-draft", "counterflow", "cell fan")):
                return "cooling_tower_induced_draft", "subtype_or_point_inference", 0.83, ["induced draft", "counterflow", "cell fan"]
            return "cooling_tower_open_cell", "equipment_type_default", 0.68, ["no induced-draft evidence"]
        return "pump_end_suction", "fallback_default", 0.5, ["fallback"]

    def _resolve_ahu_sections(self, equip: Equipment, points: list[Point]) -> list[GraphicSection]:
        configured = self._configured_ahu_sections(equip)
        if configured:
            return configured

        inferred = [self.AHU_SECTION_LIBRARY["outside_air"]]
        if self._ahu_has_component(points, ("mixed_temp", "return_damper", "return_temp")) or self._section_mentions(
            points,
            ("mixed air", "mixing box", "economizer", "return air", "relief air"),
        ):
            inferred.append(self.AHU_SECTION_LIBRARY["mixed_air"])
        if self._section_mentions(points, ("prefilter", "pre filter", "merv 8", "merv8", "merv 11", "merv11")):
            inferred.append(self.AHU_SECTION_LIBRARY["prefilter"])
        inferred.extend([
            self.AHU_SECTION_LIBRARY["filter"],
            self.AHU_SECTION_LIBRARY["cooling_coil"],
        ])
        if self._ahu_has_component(points, ("heating_valve", "heating_coil", "reheat_valve")):
            inferred.append(self.AHU_SECTION_LIBRARY["heating_coil"])
        if self._section_mentions(points, ("uv", "uv c", "uvc", "ultraviolet", "irradiance")):
            inferred.append(self.AHU_SECTION_LIBRARY["uv"])
        if self._ahu_has_component(points, ("humidity",)):
            inferred.append(self.AHU_SECTION_LIBRARY["humidifier"])
        inferred.append(self.AHU_SECTION_LIBRARY["supply_fan"])
        if self._section_mentions(points, ("silencer", "attenuator", "sound trap", "nc level")):
            inferred.append(self.AHU_SECTION_LIBRARY["sound_attenuator"])
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

    def _equipment_graphic_param(self, equip: Equipment, key: str) -> str:
        if equip.template and equip.template.parameters:
            return str(equip.template.parameters.get(key) or "").strip()
        return ""

    def _duct_profile(self, equip: Equipment) -> str:
        return self._infer_duct_profile(equip)[0]

    def _infer_duct_profile(self, equip: Equipment) -> tuple[str, str, float, list[str]]:
        explicit = self._equipment_graphic_param(equip, "duct_profile")
        if explicit:
            return explicit, "explicit_template", 0.99, [explicit]
        source_text = " ".join(
            part for part in [
                (equip.subtype or "").lower(),
                " ".join(tag.lower() for tag in equip.tags),
                self._equipment_graphic_param(equip, "graphics_model_family").lower(),
                self._equipment_graphic_param(equip, "duct_source").lower(),
                (equip.notes or "").lower(),
            ] if part
        )
        if any(phrase in source_text for phrase in ("vertical upflow", "upflow", "discharge up")):
            return "vertical_upflow", "subtype_or_tag_inference", 0.86, ["vertical upflow"]
        if any(phrase in source_text for phrase in ("vertical downflow", "downflow", "discharge down")):
            return "vertical_downflow", "subtype_or_tag_inference", 0.86, ["vertical downflow"]
        if any(phrase in source_text for phrase in ("horizontal left", "left discharge", "discharge left")):
            return "horizontal_left", "subtype_or_tag_inference", 0.82, ["horizontal left"]
        if equip.type == EquipmentType.RTU:
            return "horizontal_right", "equipment_type_default", 0.9, ["RTU default"]
        if any(phrase in source_text for phrase in ("horizontal right", "right discharge", "draw through", "draw-through")):
            return "draw_through_horizontal", "subtype_or_tag_inference", 0.78, ["horizontal right/draw-through"]
        return "draw_through_horizontal", "fallback_default", 0.62, ["no duct profile evidence"]

    def _duct_profile_metadata(self, equip: Equipment) -> dict[str, str]:
        return {
            "duct_profile": self._duct_profile(equip),
            "graphics_manufacturer": self._equipment_graphic_param(equip, "graphics_manufacturer"),
            "graphics_model_family": self._equipment_graphic_param(equip, "graphics_model_family"),
            "duct_source": self._equipment_graphic_param(equip, "duct_source"),
            "public_reference": self._equipment_graphic_param(equip, "public_reference"),
        }

    def _build_ahu_sections(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        sections: list[GraphicSection],
        points: list[Point],
    ) -> dict[str, tuple[float, float]]:
        anchors = dict(self.COMPONENT_ANCHORS["AHU"])
        casing = (0.06, 0.18, 0.88, 0.6)
        x0, y0, width, height = casing
        airflow_y = y0 + (height * 0.5)
        duct_profile, duct_profile_source, duct_profile_confidence, duct_profile_evidence = self._infer_duct_profile(equip)
        duct_metadata = {
            key: value
            for key, value in self._duct_profile_metadata(equip).items()
            if value
        }
        self._record_asset_placement(
            graphic,
            asset_id="ahu_drawthrough_doubledeck",
            x=x0,
            y=y0,
            width=width,
            height=height,
            role="primary_equipment",
            equipment_id=equip.id,
            metadata={"sections": [section.section_id for section in sections], **duct_metadata},
        )
        graphic.metadata["duct_profile"] = duct_profile
        graphic.metadata["duct_source"] = duct_metadata.get("duct_source", "")
        graphic.metadata["graphics_model_family"] = duct_metadata.get("graphics_model_family", "")
        self._record_graphics_inference(
            graphic,
            key="duct_profile",
            value=duct_profile,
            source=duct_profile_source,
            confidence=duct_profile_confidence,
            evidence=duct_profile_evidence,
        )
        if duct_profile in {"vertical_upflow", "vertical_downflow"}:
            discharge_x = x0 + (width * 0.42)
            discharge_y = y0 - 0.09 if duct_profile == "vertical_upflow" else y0 + height
            discharge_h = 0.09
            self._record_asset_placement(
                graphic,
                asset_id="rectangular_supply_duct",
                x=discharge_x,
                y=discharge_y,
                width=width * 0.16,
                height=discharge_h,
                role="duct_discharge",
                equipment_id=equip.id,
                metadata={"orientation": "vertical", "direction": "up" if duct_profile == "vertical_upflow" else "down"},
            )
        else:
            discharge_left = duct_profile == "horizontal_left"
            discharge_x = x0 - 0.05 if discharge_left else x0 + width
            self._record_asset_placement(
                graphic,
                asset_id="rectangular_supply_duct",
                x=discharge_x,
                y=airflow_y - 0.09,
                width=0.05,
                height=0.18,
                role="duct_discharge",
                equipment_id=equip.id,
                metadata={"orientation": "horizontal", "direction": "left" if discharge_left else "right"},
            )
        self._record_asset_placement(
            graphic,
            asset_id="rectangular_supply_duct",
            x=x0 + 0.025,
            y=airflow_y - 0.07,
            width=width - 0.05,
            height=0.14,
            role="internal_supply_path",
            equipment_id=equip.id,
            metadata={"duct_profile": duct_profile},
        )
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x0,
            y=y0,
            width=width,
            height=height,
            fill="url(#equipment-shell-gradient)",
            stroke="#5b5b57",
            stroke_width=2.2,
            layer="symbol",
            css_class="equipment-shell",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x0 + 0.01,
            y=y0 + 0.02,
            width=width - 0.02,
            height=height - 0.04,
            fill="url(#equipment-face-gradient)",
            stroke="#9aa0a6",
            stroke_width=1,
            layer="symbol",
            css_class="equipment-face",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x0 + 0.018,
            y=y0 + 0.045,
            width=width - 0.036,
            height=0.05,
            fill="url(#equipment-topcap-gradient)",
            stroke="none",
            stroke_width=0,
            layer="symbol",
            css_class="equipment-topcap",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x0 + 0.025,
            y=airflow_y - 0.07,
            width=width - 0.05,
            height=0.14,
            fill="url(#duct-body-gradient)",
            stroke="#6b7280",
            stroke_width=1.2,
            layer="symbol",
            css_class="duct-shell",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x0 + 0.035,
            y=airflow_y - 0.048,
            width=width - 0.07,
            height=0.096,
            fill="url(#duct-liner-gradient)",
            stroke="#9ca3af",
            stroke_width=0.8,
            layer="symbol",
            css_class="duct-liner",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x0,
            y=y0 + 0.03,
            width=width,
            height=0,
            stroke="#f8fafc",
            stroke_width=1.2,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x0,
            y=y0 + height - 0.03,
            width=width,
            height=0,
            stroke="#7b7f84",
            stroke_width=1.2,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x0 + 0.01,
            y=y0 + height - 0.045,
            width=width - 0.02,
            height=0.025,
            fill="url(#equipment-base-gradient)",
            stroke="none",
            stroke_width=0,
            layer="symbol",
            css_class="equipment-base",
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
        total_weight = sum(section.width_weight for section in sections) or 1.0
        cursor_x = x0
        intake_on_left = duct_profile not in {"horizontal_left"}
        if intake_on_left:
            self._append_ahu_duct_stub(graphic, x=x0 - 0.045, y=airflow_y - 0.09, width=0.045, height=0.18, louver=True)
        else:
            self._append_ahu_duct_stub(graphic, x=x0 + width, y=airflow_y - 0.09, width=0.05, height=0.18, louver=True)

        if duct_profile == "vertical_upflow":
            self._append_ahu_duct_stub(graphic, x=x0 + (width * 0.42), y=y0 - 0.09, width=width * 0.16, height=0.09, louver=False)
        elif duct_profile == "vertical_downflow":
            self._append_ahu_duct_stub(graphic, x=x0 + (width * 0.42), y=y0 + height, width=width * 0.16, height=0.09, louver=False)
        elif duct_profile == "horizontal_left":
            self._append_ahu_duct_stub(graphic, x=x0 - 0.05, y=airflow_y - 0.09, width=0.05, height=0.18, louver=False)
        else:
            self._append_ahu_duct_stub(graphic, x=x0 + width, y=airflow_y - 0.09, width=0.05, height=0.18, louver=False)

        for index, section in enumerate(sections):
            section_width = width * (section.width_weight / total_weight)
            sx = cursor_x
            body_y = y0 + 0.18
            body_height = height - 0.28
            graphic.elements.append(GraphicElement(
                element_type="text",
                x=sx + (section_width / 2),
                y=y0 + 0.13,
                text=section.label,
                font_size=9,
                font_family="Arial",
                layer="labels",
            ))
            if index:
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=sx,
                    y=y0 + 0.2,
                    width=0,
                    height=height - 0.32,
                    stroke="#e2e8f0",
                    stroke_width=1,
                    layer="symbol",
                ))
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=sx + 0.01,
                y=body_y + 0.01,
                width=max(section_width - 0.02, 0.02),
                height=max(body_height - 0.02, 0.02),
                fill="url(#section-bay-gradient)",
                stroke="none",
                stroke_width=0,
                layer="symbol",
                css_class="section-bay",
            ))
            panel_w = max(section_width - 0.034, 0.02)
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=sx + 0.017,
                y=body_y + 0.028,
                width=panel_w,
                height=max(body_height - 0.07, 0.02),
                fill="none",
                stroke="#8f98a3",
                stroke_width=0.9,
                layer="symbol",
                css_class="equipment-panel",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=sx + 0.026,
                y=body_y + 0.045,
                width=max(panel_w - 0.018, 0.01),
                height=0,
                stroke="#ffffff",
                stroke_width=0.8,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=sx + max(section_width - 0.032, 0.02),
                y=body_y + 0.1,
                width=0,
                height=max(body_height - 0.16, 0.01),
                stroke="#6b7280",
                stroke_width=0.9,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="circle",
                x=sx + max(section_width - 0.028, 0.02),
                y=body_y + (body_height * 0.5),
                width=0.01,
                height=0.01,
                fill="#eef2f7",
                stroke="#4b5563",
                stroke_width=0.8,
                layer="symbol",
                css_class="panel-handle",
            ))
            if duct_profile == "vertical_upflow":
                path_x = sx + (section_width * 0.5)
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=path_x,
                    y=y0 + height - 0.04,
                    width=0,
                    height=-(height - 0.12),
                    stroke="#1976d2",
                    stroke_width=3,
                    layer="symbol",
                    css_class="airflow-path airflow-supply",
                ))
            elif duct_profile == "vertical_downflow":
                path_x = sx + (section_width * 0.5)
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=path_x,
                    y=y0 + 0.06,
                    width=0,
                    height=height - 0.12,
                    stroke="#1976d2",
                    stroke_width=3,
                    layer="symbol",
                    css_class="airflow-path airflow-supply",
                ))
            elif duct_profile == "horizontal_left":
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=sx + section_width,
                    y=airflow_y,
                    width=-section_width,
                    height=0,
                    stroke="#1976d2",
                    stroke_width=3,
                    layer="symbol",
                    css_class="airflow-path airflow-supply",
                ))
            else:
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=sx,
                    y=airflow_y,
                    width=section_width,
                    height=0,
                    stroke="#1976d2",
                    stroke_width=3,
                    layer="symbol",
                    css_class="airflow-path airflow-supply",
                ))
            center_x = sx + (section_width / 2)
            anchors[section.section_id] = (center_x, y0 + (height * self.AHU_SECTION_DETAIL_Y.get(section.section_id, 0.5)))
            self._append_ahu_section_detail(
                graphic,
                equip=equip,
                points=points,
                section=section,
                sx=sx,
                y0=y0,
                section_width=section_width,
                height=height,
            )
            section_asset_id = self._asset_id_for_section(section.section_id, equip=equip, points=points)
            self._record_asset_placement(
                graphic,
                asset_id=section_asset_id,
                x=sx + 0.02,
                y=body_y,
                width=max(section_width - 0.04, 0.03),
                height=body_height,
                role=f"section:{section.section_id}",
                equipment_id=equip.id,
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
                if duct_profile == "vertical_upflow":
                    anchors["supply_temp"] = (center_x, y0 + 0.05)
                    anchors["discharge_temp"] = (center_x, y0 + 0.05)
                elif duct_profile == "vertical_downflow":
                    anchors["supply_temp"] = (center_x, y0 + height + 0.02)
                    anchors["discharge_temp"] = (center_x, y0 + height + 0.02)
                else:
                    anchors["supply_temp"] = (center_x + 0.03, y0 + 0.22)
                    anchors["discharge_temp"] = (center_x + 0.03, y0 + 0.22)
            cursor_x += section_width

        graphic.elements.append(GraphicElement(
            element_type="text",
            x=x0 - 0.01 if intake_on_left else x0 + width + 0.02,
            y=airflow_y - 0.04,
            text="OA",
            font_size=9,
            font_family="Arial",
            layer="labels",
        ))
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=x0 + width + 0.02 if duct_profile not in {"horizontal_left", "vertical_upflow", "vertical_downflow"} else (x0 - 0.01 if duct_profile == "horizontal_left" else x0 + (width * 0.48)),
            y=airflow_y - 0.04 if duct_profile not in {"vertical_upflow", "vertical_downflow"} else (y0 - 0.03 if duct_profile == "vertical_upflow" else y0 + height + 0.12),
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

    def _asset_id_for_section(self, section_id: str, *, equip: Equipment, points: list[Point]) -> str:
        if section_id in {"outside_air", "mixed_air"}:
            if self._section_mentions(points, ("low leak", "low-leak", "leakage class", "opposed blade")):
                return "mixing_damper_low_leak"
            return "mixing_damper_bank"
        if section_id == "filter":
            if self._section_mentions(points, ("bag filter", "bag", "final filter", "hepa", "merv 14", "merv14", "merv 15", "merv15")):
                return "filter_bank_bag"
            return "filter_bank_vcell"
        if section_id == "cooling_coil":
            if equip.type == EquipmentType.RTU or self._section_mentions(points, ("dx", "direct expansion", "refrigerant", "compressor", "suction")):
                return "cooling_coil_dx"
            return "cooling_coil_chw"
        if section_id == "heating_coil":
            if self._section_mentions(points, ("steam", "condensate", "trap")):
                return "heating_coil_steam"
            return "heating_coil_hw"
        if section_id in {"supply_fan", "return_fan", "relief_fan"}:
            if section_id in {"return_fan", "relief_fan"}:
                return "relief_fan_housed"
            if equip.type in {EquipmentType.AHU} or self._section_mentions(points, ("plenum fan", "fan array", "direct drive", "direct-drive")):
                return "supply_fan_plenum"
            return "supply_fan_scroll"
        if section_id == "discharge":
            return "rectangular_supply_duct"
        if section_id == "humidifier":
            return "steam_humidifier_grid"
        if section_id == "energy_recovery":
            return "energy_recovery_wheel"
        return "rectangular_supply_duct"

    def _record_asset_placement(
        self,
        graphic: GraphicDefinition,
        *,
        asset_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
        role: str,
        equipment_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        placements = graphic.metadata.setdefault("asset_placements", [])
        placements.append(
            {
                "asset_id": asset_id,
                "role": role,
                "equipment_id": equipment_id,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "metadata": metadata or {},
            }
        )

    def _append_ahu_section_detail(
        self,
        graphic: GraphicDefinition,
        *,
        equip: Equipment,
        points: list[Point],
        section: GraphicSection,
        sx: float,
        y0: float,
        section_width: float,
        height: float,
    ) -> None:
        center_x = sx + (section_width / 2)
        body_y = y0 + 0.18
        body_height = height - 0.28
        body_x = sx + 0.02
        body_width = max(section_width - 0.04, 0.03)
        asset_id = self._asset_id_for_section(section.section_id, equip=equip, points=points)
        self._append_asset_instance(
            graphic,
            asset_id=asset_id,
            x=body_x,
            y=body_y,
            width=body_width,
            height=body_height,
            stroke=section.stroke,
        )

        if section.section_id in {"cooling_coil", "heating_coil"}:
            valve_y = y0 - 0.02 if section.section_id == "cooling_coil" else y0 + height + 0.02
            self._append_valve_symbol(
                graphic,
                x=center_x - 0.025,
                y=valve_y,
                width=0.05,
                height=0.05,
                stroke=section.stroke,
            )
            return

        if section.section_id == "humidifier":
            self._append_humidifier_symbol(
                graphic,
                x=body_x,
                y=body_y + 0.06,
                width=body_width,
                height=body_height - 0.12,
                stroke=section.stroke,
            )
            return

        if section.section_id == "energy_recovery":
            self._append_energy_recovery_symbol(
                graphic,
                x=center_x,
                y=y0 + (height * 0.5),
                width=section_width,
                stroke=section.stroke,
            )
            return

    def _append_asset_instance(
        self,
        graphic: GraphicDefinition,
        *,
        asset_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str = "#64748b",
    ) -> None:
        if asset_id == "mixing_damper_bank":
            self._append_mixing_damper_asset(graphic, x=x, y=y, width=width, height=height, stroke=stroke)
            return
        if asset_id == "mixing_damper_low_leak":
            self._append_mixing_damper_asset(graphic, x=x, y=y, width=width, height=height, stroke=stroke, low_leak=True)
            return
        if asset_id == "filter_bank_vcell":
            self._append_filter_bank_asset(graphic, x=x, y=y, width=width, height=height, stroke=stroke, bag_filter=False)
            return
        if asset_id == "filter_bank_bag":
            self._append_filter_bank_asset(graphic, x=x, y=y, width=width, height=height, stroke=stroke, bag_filter=True)
            return
        if asset_id == "cooling_coil_chw":
            self._append_coil_asset(graphic, x=x, y=y, width=width, height=height, stroke="#1976d2", coil_variant="chw")
            return
        if asset_id == "cooling_coil_dx":
            self._append_coil_asset(graphic, x=x, y=y, width=width, height=height, stroke="#1976d2", coil_variant="dx")
            return
        if asset_id == "heating_coil_hw":
            self._append_coil_asset(graphic, x=x, y=y, width=width, height=height, stroke="#ef6c00", coil_variant="hw")
            return
        if asset_id == "heating_coil_steam":
            self._append_coil_asset(graphic, x=x, y=y, width=width, height=height, stroke="#ef6c00", coil_variant="steam")
            return
        if asset_id == "supply_fan_scroll":
            self._append_fan_section_asset(graphic, x=x, y=y, width=width, height=height, stroke=stroke, fan_variant="scroll")
            return
        if asset_id == "supply_fan_plenum":
            self._append_fan_section_asset(graphic, x=x, y=y, width=width, height=height, stroke=stroke, fan_variant="plenum")
            return
        if asset_id == "relief_fan_housed":
            self._append_fan_section_asset(graphic, x=x, y=y, width=width, height=height, stroke=stroke, fan_variant="housed")
            return
        if asset_id == "steam_humidifier_grid":
            self._append_humidifier_asset(graphic, x=x, y=y, width=width, height=height, stroke=stroke)
            return
        if asset_id == "energy_recovery_wheel":
            self._append_energy_recovery_asset(graphic, x=x, y=y, width=width, height=height, stroke=stroke)
            return
        if asset_id == "rtu_packaged_rooftop":
            self._append_packaged_rtu_asset(graphic, x=x, y=y, width=width, height=height)
            return
        if asset_id == "chiller_air_cooled":
            self._append_chiller_asset(graphic, x=x, y=y, width=width, height=height, variant="air_cooled")
            return
        if asset_id == "chiller_centrifugal_water_cooled":
            self._append_chiller_asset(graphic, x=x, y=y, width=width, height=height, variant="water_cooled")
            return
        if asset_id == "boiler_condensing":
            self._append_boiler_asset(graphic, x=x, y=y, width=width, height=height, variant="condensing")
            return
        if asset_id == "boiler_firetube":
            self._append_boiler_asset(graphic, x=x, y=y, width=width, height=height, variant="firetube")
            return
        if asset_id == "pump_end_suction":
            self._append_pump_asset(graphic, x=x, y=y, width=width, height=height, variant="end_suction")
            return
        if asset_id == "pump_vertical_inline":
            self._append_pump_asset(graphic, x=x, y=y, width=width, height=height, variant="vertical_inline")
            return
        if asset_id == "cooling_tower_open_cell":
            self._append_cooling_tower_asset(graphic, x=x, y=y, width=width, height=height, variant="open_cell")
            return
        if asset_id == "cooling_tower_induced_draft":
            self._append_cooling_tower_asset(graphic, x=x, y=y, width=width, height=height, variant="induced_draft")
            return
        if asset_id == "rectangular_supply_duct":
            self._append_rectangular_duct_asset(graphic, x=x, y=y, width=width, height=height)
            return
        if asset_id == "vav_reheat_terminal":
            self._append_vav_terminal_asset(graphic, x=x, y=y, width=width, height=height)
            return

    def _append_rectangular_duct_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x,
            y=y + (height * 0.18),
            width=width,
            height=height * 0.42,
            fill="url(#duct-body-gradient)",
            stroke="#6b7280",
            stroke_width=1.1,
            layer="symbol",
            css_class="duct-shell",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + 0.008,
            y=y + (height * 0.18),
            width=width - 0.016,
            height=-(height * 0.12),
            stroke="#cfd6de",
            stroke_width=1,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + width - 0.008,
            y=y + (height * 0.18),
            width=0,
            height=height * 0.42,
            stroke="#525b66",
            stroke_width=1,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + 0.006,
            y=y + (height * 0.25),
            width=max(width - 0.012, 0.01),
            height=height * 0.24,
            fill="url(#duct-liner-gradient)",
            stroke="#9ca3af",
            stroke_width=0.7,
            layer="symbol",
            css_class="duct-liner",
        ))
        for offset in (0.18, 0.42, 0.66, 0.86):
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * offset),
                y=y + (height * 0.22),
                width=0,
                height=height * 0.34,
                stroke="#838c98",
                stroke_width=0.8,
                layer="symbol",
            ))

    def _append_mixing_damper_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
        low_leak: bool = False,
    ) -> None:
        self._append_damper_symbol(
            graphic,
            x=x,
            y=y + (height * 0.1),
            width=width,
            height=height * 0.7,
            stroke=stroke,
        )
        if low_leak:
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=x + 0.012,
                y=y + (height * 0.12),
                width=max(width - 0.024, 0.01),
                height=height * 0.02,
                fill="#0f172a",
                stroke="none",
                stroke_width=0,
                layer="symbol",
            ))
        graphic.elements.append(GraphicElement(
            element_type="circle",
            x=x + width + 0.008,
            y=y + (height * 0.52),
            width=min(width * 0.1, 0.018),
            height=min(width * 0.1, 0.018),
            fill="url(#motor-gradient)",
            stroke="#374151",
            stroke_width=0.8,
            layer="symbol",
            css_class="motor-body",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.86),
            y=y + (height * 0.5),
            width=width * 0.09,
            height=0,
            stroke="#4b5563",
            stroke_width=1.2,
            layer="symbol",
            css_class="motor-link",
        ))

    def _append_filter_bank_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
        bag_filter: bool = False,
    ) -> None:
        if bag_filter:
            self._append_bag_filter_symbol(
                graphic,
                x=x,
                y=y + (height * 0.1),
                width=width,
                height=height * 0.76,
                stroke=stroke,
            )
        else:
            self._append_filter_symbol(
                graphic,
                x=x,
                y=y + (height * 0.1),
                width=width,
                height=height * 0.76,
                stroke=stroke,
            )
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.08),
            y=y + (height * 0.18),
            width=width * 0.84,
            height=height * 0.08,
            fill="#ffffff",
            stroke="none",
            stroke_width=0,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.08),
            y=y + (height * 0.7),
            width=width * 0.84,
            height=height * 0.07,
            fill="#aeb8c2",
            stroke="none",
            stroke_width=0,
            layer="symbol",
        ))

    def _append_coil_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
        coil_variant: str = "chw",
    ) -> None:
        self._append_coil_symbol(
            graphic,
            x=x,
            y=y + (height * 0.12),
            width=width,
            height=height * 0.72,
            stroke=stroke,
            coil_variant=coil_variant,
        )

    def _append_fan_section_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
        fan_variant: str = "scroll",
    ) -> None:
        fan_size = min(width * 0.64, height * 0.62)
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.16),
            y=y + (height * 0.74),
            width=width * 0.54,
            height=height * 0.08,
            fill="url(#equipment-base-gradient)",
            stroke="#64748b",
            stroke_width=0.8,
            layer="symbol",
            css_class="fan-base",
        ))
        if fan_variant == "plenum":
            self._append_plenum_fan_symbol(
                graphic,
                x=x,
                y=y,
                width=width,
                height=height,
                stroke=stroke,
            )
        elif fan_variant == "housed":
            self._append_housed_fan_symbol(
                graphic,
                x=x,
                y=y,
                width=width,
                height=height,
                stroke=stroke,
            )
        else:
            self._append_fan_symbol(
                graphic,
                x=x + (width * 0.5),
                y=y + (height * 0.52),
                size=fan_size,
                stroke=stroke,
            )

    def _append_humidifier_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.08),
            y=y + (height * 0.16),
            width=width * 0.84,
            height=height * 0.58,
            fill="#e2e8f0",
            stroke="#64748b",
            stroke_width=1,
            layer="symbol",
        ))
        self._append_humidifier_symbol(
            graphic,
            x=x + (width * 0.12),
            y=y + (height * 0.12),
            width=width * 0.76,
            height=height * 0.62,
            stroke=stroke,
        )
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.12),
            y=y + (height * 0.46),
            width=-(width * 0.08),
            height=0,
            stroke="#8b5e34",
            stroke_width=3,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.84),
            y=y + (height * 0.72),
            width=0,
            height=height * 0.1,
            stroke="#64748b",
            stroke_width=2,
            layer="symbol",
        ))

    def _append_energy_recovery_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.14),
            y=y + (height * 0.14),
            width=width * 0.72,
            height=height * 0.6,
            fill="#e2e8f0",
            stroke="#64748b",
            stroke_width=1,
            layer="symbol",
        ))
        self._append_energy_recovery_symbol(
            graphic,
            x=x + (width * 0.5),
            y=y + (height * 0.44),
            width=width * 0.6,
            stroke=stroke,
        )
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.72),
            y=y + (height * 0.34),
            width=width * 0.08,
            height=height * 0.16,
            fill="url(#motor-gradient)",
            stroke="#4b5563",
            stroke_width=0.8,
            layer="symbol",
            css_class="motor-body",
        ))

    def _build_plant_scene(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
        *,
        asset_id: str,
    ) -> dict[str, tuple[float, float]]:
        x = 0.14
        y = 0.18
        width = 0.72
        height = 0.52
        self._record_asset_placement(
            graphic,
            asset_id=asset_id,
            x=x,
            y=y,
            width=width,
            height=height,
            role="primary_equipment",
            equipment_id=equip.id,
        )
        self._append_asset_instance(
            graphic,
            asset_id=asset_id,
            x=x,
            y=y,
            width=width,
            height=height,
        )
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=0.5,
            y=0.83,
            text=equip.id,
            font_size=14,
            font_family="Arial",
            layer="labels",
        ))
        graphic.elements.append(GraphicElement(
            element_type="text",
            x=0.5,
            y=0.88,
            text=equip.type.value,
            font_size=9,
            font_family="Arial",
            layer="labels",
        ))
        anchors: dict[str, tuple[float, float]] = {
            "generic_sensor": (0.1, 0.24),
            "generic_actuator": (0.9, 0.24),
            "generic_setpoint": (0.26, 0.09),
            "generic_status": (0.26, 0.91),
            "generic_alarm": (0.08, 0.9),
        }
        if equip.type == EquipmentType.CHILLER:
            anchors.update({
                "supply_temp": (0.2, 0.74),
                "return_temp": (0.8, 0.74),
                "cooling_valve": (0.86, 0.3),
                "static_pressure": (0.52, 0.46),
            })
        elif equip.type == EquipmentType.BOILER:
            anchors.update({
                "heating_valve": (0.2, 0.52),
                "supply_temp": (0.9, 0.34),
                "return_temp": (0.9, 0.66),
                "status": (0.22, 0.8),
            })
        elif equip.type == EquipmentType.COOLING_TOWER:
            anchors.update({
                "supply_fan": (0.5, 0.24),
                "return_temp": (0.12, 0.82),
                "supply_temp": (0.5, 0.08),
                "status": (0.5, 0.9),
            })
        else:
            anchors.update({
                "supply_fan": (0.66, 0.58),
                "status": (0.74, 0.3),
                "static_pressure": (0.44, 0.58),
                "supply_temp": (0.88, 0.42),
                "return_temp": (0.12, 0.58),
            })
        return anchors

    def _append_packaged_rtu_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        self._append_ahu_section_shell(graphic, x=x, y=y, width=width, height=height)
        self._append_fan_symbol(graphic, x=x + (width * 0.8), y=y - (height * 0.02), size=min(width * 0.14, height * 0.18), stroke="#475569")
        self._append_fan_symbol(graphic, x=x + (width * 0.66), y=y - (height * 0.02), size=min(width * 0.14, height * 0.18), stroke="#475569")

    def _append_chiller_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        variant: str = "air_cooled",
    ) -> None:
        if variant == "water_cooled":
            graphic.elements.append(GraphicElement(
                element_type="ellipse",
                x=x + (width * 0.22),
                y=y + (height * 0.58),
                width=width * 0.16,
                height=height * 0.16,
                fill="#f8fafc",
                stroke="#475569",
                stroke_width=1.8,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="ellipse",
                x=x + (width * 0.72),
                y=y + (height * 0.58),
                width=width * 0.18,
                height=height * 0.16,
                fill="#dbeafe",
                stroke="#2563eb",
                stroke_width=1.8,
                layer="symbol",
            ))
            self._append_equipment_body(graphic, x=x + (width * 0.34), y=y + (height * 0.16), width=width * 0.24, height=height * 0.42)
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.09),
                y=y + (height * 0.58),
                width=width * 0.08,
                height=0,
                stroke="#1976d2",
                stroke_width=3,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.48),
                y=y + (height * 0.66),
                width=0,
                height=height * 0.12,
                stroke="#1976d2",
                stroke_width=3,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.8),
                y=y + (height * 0.66),
                width=0,
                height=height * 0.12,
                stroke="#1976d2",
                stroke_width=3,
                layer="symbol",
            ))
            return
        self._append_equipment_body(graphic, x=x, y=y + 0.06, width=width, height=height * 0.78)
        self._append_fan_symbol(graphic, x=x + (width * 0.7), y=y + (height * 0.12), size=min(width * 0.12, height * 0.18), stroke="#475569")
        self._append_fan_symbol(graphic, x=x + (width * 0.84), y=y + (height * 0.12), size=min(width * 0.12, height * 0.18), stroke="#475569")
        self._append_pump_volute(graphic, x=x + (width * 0.24), y=y + (height * 0.5), scale=min(width, height) * 0.22, stroke="#475569", fill="#f8fafc")
        self._append_coil_symbol(graphic, x=x + (width * 0.44), y=y + (height * 0.34), width=width * 0.18, height=height * 0.22, stroke="#1976d2", coil_variant="chw")

    def _append_boiler_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        variant: str = "condensing",
    ) -> None:
        if variant == "firetube":
            graphic.elements.append(GraphicElement(
                element_type="ellipse",
                x=x + (width * 0.42),
                y=y + (height * 0.48),
                width=width * 0.38,
                height=height * 0.34,
                fill="#f7ead2",
                stroke="#c2410c",
                stroke_width=2,
                layer="symbol",
            ))
            self._append_pump_volute(graphic, x=x + (width * 0.16), y=y + (height * 0.48), scale=min(width, height) * 0.16, stroke="#475569", fill="#f8fafc")
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=x + (width * 0.72),
                y=y + (height * 0.1),
                width=width * 0.05,
                height=height * 0.22,
                fill="#6b7280",
                stroke="#374151",
                stroke_width=1,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.06),
                y=y + (height * 0.58),
                width=width * 0.08,
                height=0,
                stroke="#ef6c00",
                stroke_width=3,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.7),
                y=y + (height * 0.42),
                width=width * 0.12,
                height=0,
                stroke="#ef6c00",
                stroke_width=3,
                layer="symbol",
            ))
            return
        self._append_equipment_body(graphic, x=x + (width * 0.06), y=y + (height * 0.06), width=width * 0.7, height=height * 0.82, shell_fill="#f7ead2")
        self._append_pump_volute(graphic, x=x + (width * 0.2), y=y + (height * 0.48), scale=min(width, height) * 0.16, stroke="#475569", fill="#f8fafc")
        self._append_coil_symbol(graphic, x=x + (width * 0.42), y=y + (height * 0.3), width=width * 0.16, height=height * 0.3, stroke="#ef6c00", coil_variant="steam")
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.8),
            y=y - (height * 0.02),
            width=width * 0.06,
            height=height * 0.26,
            fill="#6b7280",
            stroke="#374151",
            stroke_width=1,
            layer="symbol",
        ))

    def _append_pump_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        variant: str = "end_suction",
    ) -> None:
        if variant == "vertical_inline":
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=x + (width * 0.44),
                y=y + (height * 0.1),
                width=width * 0.12,
                height=height * 0.18,
                fill="url(#motor-gradient)",
                stroke="#4b5563",
                stroke_width=1,
                layer="symbol",
                css_class="motor-body",
            ))
            self._append_pump_volute(graphic, x=x + (width * 0.5), y=y + (height * 0.54), scale=min(width, height) * 0.22, stroke="#2563eb", fill="#dbeafe")
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.5),
                y=y + (height * 0.28),
                width=0,
                height=height * 0.38,
                stroke="#1976d2",
                stroke_width=4,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.34),
                y=y + (height * 0.54),
                width=width * 0.32,
                height=0,
                stroke="#1976d2",
                stroke_width=4,
                layer="symbol",
            ))
            self._append_valve_symbol(graphic, x=x + (width * 0.28), y=y + (height * 0.5), width=width * 0.08, height=height * 0.08, stroke="#2563eb")
            self._append_valve_symbol(graphic, x=x + (width * 0.64), y=y + (height * 0.12), width=width * 0.08, height=height * 0.08, stroke="#2563eb")
            return
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.08),
            y=y + (height * 0.74),
            width=width * 0.56,
            height=height * 0.08,
            fill="url(#equipment-base-gradient)",
            stroke="#64748b",
            stroke_width=0.8,
            layer="symbol",
            css_class="fan-base",
        ))
        self._append_pump_volute(graphic, x=x + (width * 0.34), y=y + (height * 0.54), scale=min(width, height) * 0.22, stroke="#2563eb", fill="#dbeafe")
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.5),
            y=y + (height * 0.4),
            width=width * 0.18,
            height=height * 0.16,
            fill="url(#motor-gradient)",
            stroke="#4b5563",
            stroke_width=1,
            layer="symbol",
            css_class="motor-body",
        ))
        self._append_valve_symbol(graphic, x=x + (width * 0.04), y=y + (height * 0.5), width=width * 0.1, height=height * 0.08, stroke="#2563eb")
        self._append_valve_symbol(graphic, x=x + (width * 0.76), y=y + (height * 0.36), width=width * 0.1, height=height * 0.08, stroke="#2563eb")

    def _append_cooling_tower_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        variant: str = "open_cell",
    ) -> None:
        if variant == "induced_draft":
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=x + (width * 0.24),
                y=y + (height * 0.12),
                width=width * 0.52,
                height=height * 0.62,
                fill="#d7f0ea",
                stroke="#0f766e",
                stroke_width=1.8,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.24),
                y=y + (height * 0.12),
                width=width * 0.06,
                height=-(height * 0.08),
                stroke="#0f766e",
                stroke_width=1.8,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.76),
                y=y + (height * 0.12),
                width=-(width * 0.06),
                height=-(height * 0.08),
                stroke="#0f766e",
                stroke_width=1.8,
                layer="symbol",
            ))
            self._append_fan_symbol(graphic, x=x + (width * 0.5), y=y + (height * 0.1), size=min(width * 0.14, height * 0.16), stroke="#475569")
            for offset in (0.34, 0.42, 0.5, 0.58, 0.66):
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=x + (width * offset),
                    y=y + (height * 0.32),
                    width=0,
                    height=height * 0.26,
                    stroke="#0f766e",
                    stroke_width=1.2,
                    layer="symbol",
                ))
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=x + (width * 0.34),
                y=y + (height * 0.76),
                width=width * 0.32,
                height=height * 0.08,
                fill="#bfdbfe",
                stroke="#2563eb",
                stroke_width=1.2,
                layer="symbol",
            ))
            return
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.18),
            y=y + (height * 0.04),
            width=width * 0.64,
            height=height * 0.72,
            fill="#d7f0ea",
            stroke="#0f766e",
            stroke_width=1.8,
            layer="symbol",
            css_class="equipment-shell",
        ))
        self._append_fan_symbol(graphic, x=x + (width * 0.5), y=y + (height * 0.14), size=min(width * 0.16, height * 0.18), stroke="#475569")
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.32),
            y=y + (height * 0.38),
            width=width * 0.36,
            height=height * 0.14,
            fill="#b7e4dc",
            stroke="#0f766e",
            stroke_width=1.2,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.24),
            y=y + (height * 0.76),
            width=width * 0.52,
            height=height * 0.08,
            fill="#bfdbfe",
            stroke="#2563eb",
            stroke_width=1.2,
            layer="symbol",
        ))

    def _append_ahu_section_shell(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        self._append_equipment_body(graphic, x=x, y=y, width=width, height=height)

    def _append_equipment_body(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        shell_fill: str = "url(#equipment-shell-gradient)",
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="rect", x=x, y=y, width=width, height=height,
            fill=shell_fill, stroke="#5b5b57", stroke_width=2, layer="symbol", css_class="equipment-shell",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect", x=x + 0.01, y=y + 0.02, width=max(width - 0.02, 0.02), height=max(height - 0.04, 0.02),
            fill="url(#equipment-face-gradient)", stroke="#9aa0a6", stroke_width=1, layer="symbol", css_class="equipment-face",
        ))

    def _append_pump_volute(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        scale: float,
        stroke: str,
        fill: str,
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="circle", x=x, y=y, width=scale, height=scale,
            fill=fill, stroke=stroke, stroke_width=1.6, layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="circle", x=x, y=y, width=scale * 0.46, height=scale * 0.46,
            fill="#ffffff", stroke=stroke, stroke_width=1.2, layer="symbol",
        ))

    def _append_vav_terminal_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        self._append_isometric_vav_asset(
            graphic,
            x=x,
            y=y,
            width=width,
            height=height,
        )

    def _append_damper_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        blade_count = 3
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x,
            y=y + (height * 0.08),
            width=width,
            height=height * 0.78,
            fill="url(#damper-frame-gradient)",
            stroke="#64748b",
            stroke_width=1,
            layer="symbol",
            css_class="damper-frame",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + 0.006,
            y=y + (height * 0.14),
            width=max(width - 0.012, 0.01),
            height=height * 0.62,
            fill="#f8fafc",
            stroke="#cbd5e1",
            stroke_width=0.6,
            layer="symbol",
        ))
        gap = height / (blade_count + 1)
        for index in range(blade_count):
            y_pos = y + ((index + 1) * gap)
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x,
                y=y_pos,
                width=width,
                height=height * 0.18,
                stroke=stroke,
                stroke_width=2,
                layer="symbol",
            ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.1),
            y=y + (height * 0.16),
            width=width * 0.8,
            height=0,
            stroke="#ffffff",
            stroke_width=0.8,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.84),
            y=y + (height * 0.18),
            width=0,
            height=height * 0.58,
            stroke="#64748b",
            stroke_width=1.1,
            layer="symbol",
            css_class="damper-linkage",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + width + 0.008,
            y=y + (height * 0.32),
            width=min(width * 0.12, 0.022),
            height=min(height * 0.2, 0.04),
            fill="url(#motor-gradient)",
            stroke="#4b5563",
            stroke_width=0.8,
            layer="symbol",
            css_class="actuator-body",
        ))

    def _append_filter_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        pleat_count = 5
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x,
            y=y,
            width=width,
            height=height,
            fill="#cfd6de",
            stroke="#5b6470",
            stroke_width=1.2,
            layer="symbol",
            css_class="filter-bank",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.08),
            y=y + (height * 0.12),
            width=width * 0.84,
            height=height * 0.72,
            fill="#f8fafc",
            stroke="#b6c2cd",
            stroke_width=0.8,
            layer="symbol",
        ))
        spacing = (width * 0.76) / pleat_count
        for index in range(pleat_count):
            start_x = x + (width * 0.12) + (index * spacing)
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=start_x,
                y=y + (height * 0.82),
                width=spacing * 0.48,
                height=-(height * 0.58),
                stroke="#64748b",
                stroke_width=1.5,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=start_x + (spacing * 0.06),
                y=y + (height * 0.78),
                width=spacing * 0.34,
                height=-(height * 0.42),
                stroke=stroke,
                stroke_width=1.2,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=start_x + (spacing * 0.04),
                y=y + (height * 0.24),
                width=spacing * 0.32,
                height=height * 0.46,
                fill="#eef2f6",
                stroke="none",
                stroke_width=0,
                layer="symbol",
            ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.1),
            y=y + (height * 0.18),
            width=width * 0.8,
            height=height * 0.08,
            fill="#e5ebf1",
            stroke="#cbd5e1",
            stroke_width=0.6,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.1),
            y=y + (height * 0.18),
            width=width * 0.8,
            height=0,
            stroke="#ffffff",
            stroke_width=0.8,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.12),
            y=y + (height * 0.8),
            width=width * 0.76,
            height=0,
            stroke=stroke,
            stroke_width=1,
            layer="symbol",
        ))

    def _append_bag_filter_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x,
            y=y,
            width=width,
            height=height,
            fill="#cfd6de",
            stroke="#5b6470",
            stroke_width=1.2,
            layer="symbol",
            css_class="filter-bank",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.08),
            y=y + (height * 0.08),
            width=width * 0.84,
            height=height * 0.12,
            fill="#f8fafc",
            stroke="#cbd5e1",
            stroke_width=0.7,
            layer="symbol",
        ))
        pocket_count = 3
        pocket_w = width * 0.18
        gap = width * 0.1
        for index in range(pocket_count):
            pocket_x = x + (width * 0.14) + index * (pocket_w + gap)
            graphic.elements.append(GraphicElement(
                element_type="rect",
                x=pocket_x,
                y=y + (height * 0.2),
                width=pocket_w,
                height=height * 0.48,
                fill="#f8fafc",
                stroke="#64748b",
                stroke_width=1,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=pocket_x,
                y=y + (height * 0.2),
                width=0,
                height=height * 0.48,
                stroke=stroke,
                stroke_width=1.7,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=pocket_x + pocket_w,
                y=y + (height * 0.2),
                width=0,
                height=height * 0.48,
                stroke=stroke,
                stroke_width=1.7,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=pocket_x,
                y=y + (height * 0.68),
                width=pocket_w / 2,
                height=height * 0.1,
                stroke=stroke,
                stroke_width=1.5,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=pocket_x + pocket_w,
                y=y + (height * 0.68),
                width=-(pocket_w / 2),
                height=height * 0.1,
                stroke=stroke,
                stroke_width=1.5,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=pocket_x + (pocket_w * 0.18),
                y=y + (height * 0.28),
                width=pocket_w * 0.64,
                height=0,
                stroke="#cbd5e1",
                stroke_width=0.8,
                layer="symbol",
            ))

    def _append_coil_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
        coil_variant: str = "chw",
    ) -> None:
        fin_fill = "#d9e1e8"
        fin_stroke = "#6b7280"
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x,
            y=y,
            width=width,
            height=height,
            fill="#cfd6de",
            stroke="#5b6470",
            stroke_width=1.2,
            layer="symbol",
            css_class="coil-face",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.12),
            y=y + (height * 0.12),
            width=width * 0.76,
            height=height * 0.68,
            fill=fin_fill,
            stroke="#9aa0a6",
            stroke_width=0.8,
            layer="symbol",
        ))
        for offset in (0.18, 0.28, 0.38, 0.48, 0.58, 0.68, 0.78):
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * offset),
                y=y + (height * 0.14),
                width=0,
                height=height * 0.64,
                stroke=fin_stroke,
                stroke_width=0.7,
                layer="symbol",
            ))
        tube_rows = 4
        row_gap = (height * 0.56) / max(tube_rows - 1, 1)
        for row in range(tube_rows):
            y_pos = y + (height * 0.2) + (row * row_gap)
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (width * 0.16),
                y=y_pos,
                width=width * 0.68,
                height=0,
                stroke=stroke,
                stroke_width=1.2,
                layer="symbol",
            ))
        header_offset = 0.018
        pipe_stroke = "#b87333" if stroke != "#1976d2" else "#8c5a2b"
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x - header_offset - 0.004,
            y=y + 0.006,
            width=0.008,
            height=max(height - 0.012, 0.01),
            fill="#b58b64",
            stroke="#8c5a2b",
            stroke_width=0.6,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x - header_offset,
            y=y + 0.01,
            width=0,
            height=height - 0.02,
            stroke=pipe_stroke,
            stroke_width=1.8,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + width + header_offset - 0.004,
            y=y + 0.006,
            width=0.008,
            height=max(height - 0.012, 0.01),
            fill="#b58b64",
            stroke="#8c5a2b",
            stroke_width=0.6,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + width + header_offset,
            y=y + 0.01,
            width=0,
            height=height - 0.02,
            stroke=pipe_stroke,
            stroke_width=1.8,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x - header_offset,
            y=y + 0.02,
            width=width + (header_offset * 2),
            height=0,
            stroke=pipe_stroke,
            stroke_width=0.9,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x - header_offset,
            y=y + height - 0.02,
            width=width + (header_offset * 2),
            height=0,
            stroke=pipe_stroke,
            stroke_width=0.9,
            layer="symbol",
        ))
        for y_offset in (0.22, 0.42, 0.62):
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x - header_offset,
                y=y + (height * y_offset),
                width=width * 0.08,
                height=-(height * 0.08) if int(y_offset * 100) % 40 else (height * 0.08),
                stroke=pipe_stroke,
                stroke_width=1.1,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + width + header_offset - (width * 0.08),
                y=y + (height * y_offset),
                width=width * 0.08,
                height=(height * 0.08) if int(y_offset * 100) % 40 else -(height * 0.08),
                stroke=pipe_stroke,
                stroke_width=1.1,
                layer="symbol",
            ))
        self._append_pipe_flange(
            graphic,
            x=x - header_offset - 0.008,
            y=y + (height * 0.12),
            width=0.012,
            height=0.02,
        )
        self._append_pipe_flange(
            graphic,
            x=x - header_offset - 0.008,
            y=y + (height * 0.76),
            width=0.012,
            height=0.02,
        )
        self._append_pipe_flange(
            graphic,
            x=x + width + header_offset - 0.004,
            y=y + (height * 0.12),
            width=0.012,
            height=0.02,
        )
        self._append_pipe_flange(
            graphic,
            x=x + width + header_offset - 0.004,
            y=y + (height * 0.76),
            width=0.012,
            height=0.02,
        )
        self._append_flex_connector(
            graphic,
            x=x - header_offset - 0.028,
            y=y + (height * 0.1),
            width=0.018,
            height=height * 0.8,
            stroke=pipe_stroke,
        )
        if coil_variant == "dx":
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + width + header_offset,
                y=y + (height * 0.2),
                width=width * 0.16,
                height=-(height * 0.08),
                stroke="#8c5a2b",
                stroke_width=1.3,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + width + header_offset,
                y=y + (height * 0.8),
                width=width * 0.16,
                height=height * 0.08,
                stroke="#8c5a2b",
                stroke_width=1.3,
                layer="symbol",
            ))
            self._append_pipe_flange(
                graphic,
                x=x + width + header_offset + (width * 0.12),
                y=y + (height * 0.12),
                width=0.012,
                height=0.02,
            )
            self._append_pipe_flange(
                graphic,
                x=x + width + header_offset + (width * 0.12),
                y=y + (height * 0.78),
                width=0.012,
                height=0.02,
            )
        if coil_variant == "steam":
            self._append_y_strainer(
                graphic,
                x=x - header_offset - 0.04,
                y=y + (height * 0.16),
                width=0.03,
                height=0.04,
                stroke=pipe_stroke,
            )
            graphic.elements.append(GraphicElement(
                element_type="circle",
                x=x + width + (header_offset * 1.9),
                y=y + (height * 0.82),
                width=0.018,
                height=0.018,
                fill="#d1d5db",
                stroke="#4b5563",
                stroke_width=0.8,
                layer="symbol",
            ))
        if coil_variant in {"chw", "hw"}:
            self._append_y_strainer(
                graphic,
                x=x - header_offset - 0.04,
                y=y + (height * 0.16),
                width=0.03,
                height=0.04,
                stroke=pipe_stroke,
            )

    def _append_fan_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        size: float,
        stroke: str,
    ) -> None:
        housing_w = size * 0.92
        housing_h = size * 0.7
        graphic.elements.append(GraphicElement(
            element_type="ellipse",
            x=x - (size * 0.02),
            y=y + (size * 0.02),
            width=size * 0.78,
            height=size * 0.78,
            fill="#dce3ea",
            stroke="#475569",
            stroke_width=2,
            layer="symbol",
            css_class="fan-housing",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x - (housing_w * 0.44),
            y=y - (housing_h * 0.28),
            width=housing_w,
            height=housing_h,
            fill="#cfd6de",
            stroke="#6b7280",
            stroke_width=1.3,
            layer="symbol",
            css_class="fan-shell",
        ))
        graphic.elements.append(GraphicElement(
            element_type="circle",
            x=x - (size * 0.03),
            y=y + (size * 0.02),
            width=size * 0.52,
            height=size * 0.52,
            fill="#f8fafc",
            stroke=stroke,
            stroke_width=1.6,
            layer="symbol",
        ))
        blade_center_x = x - (size * 0.03)
        blade_center_y = y + (size * 0.02)
        blade = size * 0.18
        for angle_deg in (18, 138, 258):
            angle = math.radians(angle_deg)
            dx = math.cos(angle) * blade
            dy = math.sin(angle) * blade
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=blade_center_x,
                y=blade_center_y,
                width=dx,
                height=dy,
                stroke=stroke,
                stroke_width=1.5,
                layer="symbol",
                css_class="fan-blade",
            ))
        graphic.elements.append(GraphicElement(
            element_type="circle",
            x=x - (size * 0.03),
            y=y + (size * 0.02),
            width=size * 0.12,
            height=size * 0.12,
            fill="#d1d5db",
            stroke=stroke,
            stroke_width=1.1,
            layer="symbol",
            css_class="fan-hub",
        ))
        motor_x = x + (size * 0.34)
        motor_y = y + (size * 0.14)
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=motor_x,
            y=motor_y,
            width=size * 0.18,
            height=size * 0.18,
            fill="#6b7280",
            stroke="#4b5563",
            stroke_width=1,
            layer="symbol",
            css_class="motor-body",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (size * 0.08),
            y=y + (size * 0.02),
            width=size * 0.26,
            height=size * 0.12,
            stroke="#4b5563",
            stroke_width=1.2,
            layer="symbol",
            css_class="motor-link",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x - (housing_w * 0.5),
            y=y + (housing_h * 0.18),
            width=housing_w * 0.96,
            height=0,
            stroke="#f8fafc",
            stroke_width=0.8,
            layer="symbol",
        ))

    def _append_plenum_fan_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        wheel_size = min(width * 0.28, height * 0.38)
        centers = (x + (width * 0.35), x + (width * 0.68))
        for center_x in centers:
            self._append_fan_symbol(
                graphic,
                x=center_x,
                y=y + (height * 0.52),
                size=wheel_size,
                stroke=stroke,
            )
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.14),
            y=y + (height * 0.18),
            width=width * 0.66,
            height=height * 0.52,
            fill="none",
            stroke="#94a3b8",
            stroke_width=0.9,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.76),
            y=y + (height * 0.38),
            width=width * 0.12,
            height=height * 0.18,
            fill="url(#motor-gradient)",
            stroke="#4b5563",
            stroke_width=0.8,
            layer="symbol",
            css_class="motor-body",
        ))

    def _append_housed_fan_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        self._append_fan_symbol(
            graphic,
            x=x + (width * 0.42),
            y=y + (height * 0.56),
            size=min(width * 0.34, height * 0.42),
            stroke=stroke,
        )
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.18),
            y=y + (height * 0.56),
            width=width * 0.14,
            height=0,
            stroke="#94a3b8",
            stroke_width=2,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.58),
            y=y + (height * 0.44),
            width=width * 0.16,
            height=-(height * 0.16),
            stroke="#64748b",
            stroke_width=2.4,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.72),
            y=y + (height * 0.2),
            width=width * 0.1,
            height=height * 0.18,
            fill="url(#motor-gradient)",
            stroke="#4b5563",
            stroke_width=0.9,
            layer="symbol",
            css_class="motor-body",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.62),
            y=y + (height * 0.46),
            width=width * 0.1,
            height=-(height * 0.12),
            stroke="#4b5563",
            stroke_width=1.2,
            layer="symbol",
            css_class="motor-link",
        ))

    def _append_humidifier_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        manifold_y = y + (height * 0.35)
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.08),
            y=y + (height * 0.2),
            width=width * 0.84,
            height=height * 0.08,
            fill="#cbd5e1",
            stroke="#64748b",
            stroke_width=0.8,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x,
            y=manifold_y,
            width=width,
            height=0,
            stroke=stroke,
            stroke_width=2,
            layer="symbol",
        ))
        for offset in (0.18, 0.38, 0.58, 0.78):
            nozzle_x = x + (width * offset)
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=nozzle_x,
                y=manifold_y,
                width=0,
                height=height * 0.34,
                stroke=stroke,
                stroke_width=1.4,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="circle",
                x=nozzle_x,
                y=manifold_y + (height * 0.38),
                width=0.01,
                height=0.01,
                fill="#dbeafe",
                stroke="none",
                stroke_width=0,
                layer="symbol",
            ))

    def _append_energy_recovery_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        stroke: str,
    ) -> None:
        offset = min(width * 0.16, 0.06)
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x - (offset * 1.7),
            y=y - 0.07,
            width=offset * 3.4,
            height=0.14,
            fill="#e2e8f0",
            stroke="#64748b",
            stroke_width=1,
            layer="symbol",
        ))
        for multiplier in (-1, 1):
            graphic.elements.append(GraphicElement(
                element_type="circle",
                x=x + (multiplier * offset),
                y=y,
                width=0.08,
                height=0.08,
                fill="#ffffff",
                stroke=stroke,
                stroke_width=2,
                layer="symbol",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + (multiplier * offset),
                y=y - 0.03,
                width=0,
                height=0.06,
                stroke=stroke,
                stroke_width=1.2,
                layer="symbol",
            ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x - offset,
            y=y,
            width=offset * 2,
            height=0,
            stroke=stroke,
            stroke_width=1.6,
            layer="symbol",
        ))

    def _append_valve_symbol(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x,
            y=y + (height / 2),
            width=width,
            height=0,
            stroke=stroke,
            stroke_width=1.6,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.18),
            y=y + (height * 0.2),
            width=width * 0.32,
            height=height * 0.3,
            stroke=stroke,
            stroke_width=1.4,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.18),
            y=y + (height * 0.8),
            width=width * 0.32,
            height=-(height * 0.3),
            stroke=stroke,
            stroke_width=1.4,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.5),
            y=y + (height * 0.2),
            width=width * 0.32,
            height=height * 0.3,
            stroke=stroke,
            stroke_width=1.4,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.5),
            y=y + (height * 0.8),
            width=width * 0.32,
            height=-(height * 0.3),
            stroke=stroke,
            stroke_width=1.4,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + (width * 0.33),
            y=y - (height * 0.18),
            width=width * 0.14,
            height=height * 0.22,
            fill="url(#motor-gradient)",
            stroke="#4b5563",
            stroke_width=0.8,
            layer="symbol",
            css_class="actuator-body",
        ))

    def _append_pipe_flange(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x,
            y=y,
            width=width,
            height=height,
            fill="#d1d5db",
            stroke="#6b7280",
            stroke_width=0.7,
            layer="symbol",
            css_class="pipe-flange",
        ))

    def _append_flex_connector(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        segments = 4
        for index in range(segments):
            line_y = y + ((index + 0.5) * (height / segments))
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x,
                y=line_y,
                width=width,
                height=(height / segments) * (0.22 if index % 2 == 0 else -0.22),
                stroke=stroke,
                stroke_width=0.9,
                layer="symbol",
                css_class="flex-connector",
            ))

    def _append_y_strainer(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        stroke: str,
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x,
            y=y + (height * 0.2),
            width=width * 0.58,
            height=height * 0.24,
            stroke=stroke,
            stroke_width=1.3,
            layer="symbol",
            css_class="pipe-strainer",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.58),
            y=y + (height * 0.44),
            width=width * 0.3,
            height=-(height * 0.38),
            stroke=stroke,
            stroke_width=1.3,
            layer="symbol",
            css_class="pipe-strainer",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width * 0.38),
            y=y + (height * 0.34),
            width=width * 0.18,
            height=height * 0.18,
            stroke="#94a3b8",
            stroke_width=0.8,
            layer="symbol",
            css_class="pipe-strainer",
        ))

    def _append_ahu_duct_stub(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        louver: bool,
    ) -> None:
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x,
            y=y,
            width=width,
            height=height,
            fill="url(#duct-body-gradient)",
            stroke="#6b7280",
            stroke_width=1.3,
            layer="symbol",
            css_class="duct-shell",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + 0.003,
            y=y + 0.01,
            width=max(width - 0.006, 0.01),
            height=max(height - 0.02, 0.02),
            fill="url(#duct-liner-gradient)",
            stroke="#9ca3af",
            stroke_width=0.7,
            layer="symbol",
            css_class="duct-liner",
        ))
        if louver:
            slat_gap = height / 7
            for index in range(1, 6):
                graphic.elements.append(GraphicElement(
                    element_type="line",
                    x=x + 0.004,
                    y=y + (index * slat_gap),
                    width=width - 0.008,
                    height=slat_gap * 0.35,
                    stroke="#9aa0a6",
                    stroke_width=1,
                    layer="symbol",
                ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x,
            y=y,
            width=width / 2,
            height=height / 2,
            stroke="#6b7280",
            stroke_width=1.6,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + (width / 2),
            y=y + height,
            width=width / 2,
            height=-(height / 2),
            stroke="#6b7280",
            stroke_width=1.6,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + 0.003,
            y=y + 0.01,
            width=width - 0.006,
            height=0,
            stroke="#ffffff",
            stroke_width=0.8,
            layer="symbol",
        ))

    def _append_isometric_vav_asset(
        self,
        graphic: GraphicDefinition,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        body_y = y + 0.06
        body_h = height * 0.42
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x,
            y=body_y,
            width=width,
            height=body_h,
            fill="url(#duct-body-gradient)",
            stroke="#5b6470",
            stroke_width=1.8,
            layer="equipment",
            css_class="vav-shell",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + 0.02,
            y=y + 0.11,
            width=width - 0.04,
            height=height * 0.2,
            fill="url(#duct-liner-gradient)",
            stroke="#94a3b8",
            stroke_width=0.8,
            layer="equipment",
            css_class="vav-face",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + 0.02,
            y=body_y,
            width=width * 0.08,
            height=-(height * 0.06),
            stroke="#cbd5e1",
            stroke_width=1,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + width,
            y=body_y,
            width=-(width * 0.08),
            height=-(height * 0.06),
            stroke="#cbd5e1",
            stroke_width=1,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + 0.055,
            y=y + 0.14,
            width=0.12,
            height=0.09,
            fill="none",
            stroke="#7b8794",
            stroke_width=0.8,
            layer="symbol",
            css_class="equipment-panel",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + 0.08,
            y=y + 0.29,
            width=0.1,
            height=-0.09,
            stroke="#475569",
            stroke_width=2.4,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="circle",
            x=x + 0.145,
            y=y + 0.185,
            width=0.01,
            height=0.01,
            fill="#eef2f7",
            stroke="#4b5563",
            stroke_width=0.8,
            layer="symbol",
            css_class="panel-handle",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + 0.32,
            y=y + 0.13,
            width=0.14,
            height=0.16,
            fill="url(#coil-face-gradient)",
            stroke="#c2410c",
            stroke_width=1.2,
            layer="symbol",
            css_class="coil-face",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + 0.305,
            y=y + 0.145,
            width=0,
            height=0.13,
            stroke="#8c5a2b",
            stroke_width=1.5,
            layer="symbol",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + 0.468,
            y=y + 0.145,
            width=0,
            height=0.13,
            stroke="#8c5a2b",
            stroke_width=1.5,
            layer="symbol",
        ))
        for offset in (0.02, 0.045, 0.07, 0.095):
            graphic.elements.append(GraphicElement(
                element_type="line",
                x=x + 0.34,
                y=y + 0.15 + offset,
                width=0.1,
                height=0,
                stroke="#c2410c",
                stroke_width=1.6,
                layer="symbol",
            ))
        graphic.elements.append(GraphicElement(
            element_type="line",
            x=x + 0.02,
            y=y + 0.215,
            width=width - 0.04,
            height=0,
            stroke="#1976d2",
            stroke_width=3.5,
            layer="symbol",
            css_class="airflow-path airflow-supply",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect",
            x=x + 0.54,
            y=y + 0.16,
            width=0.11,
            height=0.06,
            fill="url(#equipment-base-gradient)",
            stroke="#6b7280",
            stroke_width=0.8,
            layer="symbol",
            css_class="control-enclosure",
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

        planned_points = []
        for point in points:
            binding_type = self._binding_type_for_point(point)
            component = self._classify_point_component(point, equip.type)
            planned_points.append((point, binding_type, component))

        planned_points.sort(
            key=lambda item: (
                self._component_sort_key(item[2]),
                self._binding_type_priority(item[1]),
                item[0].name,
            )
        )

        for point, binding_type, component in planned_points:
            x, y = self._binding_position_for_point(point, component, anchors, component_counters, fallback_counters)
            binding = GraphicBinding(
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
            )
            graphic.bindings.append(binding)
            self._record_asset_point_relation(
                graphic,
                point=point,
                binding=binding,
                component=component,
                equipment_id=equip.id,
            )

    def _record_asset_point_relation(
        self,
        graphic: GraphicDefinition,
        *,
        point: Point,
        binding: GraphicBinding,
        component: str | None,
        equipment_id: str,
    ) -> None:
        relation = self._build_asset_point_relation(
            graphic,
            point=point,
            binding=binding,
            component=component,
            equipment_id=equipment_id,
        )
        if relation is None:
            return
        relations = graphic.metadata.setdefault("asset_point_relations", [])
        relations.append(relation)

    def _record_graphics_inference(
        self,
        graphic: GraphicDefinition,
        *,
        key: str,
        value: object,
        source: str,
        confidence: float,
        evidence: list[str] | None = None,
    ) -> None:
        inferences = graphic.metadata.setdefault("graphics_inference", {})
        inferences[key] = {
            "value": value,
            "source": source,
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
            "evidence": list(evidence or []),
        }

    def _append_graphics_issue(
        self,
        graphic: GraphicDefinition,
        *,
        severity: str,
        code: str,
        detail: str,
        point_name: str | None = None,
    ) -> None:
        issues = graphic.metadata.setdefault("graphics_issues", [])
        issues.append(
            {
                "severity": severity,
                "code": code,
                "detail": detail,
                "point_name": point_name or "",
            }
        )

    def _finalize_graphic_confidence(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
    ) -> None:
        relations = list(graphic.metadata.get("asset_point_relations") or [])
        relation_by_point = {str(item.get("point_name") or ""): item for item in relations}
        classified_points = 0
        low_confidence_points = 0
        for point in points:
            component = self._classify_point_component(point, equip.type)
            if component:
                classified_points += 1
            else:
                self._append_graphics_issue(
                    graphic,
                    severity="warning",
                    code="unclassified_point",
                    detail="Point name did not map cleanly to a known graphic component.",
                    point_name=point.name,
                )
            relation = relation_by_point.get(point.name)
            if relation and not relation.get("target_key"):
                low_confidence_points += 1
                self._append_graphics_issue(
                    graphic,
                    severity="info",
                    code="weak_asset_relation",
                    detail="Point was placed on the graphic but did not resolve to a specific asset binding target.",
                    point_name=point.name,
                )

        inferences = graphic.metadata.get("graphics_inference") or {}
        inference_confidences = [
            float(item.get("confidence", 0.0))
            for item in inferences.values()
            if isinstance(item, dict)
        ]
        inference_average = (
            sum(inference_confidences) / len(inference_confidences)
            if inference_confidences
            else 0.85
        )
        total_points = len(points)
        classification_ratio = (classified_points / total_points) if total_points else 1.0
        relation_ratio = ((total_points - low_confidence_points) / total_points) if total_points else 1.0
        score = (inference_average * 0.4) + (classification_ratio * 0.35) + (relation_ratio * 0.25)
        graphic.metadata["graphics_confidence"] = {
            "score": round(max(0.0, min(1.0, score)), 2),
            "total_points": total_points,
            "classified_points": classified_points,
            "unclassified_points": total_points - classified_points,
            "weak_relations": low_confidence_points,
            "inference_count": len(inference_confidences),
        }

    def _build_asset_point_relation(
        self,
        graphic: GraphicDefinition,
        *,
        point: Point,
        binding: GraphicBinding,
        component: str | None,
        equipment_id: str,
    ) -> dict[str, object] | None:
        placements = list(graphic.metadata.get("asset_placements") or [])
        if not placements:
            return None

        best_match: tuple[float, dict[str, object], object | None, object | None] | None = None
        for placement in placements:
            placement_equipment_id = str(placement.get("equipment_id") or "")
            if placement_equipment_id and placement_equipment_id not in {equipment_id, point.equipment_id}:
                continue

            asset = self.asset_library.get(str(placement.get("asset_id") or ""))
            role = str(placement.get("role") or "")
            role_match = self._role_matches_component(role, component)

            target_match = None
            target_score = 0.0
            anchor = None
            if asset is not None:
                for target in asset.binding_targets:
                    score = 0.0
                    component_matches_target = False
                    if component and target.component == component:
                        score += 10.0
                        component_matches_target = True
                    elif component and component in target.component:
                        score += 6.0
                        component_matches_target = True
                    if not component_matches_target:
                        continue
                    if binding.binding_type.value in target.binding_types:
                        score += 3.0
                    if point.kind.value in target.preferred_point_kinds:
                        score += 2.0
                    if score > target_score:
                        target_score = score
                        target_match = target
                if target_match is not None:
                    anchor = next(
                        (item for item in asset.anchor_points if item.key == target_match.anchor_key),
                        None,
                    )

            placement_score = 0.0
            if placement_equipment_id == point.equipment_id:
                placement_score += 4.0
            if role_match:
                placement_score += 5.0
            if role.startswith("section:") and component:
                placement_score += 1.5
            if role == "primary_equipment":
                placement_score += 1.0
            score = placement_score + target_score
            if score <= 0:
                continue
            if best_match is None or score > best_match[0]:
                best_match = (score, placement, target_match, anchor)

        if best_match is None:
            return None

        _, placement, target_match, anchor = best_match
        px = float(placement.get("x") or 0)
        py = float(placement.get("y") or 0)
        pw = float(placement.get("width") or 0)
        ph = float(placement.get("height") or 0)
        relation_x = binding.x
        relation_y = binding.y
        if anchor is not None:
            relation_x = px + (pw * anchor.x)
            relation_y = py + (ph * anchor.y)

        return {
            "asset_id": str(placement.get("asset_id") or ""),
            "asset_role": str(placement.get("role") or ""),
            "equipment_id": str(placement.get("equipment_id") or equipment_id),
            "point_name": point.name,
            "point_kind": point.kind.value,
            "point_direction": point.direction.value,
            "binding_type": binding.binding_type.value,
            "component": component or "",
            "target_key": target_match.key if target_match is not None else "",
            "target_component": target_match.component if target_match is not None else "",
            "anchor_key": anchor.key if anchor is not None else "",
            "anchor_role": anchor.role if anchor is not None else "",
            "target_description": target_match.description if target_match is not None else "",
            "asset_x": px,
            "asset_y": py,
            "asset_width": pw,
            "asset_height": ph,
            "relation_x": relation_x,
            "relation_y": relation_y,
            "binding_x": binding.x,
            "binding_y": binding.y,
            "label": binding.label or point.name,
            "units": point.units or "",
            "visual_hint": self._visual_hint_for_component(component, binding.binding_type),
            "relation_kind": self._relation_kind_for_binding(binding.binding_type),
        }

    def _role_matches_component(self, role: str, component: str | None) -> bool:
        if role == "primary_equipment":
            return component is None
        if not component:
            return False
        section_component_map = {
            "section:outside_air": {"outside_damper", "return_damper", "outside_temp", "mixed_temp", "damper"},
            "section:mixed_air": {"outside_damper", "return_damper", "mixed_temp", "return_temp", "damper"},
            "section:filter": {"filter", "static_pressure"},
            "section:cooling_coil": {"cooling_coil", "cooling_valve"},
            "section:heating_coil": {"heating_coil", "heating_valve", "reheat_valve"},
            "section:humidifier": {"humidity"},
            "section:energy_recovery": {"energy_recovery"},
            "section:uv": {"uv"},
            "section:supply_fan": {"supply_fan", "status", "static_pressure"},
            "section:return_fan": {"return_fan", "return_temp"},
            "section:relief_fan": {"relief_fan", "exhaust_damper"},
            "section:discharge": {"supply_temp", "discharge_temp", "airflow", "static_pressure"},
            "internal_supply_path": {"airflow", "supply_temp", "discharge_temp", "static_pressure"},
            "supply_trunk": {"airflow", "supply_temp", "discharge_temp", "static_pressure"},
            "branch_takeoff": {"airflow"},
            "terminal_unit": {"damper", "reheat_valve", "heating_coil", "discharge_temp", "supply_temp", "airflow"},
        }
        return component in section_component_map.get(role, set())

    def _visual_hint_for_component(self, component: str | None, binding_type: BindingType) -> str:
        if component in {"supply_fan", "return_fan", "relief_fan"}:
            return "fan_spin"
        if component in {"outside_damper", "return_damper", "exhaust_damper", "damper"}:
            return "damper_position"
        if component in {"cooling_valve", "heating_valve", "reheat_valve"}:
            return "valve_position"
        if component in {"cooling_coil", "heating_coil", "humidity"}:
            return "thermal_state"
        if component == "energy_recovery":
            return "wheel_rotation"
        if component == "uv":
            return "uv_bank_state"
        if component in {"airflow", "static_pressure"}:
            return "flow_path"
        if binding_type == BindingType.ALARM:
            return "alarm_state"
        if binding_type == BindingType.STATUS:
            return "status_state"
        return "value_readout"

    def _relation_kind_for_binding(self, binding_type: BindingType) -> str:
        if binding_type == BindingType.COMMAND:
            return "control_output"
        if binding_type == BindingType.STATUS:
            return "operational_state"
        if binding_type == BindingType.SETPOINT:
            return "control_target"
        if binding_type == BindingType.ALARM:
            return "fault_indicator"
        return "telemetry"

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

    def _binding_type_priority(self, binding_type: BindingType) -> int:
        order = {
            BindingType.ALARM: 0,
            BindingType.STATUS: 1,
            BindingType.COMMAND: 2,
            BindingType.SETPOINT: 3,
            BindingType.VALUE: 4,
            BindingType.TREND: 5,
            BindingType.OVERRIDE: 6,
        }
        return order.get(binding_type, 99)

    def _component_sort_key(self, component: str | None) -> tuple[int, str]:
        if component is None:
            return (99, "")
        order = {
            "outside_temp": 0,
            "outside_damper": 1,
            "mixed_temp": 2,
            "return_damper": 3,
            "filter": 4,
            "static_pressure": 5,
            "cooling_valve": 6,
            "cooling_coil": 7,
            "heating_valve": 8,
            "heating_coil": 9,
            "humidity": 10,
            "uv": 11,
            "energy_recovery": 12,
            "supply_fan": 13,
            "return_fan": 14,
            "relief_fan": 15,
            "airflow": 16,
            "supply_temp": 17,
            "discharge_temp": 18,
            "return_temp": 19,
            "room_temp": 20,
        }
        return (order.get(component, 90), component)

    def _label_for_point(self, point: Point) -> str:
        display_name = self._display_name_for_point(point)
        if point.kind == PointKind.ALARM:
            return f"ALM {display_name}"
        return display_name

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
        if equipment_type == EquipmentType.COOLING_TOWER and any(
            keyword in normalized for keyword in ("cell fan", "tower fan", "fan cyl", "fan proof")
        ):
            return "supply_fan"
        if equipment_type in {EquipmentType.CHILLER, EquipmentType.BOILER, EquipmentType.PUMP_HW, EquipmentType.PUMP_CHW, EquipmentType.PUMP_CW}:
            if any(keyword in normalized for keyword in ("lwt", "leaving water", "supply water", "chws", "hws", "cws")):
                return "supply_temp"
            if any(keyword in normalized for keyword in ("ewt", "entering water", "return water", "chwr", "hwr", "cwr")):
                return "return_temp"
        if any(keyword in normalized for keyword in ("filter", "filt", "flt")) and any(
            keyword in normalized for keyword in ("dp", "differential pressure", "diff pressure", "dirty")
        ):
            return "filter"
        preferred_component_order = (
            "discharge_temp",
            "supply_temp",
            "mixed_temp",
            "return_temp",
            "outside_temp",
            "cooling_valve",
            "heating_valve",
            "reheat_valve",
            "outside_damper",
            "return_damper",
            "exhaust_damper",
            "damper",
            "supply_fan",
            "return_fan",
            "cooling_coil",
            "heating_coil",
            "filter",
            "static_pressure",
            "airflow",
            "humidity",
            "room_temp",
            "uv",
            "energy_recovery",
        )
        for component in preferred_component_order:
            keywords = self.COMPONENT_KEYWORDS.get(component, ())
            if any(keyword in normalized for keyword in keywords):
                return component
        return None

    def _display_name_for_point(self, point: Point) -> str:
        equipment_id = (point.equipment_id or "").strip()
        name = point.name.strip()
        if not equipment_id:
            return name

        normalized_name = name.replace("_", " ").strip()
        normalized_equipment = equipment_id.replace("_", " ").strip()
        if normalized_name == normalized_equipment:
            return name
        if normalized_name.startswith(normalized_equipment + " "):
            trimmed = normalized_name[len(normalized_equipment):].strip(" -_/")
            if trimmed:
                return trimmed
        return name

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
        self._record_asset_placement(
            graphic,
            asset_id="ahu_drawthrough_doubledeck",
            x=0.05,
            y=0.16,
            width=0.44,
            height=0.56,
            role="primary_equipment",
            equipment_id=ahu.id,
        )
        graphic.elements.append(GraphicElement(
            element_type="rect", x=0.05, y=0.16, width=0.44, height=0.56,
            fill="url(#equipment-shell-gradient)", stroke="#5b5b57", stroke_width=2.2, layer="equipment",
            css_class="equipment-shell",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect", x=0.06, y=0.18, width=0.42, height=0.52,
            fill="url(#equipment-face-gradient)", stroke="#9aa0a6", stroke_width=1, layer="equipment",
            css_class="equipment-face",
        ))
        graphic.elements.append(GraphicElement(
            element_type="rect", x=0.49, y=0.405, width=0.17, height=0.07,
            fill="url(#duct-body-gradient)", stroke="#6b7280", stroke_width=1.2, layer="piping",
            css_class="duct-shell",
        ))
        self._record_asset_placement(
            graphic,
            asset_id="rectangular_supply_duct",
            x=0.49,
            y=0.405,
            width=0.17,
            height=0.07,
            role="supply_trunk",
            equipment_id=ahu.id,
        )
        graphic.elements.append(GraphicElement(
            element_type="rect", x=0.497, y=0.421, width=0.156, height=0.038,
            fill="url(#duct-liner-gradient)", stroke="#a1a1aa", stroke_width=0.7, layer="piping",
            css_class="duct-liner",
        ))
        self._append_ahu_duct_stub(graphic, x=0.015, y=0.37, width=0.035, height=0.14, louver=True)
        self._append_filter_symbol(graphic, x=0.12, y=0.28, width=0.05, height=0.28, stroke="#64748b")
        self._append_coil_symbol(graphic, x=0.21, y=0.26, width=0.07, height=0.32, stroke="#1976d2")
        self._append_coil_symbol(graphic, x=0.29, y=0.26, width=0.06, height=0.32, stroke="#ef6c00")
        self._append_fan_symbol(graphic, x=0.40, y=0.44, size=0.12, stroke="#6b7280")
        graphic.elements.append(GraphicElement(
            element_type="text", x=0.27, y=0.77, text=ahu.id,
            font_size=16, layer="labels",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line", x=0.49, y=0.44, width=0.17, height=0,
            stroke="#1976d2", stroke_width=4, layer="piping",
            css_class="airflow-path airflow-supply",
        ))

        # VAV boxes along duct
        for i, vav in enumerate(children):
            y = 0.2 + (i * 0.6 / max(len(children), 1))
            box_y = y
            graphic.elements.append(GraphicElement(
                element_type="rect", x=0.69, y=box_y, width=0.17, height=0.11,
                fill="url(#equipment-shell-gradient)", stroke="#6b7280", stroke_width=1.4, layer="equipment",
                css_class="vav-shell",
            ))
            graphic.elements.append(GraphicElement(
                element_type="rect", x=0.70, y=box_y + 0.01, width=0.15, height=0.09,
                fill="url(#equipment-face-gradient)", stroke="#cbd5e1", stroke_width=0.8, layer="equipment",
                css_class="vav-face",
            ))
            graphic.elements.append(GraphicElement(
                element_type="rect", x=0.65, y=y + 0.026, width=0.05, height=0.048,
                fill="url(#duct-body-gradient)", stroke="#6b7280", stroke_width=1, layer="piping",
                css_class="duct-shell",
            ))
            self._record_asset_placement(
                graphic,
                asset_id="rectangular_supply_duct",
                x=0.65,
                y=y + 0.026,
                width=0.05,
                height=0.048,
                role="branch_takeoff",
                equipment_id=vav.id,
            )
            self._record_asset_placement(
                graphic,
                asset_id="vav_reheat_terminal",
                x=0.69,
                y=box_y,
                width=0.17,
                height=0.11,
                role="terminal_unit",
                equipment_id=vav.id,
            )
            self._append_damper_symbol(graphic, x=0.712, y=box_y + 0.03, width=0.032, height=0.045, stroke="#64748b")
            self._append_coil_symbol(graphic, x=0.762, y=box_y + 0.03, width=0.05, height=0.045, stroke="#ef6c00")
            graphic.elements.append(GraphicElement(
                element_type="text", x=0.775, y=box_y + 0.13, text=vav.id,
                font_size=9, layer="labels",
            ))
            graphic.elements.append(GraphicElement(
                element_type="line", x=0.65, y=y + 0.05, width=0.05, height=0,
                stroke="#1976d2", stroke_width=2, layer="piping",
                css_class="airflow-path airflow-supply airflow-branch",
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
            element_type="rect", x=0.49, y=0.545, width=0.14, height=0.065,
            fill="url(#return-duct-gradient)", stroke="#7c2d12", stroke_width=1.1, layer="piping",
            css_class="duct-shell",
        ))
        graphic.elements.append(GraphicElement(
            element_type="line", x=0.49, y=0.58, width=0.14, height=0,
            stroke="#ef6c00", stroke_width=3, layer="piping",
            css_class="airflow-path airflow-return",
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
                    "css_class": e.css_class,
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
            "  <defs>",
            self._svg_visual_defs(),
            "    <style>",
            self._svg_animation_styles(),
            "    </style>",
            "  </defs>",
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

        # Bindings as station widgets
        lines.append('  <g class="layer-bindings">')
        for index, binding in enumerate(graphic.bindings):
            lines.append(self._binding_to_svg(binding, graphic.width, graphic.height, index))
        lines.append('  </g>')

        lines.append('</svg>')
        return "\n".join(lines)

    def _binding_to_svg(self, binding: GraphicBinding, width: int, height: int, index: int) -> str:
        px = binding.x * width
        py = binding.y * height
        label = escape(binding.label or binding.point_name)
        widget_id = escape(binding.point_name.replace(" ", "_"), quote=True)
        color = self._binding_widget_color(binding.binding_type)
        value_text = escape(self._binding_sample_value(binding))
        card_w = min(max(86 + (len(label) * 4), 126), 220)
        card_h = 34 if binding.binding_type in {BindingType.STATUS, BindingType.ALARM, BindingType.COMMAND} else 38
        dx, dy = self._binding_widget_offset(index, binding.binding_type)
        card_x = px + dx
        card_y = py + dy
        icon = self._binding_widget_icon(binding.binding_type, card_x=card_x, card_y=card_y, card_w=card_w, card_h=card_h)
        anchor_x = card_x if dx >= 0 else card_x + card_w
        anchor_y = card_y + (card_h / 2)
        angle = math.degrees(math.atan2(anchor_y - py, anchor_x - px))
        line_len = math.hypot(anchor_x - px, anchor_y - py)

        return f"""
    <g class="station-widget station-widget-{binding.binding_type.value}" data-point="{escape(binding.point_name, quote=True)}" data-type="{binding.binding_type.value}" data-widget="{widget_id}">
      <circle cx="{px:.2f}" cy="{py:.2f}" r="5.5" fill="{color}" stroke="#f8fafc" stroke-width="2" class="station-widget-anchor" />
      <line x1="{px:.2f}" y1="{py:.2f}" x2="{anchor_x:.2f}" y2="{anchor_y:.2f}" stroke="#475569" stroke-width="1.25" stroke-linecap="round" class="station-widget-lead" data-angle="{angle:.2f}" data-length="{line_len:.2f}" />
      <rect x="{card_x:.2f}" y="{card_y:.2f}" width="{card_w:.2f}" height="{card_h:.2f}" rx="8" fill="rgba(248,250,252,0.96)" stroke="#475569" stroke-width="1" class="station-widget-card" />
      <rect x="{card_x + 1.5:.2f}" y="{card_y + 1.5:.2f}" width="{card_w - 3:.2f}" height="12" rx="6" fill="rgba(226,232,240,0.95)" class="station-widget-header" />
      <circle cx="{card_x + 9:.2f}" cy="{card_y + 7.5:.2f}" r="3.5" fill="{color}" class="station-widget-dot" />
      <text x="{card_x + 17:.2f}" y="{card_y + 8.8:.2f}" font-size="8.5" font-family="Arial" fill="#334155" font-weight="700" class="station-widget-label">{label}</text>
      <text x="{card_x + card_w - 8:.2f}" y="{card_y + 8.8:.2f}" text-anchor="end" font-size="8" font-family="Arial" fill="#64748b" font-weight="700" class="station-widget-kind">{binding.binding_type.value.upper()}</text>
      {icon}
      <text x="{card_x + 26:.2f}" y="{card_y + 25.5:.2f}" font-size="12" font-family="Arial" fill="#0f172a" font-weight="700" class="station-widget-value">{value_text}</text>
    </g>
        """.strip()

    def _binding_widget_offset(self, index: int, binding_type: BindingType) -> tuple[float, float]:
        cycles = {
            BindingType.VALUE: ((14, -48), (14, 14), (-170, -48), (-170, 14)),
            BindingType.SETPOINT: ((18, -54), (-176, -54), (18, 18), (-176, 18)),
            BindingType.STATUS: ((16, -42), (16, 10), (-160, -42), (-160, 10)),
            BindingType.ALARM: ((18, -40), (-164, -40), (18, 10), (-164, 10)),
            BindingType.COMMAND: ((18, 12), (-164, 12), (18, -46), (-164, -46)),
        }
        options = cycles.get(binding_type, ((14, -48), (14, 14), (-170, -48), (-170, 14)))
        return options[index % len(options)]

    def _binding_widget_color(self, binding_type: BindingType) -> str:
        color_map = {
            BindingType.VALUE: "#1d4ed8",
            BindingType.SETPOINT: "#7c3aed",
            BindingType.STATUS: "#059669",
            BindingType.ALARM: "#dc2626",
            BindingType.COMMAND: "#b45309",
            BindingType.TREND: "#0891b2",
            BindingType.OVERRIDE: "#6b7280",
        }
        return color_map.get(binding_type, "#1d4ed8")

    def _binding_widget_icon(self, binding_type: BindingType, *, card_x: float, card_y: float, card_w: float, card_h: float) -> str:
        if binding_type == BindingType.STATUS:
            return f'<circle cx="{card_x + card_w - 16:.2f}" cy="{card_y + 24:.2f}" r="5.5" fill="#bbf7d0" stroke="#059669" stroke-width="1.2" class="station-status-lamp" />'
        if binding_type == BindingType.ALARM:
            return f'<polygon points="{card_x + card_w - 22:.2f},{card_y + 28:.2f} {card_x + card_w - 10:.2f},{card_y + 28:.2f} {card_x + card_w - 16:.2f},{card_y + 17:.2f}" fill="#fee2e2" stroke="#dc2626" stroke-width="1" class="station-alarm-glyph" />'
        if binding_type == BindingType.COMMAND:
            return f'<rect x="{card_x + card_w - 28:.2f}" y="{card_y + 18:.2f}" width="16" height="10" rx="3" fill="#ffedd5" stroke="#b45309" stroke-width="1" class="station-command-glyph" />'
        if binding_type == BindingType.SETPOINT:
            return f'<path d="M {card_x + card_w - 22:.2f} {card_y + 28:.2f} L {card_x + card_w - 16:.2f} {card_y + 18:.2f} L {card_x + card_w - 10:.2f} {card_y + 28:.2f}" fill="none" stroke="#7c3aed" stroke-width="1.4" class="station-setpoint-glyph" />'
        return f'<rect x="{card_x + card_w - 26:.2f}" y="{card_y + 18:.2f}" width="14" height="12" rx="3" fill="#dbeafe" stroke="#1d4ed8" stroke-width="1" class="station-value-glyph" />'

    def _binding_sample_value(self, binding: GraphicBinding) -> str:
        if binding.binding_type == BindingType.STATUS:
            return "ON"
        if binding.binding_type == BindingType.ALARM:
            return "NORMAL"
        if binding.binding_type == BindingType.COMMAND:
            return "AUTO"
        if binding.binding_type == BindingType.SETPOINT:
            if binding.format == ".0f":
                return "55"
            return "55.0"
        if binding.format == ".0f":
            return "72"
        if binding.format == ".2f":
            return "1.65"
        return "55.2"

    def _element_to_svg(self, elem: GraphicElement, width: int, height: int) -> str:
        """Convert element to SVG."""
        px = elem.x * width
        py = elem.y * height
        pw = elem.width * width
        ph = elem.height * height
        class_attr = f' class="{escape(elem.css_class, quote=True)}" ' if elem.css_class else ""

        if elem.element_type == "rect":
            return (f'    <rect x="{px}" y="{py}" width="{pw}" height="{ph}" '
                    f'{class_attr}'
                    f'fill="{elem.fill or "none"}" stroke="{elem.stroke or "none"}" '
                    f'stroke-width="{elem.stroke_width}"/>')
        if elem.element_type == "circle":
            r = pw / 2
            return (f'    <circle cx="{px}" cy="{py}" r="{r}" '
                    f'{class_attr}'
                    f'fill="{elem.fill or "none"}" stroke="{elem.stroke or "none"}" '
                    f'stroke-width="{elem.stroke_width}"/>')
        if elem.element_type == "ellipse":
            rx = pw / 2
            ry = ph / 2
            return (f'    <ellipse cx="{px}" cy="{py}" rx="{rx}" ry="{ry}" '
                    f'{class_attr}'
                    f'fill="{elem.fill or "none"}" stroke="{elem.stroke or "none"}" '
                    f'stroke-width="{elem.stroke_width}"/>')
        if elem.element_type == "line":
            x2 = px + pw
            y2 = py + ph
            return (f'    <line x1="{px}" y1="{py}" x2="{x2}" y2="{y2}" '
                    f'{class_attr}'
                    f'stroke="{elem.stroke or "black"}" stroke-width="{elem.stroke_width}"/>')
        if elem.element_type == "text":
            return (f'    <text x="{px}" y="{py}" '
                    f'{class_attr}'
                    f'font-size="{elem.font_size}" font-family="{elem.font_family}" '
                    f'text-anchor="middle" dominant-baseline="middle">{escape(elem.text or "")}</text>')
        return ""

    def _svg_animation_styles(self) -> str:
        """Shared SVG animation styles for station-style motion cues."""
        return """
      .equipment-shell, .duct-shell, .fan-shell, .fan-housing, .coil-face, .filter-bank, .damper-frame, .vav-shell {
        filter: url(#soft-shadow);
      }
      .equipment-face, .duct-liner, .vav-face, .section-bay {
        filter: url(#inner-depth);
      }
      .equipment-panel, .panel-handle, .fan-base, .equipment-topcap, .equipment-base, .control-enclosure {
        filter: url(#metal-shadow);
      }
      .fan-shell, .fan-housing {
        filter: url(#metal-shadow);
      }
      .filter-bank, .coil-face {
        opacity: 0.96;
      }
      .airflow-path {
        opacity: 0.9;
      }
      .fan-blade {
        transform-box: fill-box;
        transform-origin: center;
        animation: fan-spin 1.1s linear infinite;
      }
      .motor-body {
        animation: motor-pulse 1.8s ease-in-out infinite;
      }
      .airflow-path {
        stroke-linecap: round;
        stroke-dasharray: 16 12;
      }
      .airflow-supply {
        animation: airflow-forward 1.3s linear infinite;
      }
      .airflow-return {
        animation: airflow-reverse 1.6s linear infinite;
      }
      .airflow-branch {
        stroke-dasharray: 10 8;
      }
      @keyframes fan-spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }
      @keyframes motor-pulse {
        0% { opacity: 0.75; }
        50% { opacity: 1; }
        100% { opacity: 0.75; }
      }
      @keyframes airflow-forward {
        from { stroke-dashoffset: 0; }
        to { stroke-dashoffset: -28; }
      }
      @keyframes airflow-reverse {
        from { stroke-dashoffset: 0; }
        to { stroke-dashoffset: 28; }
      }
        """.strip()

    def _svg_visual_defs(self) -> str:
        """SVG defs for more dimensional equipment rendering."""
        return """
    <linearGradient id="equipment-shell-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#f4f5f7"/>
      <stop offset="45%" stop-color="#c8ccd1"/>
      <stop offset="100%" stop-color="#8a9199"/>
    </linearGradient>
    <linearGradient id="equipment-face-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#fdfdfd"/>
      <stop offset="55%" stop-color="#d8dee5"/>
      <stop offset="100%" stop-color="#bcc4ce"/>
    </linearGradient>
    <linearGradient id="equipment-topcap-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#cfd6dd"/>
    </linearGradient>
    <linearGradient id="equipment-base-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#a4adb7"/>
      <stop offset="100%" stop-color="#5f6873"/>
    </linearGradient>
    <linearGradient id="duct-body-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#d5dae0"/>
      <stop offset="50%" stop-color="#a2aab3"/>
      <stop offset="100%" stop-color="#6b7280"/>
    </linearGradient>
    <linearGradient id="duct-liner-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#384252"/>
      <stop offset="100%" stop-color="#111827"/>
    </linearGradient>
    <linearGradient id="return-duct-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#fed7aa"/>
      <stop offset="55%" stop-color="#fb923c"/>
      <stop offset="100%" stop-color="#9a3412"/>
    </linearGradient>
    <linearGradient id="coil-face-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#f0f9ff"/>
      <stop offset="50%" stop-color="#93c5fd"/>
      <stop offset="100%" stop-color="#1d4ed8"/>
    </linearGradient>
    <linearGradient id="filter-face-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#f8fafc"/>
      <stop offset="100%" stop-color="#cbd5e1"/>
    </linearGradient>
    <linearGradient id="damper-frame-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#eef2f7"/>
      <stop offset="100%" stop-color="#94a3b8"/>
    </linearGradient>
    <linearGradient id="fan-wheel-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="60%" stop-color="#cbd5e1"/>
      <stop offset="100%" stop-color="#64748b"/>
    </linearGradient>
    <linearGradient id="fan-housing-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#f3f4f6"/>
      <stop offset="100%" stop-color="#9ca3af"/>
    </linearGradient>
    <linearGradient id="motor-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#d1d5db"/>
      <stop offset="100%" stop-color="#4b5563"/>
    </linearGradient>
    <linearGradient id="section-bay-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#94a3b8" stop-opacity="0.04"/>
    </linearGradient>
    <filter id="soft-shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="6" stdDeviation="6" flood-color="#0f172a" flood-opacity="0.18"/>
    </filter>
    <filter id="metal-shadow" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#0f172a" flood-opacity="0.22"/>
    </filter>
    <filter id="inner-depth" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="1" stdDeviation="1.2" flood-color="#ffffff" flood-opacity="0.35"/>
    </filter>
        """.strip()

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
    engine = ValidationEngine()
    engine.validate(project)

    json_paths = generator.to_json(output_dir / "graphics_json")
    svg_paths = generator.to_svg(output_dir / "graphics_svg")
    niagara_path = generator.to_niagara_json(output_dir / "graphics_niagara.json")
    summaries = []
    for graphic in generator.graphics.values():
        equipment_id = graphic.equipment_id or ""
        equipment = project.get_equipment(equipment_id) if equipment_id else None
        sequence_review = (
            engine.sequence_coverage_for_equipment(project, equipment_id)
            if equipment_id
            else {
                "status": "not_indexed",
                "missing_refs": [],
                "missing_families": [],
                "summary": "",
            }
        )
        summaries.append(
            {
                "graphic_id": graphic.graphic_id,
                "equipment_id": equipment_id,
                "graphic_type": graphic.graphic_type.value,
                "sequence_reference": equipment.sequence_ref if equipment and equipment.sequence_ref else "",
                "sequence_review_status": sequence_review.get("status", "not_indexed"),
                "sequence_missing_refs": list(sequence_review.get("missing_refs") or []),
                "sequence_missing_families": list(sequence_review.get("missing_families") or []),
                "sequence_summary": sequence_review.get("summary", ""),
                "graphic_sections": list(graphic.metadata.get("graphic_sections") or []),
            }
        )

    return {
        "json": json_paths,
        "svg": svg_paths,
        "niagara": niagara_path,
        "summaries": summaries,
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
