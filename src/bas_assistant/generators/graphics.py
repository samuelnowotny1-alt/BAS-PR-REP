"""Graphics generator - graphics definitions, bindings, SVG/JSON output."""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
import json

from ..models import Project, Equipment, Point, PointKind, EquipmentType


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
    label: Optional[str] = None
    format: Optional[str] = None  # e.g., ".1f", ".0f", "on/off"
    color_map: Optional[dict] = None  # For status/alarm colors
    min_max: Optional[tuple[float, float]] = None  # For trends/bars


@dataclass
class GraphicElement:
    """A graphic element (symbol, text, shape)."""

    element_type: str  # rect, circle, line, text, image, symbol
    x: float
    y: float
    width: float = 0
    height: float = 0
    rotation: float = 0
    fill: Optional[str] = None
    stroke: Optional[str] = None
    stroke_width: float = 1
    text: Optional[str] = None
    font_size: float = 12
    font_family: str = "Arial"
    symbol_name: Optional[str] = None  # For predefined symbols
    point_binding: Optional[GraphicBinding] = None
    layer: str = "default"


@dataclass
class GraphicDefinition:
    """Complete graphic definition."""

    graphic_id: str
    name: str
    graphic_type: GraphicType
    equipment_id: Optional[str] = None
    width: int = 1200
    height: int = 800
    background: str = "white"
    elements: list[GraphicElement] = field(default_factory=list)
    bindings: list[GraphicBinding] = field(default_factory=list)
    navigation: list[str] = field(default_factory=list)  # Links to other graphics
    metadata: dict = field(default_factory=dict)


class GraphicsGenerator:
    """Generates graphics definitions from project data."""

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

        # Use template or generic
        if symbol_key in self.SYMBOLS:
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
        elif elem_type == "circle":
            return GraphicElement(
                element_type="circle",
                x=elem_data["x"], y=elem_data["y"],
                width=elem_data["radius"] * 2, height=elem_data["radius"] * 2,
                fill=elem_data.get("fill"), stroke=elem_data.get("stroke"),
                stroke_width=elem_data.get("stroke_width", 1),
                layer="symbol",
            )
        elif elem_type == "ellipse":
            return GraphicElement(
                element_type="ellipse",
                x=elem_data["x"], y=elem_data["y"],
                width=elem_data["width"], height=elem_data["height"],
                fill=elem_data.get("fill"), stroke=elem_data.get("stroke"),
                stroke_width=elem_data.get("stroke_width", 1),
                layer="symbol",
            )
        elif elem_type == "line":
            return GraphicElement(
                element_type="line",
                x=elem_data["x1"], y=elem_data["y1"],
                width=elem_data["x2"] - elem_data["x1"],
                height=elem_data["y2"] - elem_data["y1"],
                stroke=elem_data.get("stroke", "#333"),
                stroke_width=elem_data.get("stroke_width", 1),
                layer="symbol",
            )
        elif elem_type == "text":
            return GraphicElement(
                element_type="text",
                x=elem_data["x"], y=elem_data["y"],
                text=elem_data["text"].format(name=equip_id),
                font_size=elem_data.get("font_size", 12),
                font_family=elem_data.get("font_family", "Arial"),
                layer="labels",
            )
        else:
            return GraphicElement(element_type="rect", x=0, y=0, layer="symbol")

    def _add_point_bindings(
        self,
        graphic: GraphicDefinition,
        equip: Equipment,
        points: list[Point],
    ) -> None:
        """Add point bindings around equipment symbol."""
        # Group points by kind for layout
        sensors = [p for p in points if p.kind == PointKind.SENSOR]
        actuators = [p for p in points if p.kind == PointKind.ACTUATOR]
        setpoints = [p for p in points if p.kind == PointKind.SETPOINT]
        status = [p for p in points if p.kind == PointKind.STATUS]
        alarms = [p for p in points if p.kind == PointKind.ALARM]

        # Layout positions around symbol (normalized coordinates)
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
            graphic.bindings.append(GraphicBinding(
                point_name=point.name,
                binding_type=BindingType.VALUE,
                x=x, y=y,
                label=point.name,
                format=self._get_format(point),
                min_max=(point.range_min, point.range_max) if point.range_min is not None and point.range_max is not None else None,
            ))

        # Add actuator bindings (right side)
        for i, point in enumerate(actuators):
            pos = positions["actuators"]
            x = pos["start"][0] + i * pos["step"][0]
            y = pos["start"][1] + i * pos["step"][1]
            graphic.bindings.append(GraphicBinding(
                point_name=point.name,
                binding_type=BindingType.COMMAND if point.direction.value == "output" else BindingType.VALUE,
                x=x, y=y,
                label=point.name,
                format=self._get_format(point),
            ))

        # Add setpoint bindings (top)
        for i, point in enumerate(setpoints):
            pos = positions["setpoints"]
            x = pos["start"][0] + i * pos["step"][0]
            y = pos["start"][1] + i * pos["step"][1]
            graphic.bindings.append(GraphicBinding(
                point_name=point.name,
                binding_type=BindingType.SETPOINT,
                x=x, y=y,
                label=point.name,
                format=self._get_format(point),
            ))

        # Add status bindings (bottom)
        for i, point in enumerate(status):
            pos = positions["status"]
            x = pos["start"][0] + i * pos["step"][0]
            y = pos["start"][1] + i * pos["step"][1]
            graphic.bindings.append(GraphicBinding(
                point_name=point.name,
                binding_type=BindingType.STATUS,
                x=x, y=y,
                label=point.name,
                format="on/off",
                color_map={"on": "#4caf50", "off": "#f44336", "open": "#4caf50", "closed": "#f44336"},
            ))

        # Add alarm bindings (bottom-left)
        for i, point in enumerate(alarms):
            pos = positions["alarms"]
            x = pos["start"][0] + i * pos["step"][0]
            y = pos["start"][1] + i * pos["step"][1]
            graphic.bindings.append(GraphicBinding(
                point_name=point.name,
                binding_type=BindingType.ALARM,
                x=x, y=y,
                label=f"⚠ {point.name}",
                color_map={"normal": "#4caf50", "alarm": "#f44336", "fault": "#ff9800"},
            ))

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
        elif elem.element_type == "circle":
            r = pw / 2
            return (f'    <circle cx="{px}" cy="{py}" r="{r}" '
                    f'fill="{elem.fill or "none"}" stroke="{elem.stroke or "none"}" '
                    f'stroke-width="{elem.stroke_width}"/>')
        elif elem.element_type == "ellipse":
            rx = pw / 2
            ry = ph / 2
            return (f'    <ellipse cx="{px}" cy="{py}" rx="{rx}" ry="{ry}" '
                    f'fill="{elem.fill or "none"}" stroke="{elem.stroke or "none"}" '
                    f'stroke-width="{elem.stroke_width}"/>')
        elif elem.element_type == "line":
            x2 = px + pw
            y2 = py + ph
            return (f'    <line x1="{px}" y1="{py}" x2="{x2}" y2="{y2}" '
                    f'stroke="{elem.stroke or "black"}" stroke-width="{elem.stroke_width}"/>')
        elif elem.element_type == "text":
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


__all__ = [
    "GraphicsGenerator",
    "GraphicDefinition",
    "GraphicElement",
    "GraphicBinding",
    "GraphicType",
    "BindingType",
    "generate_graphics",
]