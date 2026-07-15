"""
Niagara PX (Presentation XML) Graphics Parser/Generator

This module provides parsing and generation of Niagara PX (Presentation XML) files,
which are the native graphics format for Tridium Niagara Framework.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
import re


class PXWidgetType(str, Enum):
    """Standard Niagara PX widget types."""

    # Container widgets
    CANVAS_PANE = "kitPx:CanvasPane"
    SCROLL_PANE = "kitPx:ScrollPane"
    SPLIT_PANE = "kitPx:SplitPane"
    TABBED_PANE = "kitPx:TabbedPane"

    # Display widgets
    LABEL = "kitPx:Label"
    BOUND_LABEL = "kitPx:BoundLabel"
    BOUND_VALUE = "kitPx:BoundValue"
    MULTI_STATE_LABEL = "kitPx:MultiStateLabel"
    IMAGE = "kitPx:Image"
    LEVEL = "kitPx:Level"
    PROGRESS_BAR = "kitPx:ProgressBar"

    # Input widgets
    BUTTON = "kitPx:Button"
    TOGGLE_BUTTON = "kitPx:ToggleButton"
    SLIDER = "kitPx:Slider"
    TEXT_FIELD = "kitPx:TextField"
    COMBO_BOX = "kitPx:ComboBox"
    SPINNER = "kitPx:Spinner"

    # Complex widgets
    TABLE = "kitPx:Table"
    TREE = "kitPx:Tree"
    NAVIGATOR = "kitPx:Navigator"
    ALARM_TABLE = "kitPx:AlarmTable"
    HISTORY_TABLE = "kitPx:HistoryTable"
    SCHEDULE = "kitPx:Schedule"
    CALENDAR = "kitPx:Calendar"

    # Chart widgets
    CHART = "kitPx:Chart"
    REAL_TIME_CHART = "kitPx:RealTimeChart"
    XY_CHART = "kitPx:XYChart"

    # Special widgets
    PX_INCLUDE = "kitPx:PxInclude"
    PX_LINK = "kitPx:PxLink"
    HYPERLINK = "kitPx:Hyperlink"
    ACTION_BUTTON = "kitPx:ActionButton"


class PXBindingType(str, Enum):
    """PX binding types for widget properties."""

    VALUE = "value"                    # Standard value binding
    BOUND_LABEL = "boundLabel"         # Label with value binding
    BOUND_VALUE = "boundValue"         # Value display with binding
    HYPERLINK = "hyperlink"            # Navigation hyperlink
    SPECTRUM = "spectrum"              # Color spectrum animation
    SPECTRUM_SETPOINT = "spectrumSetpoint"  # Spectrum setpoint
    TOOLTIP = "tooltip"                # Tooltip binding
    VISIBLE = "visible"                # Visibility binding
    ENABLED = "enabled"                # Enabled/disabled binding
    ACTION = "action"                  # Action/command binding
    TEXT = "text"                      # Text content binding


@dataclass
class PXOrd:
    """Niagara ORD (Object Reference Descriptor) for PX bindings."""

    ord: str

    def __str__(self) -> str:
        return self.ord

    @property
    def is_relative(self) -> bool:
        """Check if ORD is relative (starts with slot:, file:, etc.)."""
        return self.ord.startswith(("slot:", "file:", "station:", "platform:"))

    @property
    def is_absolute(self) -> bool:
        """Check if ORD is absolute (starts with station:|slot:/)."""
        return self.ord.startswith("station:|slot:/")

    @property
    def base_component(self) -> str:
        """Extract base component from ORD (before /points/ or similar)."""
        # Remove station prefix if present
        ord_clean = self.ord
        if ord_clean.startswith("station:|"):
            ord_clean = ord_clean[len("station:|"):]

        # Find the component path (before /points/, /slot/, etc.)
        for separator in ["/points/", "/slot/", "/actions/", "/alarms/"]:
            if separator in ord_clean:
                return ord_clean.split(separator)[0]
        return ord_clean

    @property
    def point_path(self) -> str:
        """Extract point path from ORD (after base component)."""
        ord_clean = self.ord
        if ord_clean.startswith("station:|"):
            ord_clean = ord_clean[len("station:|"):]

        for separator in ["/points/", "/slot/", "/actions/", "/alarms/"]:
            if separator in ord_clean:
                parts = ord_clean.split(separator)
                return separator.lstrip("/") + "/" + parts[1] if len(parts) > 1 else ""
        return ""

    def to_variable_ord(self, variable_name: str) -> "PXOrd":
        """Convert to variable-based ORD for PX includes."""
        base = self.base_component
        point_path = self.point_path
        if point_path:
            return PXOrd(f"$({variable_name})/{point_path}")
        return PXOrd(f"$({variable_name})")


@dataclass
class PXBinding:
    """A PX widget property binding."""

    property_name: str
    binding_type: PXBindingType
    ord: PXOrd
    format_string: str | None = None
    degrade_behavior: str | None = None  # "hide", "disable", "showError"
    spectrum_stops: list[dict] | None = None  # For spectrum bindings

    def to_xml(self) -> ET.Element:
        """Convert binding to XML element."""
        binding_elem = ET.Element("binding")
        binding_elem.set("name", self.property_name)
        binding_elem.set("type", self.binding_type.value)
        binding_elem.set("ord", str(self.ord))

        if self.format_string:
            binding_elem.set("format", self.format_string)
        if self.degrade_behavior:
            binding_elem.set("degradeBehavior", self.degrade_behavior)
        if self.spectrum_stops:
            spectrum_elem = ET.SubElement(binding_elem, "spectrum")
            for stop in self.spectrum_stops:
                stop_elem = ET.SubElement(spectrum_elem, "stop")
                for k, v in stop.items():
                    stop_elem.set(k, str(v))
        return binding_elem

    @classmethod
    def from_xml(cls, elem: ET.Element) -> "PXBinding":
        """Create binding from XML element."""
        spectrum_stops: list[dict[str, str]] | None = None
        spectrum_elem = elem.find("spectrum")
        if spectrum_elem is not None:
            stops = []
            for stop_elem in spectrum_elem.findall("stop"):
                stops.append(dict(stop_elem.attrib))
            if stops:
                spectrum_stops = stops
        return cls(
            property_name=elem.get("name", ""),
            binding_type=PXBindingType(elem.get("type", "value")),
            ord=PXOrd(elem.get("ord", "")),
            format_string=elem.get("format"),
            degrade_behavior=elem.get("degradeBehavior"),
            spectrum_stops=spectrum_stops,
        )


@dataclass
class PXWidget:
    """A widget in the PX widget tree."""

    widget_type: str
    name: str = ""
    x: float = 0
    y: float = 0
    width: float = 100
    height: float = 100
    properties: dict[str, Any] = field(default_factory=dict)
    bindings: list[PXBinding] = field(default_factory=list)
    children: list["PXWidget"] = field(default_factory=list)
    ordinal: int = 0  # Z-order

    def to_xml(self) -> ET.Element:
        """Convert widget to XML element."""
        widget_elem = ET.Element("widget")
        widget_elem.set("type", self.widget_type)
        if self.name:
            widget_elem.set("name", self.name)
        widget_elem.set("x", str(self.x))
        widget_elem.set("y", str(self.y))
        widget_elem.set("width", str(self.width))
        widget_elem.set("height", str(self.height))
        widget_elem.set("ordinal", str(self.ordinal))

        # Properties
        if self.properties:
            props_elem = ET.SubElement(widget_elem, "properties")
            for key, value in self.properties.items():
                prop_elem = ET.SubElement(props_elem, "property")
                prop_elem.set("name", key)
                prop_elem.text = str(value)

        # Bindings
        if self.bindings:
            bindings_elem = ET.SubElement(widget_elem, "bindings")
            for binding in self.bindings:
                bindings_elem.append(binding.to_xml())

        # Children
        if self.children:
            children_elem = ET.SubElement(widget_elem, "children")
            for child in self.children:
                children_elem.append(child.to_xml())

        return widget_elem

    @classmethod
    def from_xml(cls, elem: ET.Element) -> "PXWidget":
        """Create widget from XML element."""
        widget = cls(
            widget_type=elem.get("type", ""),
            name=elem.get("name", ""),
            x=float(elem.get("x", "0")),
            y=float(elem.get("y", "0")),
            width=float(elem.get("width", "100")),
            height=float(elem.get("height", "100")),
            ordinal=int(elem.get("ordinal", "0"))
        )

        # Properties
        props_elem = elem.find("properties")
        if props_elem is not None:
            for prop_elem in props_elem.findall("property"):
                widget.properties[prop_elem.get("name", "")] = prop_elem.text or ""

        # Bindings
        bindings_elem = elem.find("bindings")
        if bindings_elem is not None:
            for binding_elem in bindings_elem.findall("binding"):
                widget.bindings.append(PXBinding.from_xml(binding_elem))

        # Children
        children_elem = elem.find("children")
        if children_elem is not None:
            for child_elem in children_elem.findall("widget"):
                widget.children.append(PXWidget.from_xml(child_elem))

        return widget


@dataclass
class PXFile:
    """Complete PX file representation."""

    name: str
    version: str = "4.0"
    width: int = 1200
    height: int = 800
    background_color: str = "#ffffff"
    root_widget: PXWidget | None = None
    variables: dict[str, str] = field(default_factory=dict)  # For PX includes
    metadata: dict[str, str] = field(default_factory=dict)

    def to_xml(self) -> ET.Element:
        """Convert PX file to XML element tree."""
        root = ET.Element("px")
        root.set("version", self.version)
        root.set("name", self.name)
        root.set("width", str(self.width))
        root.set("height", str(self.height))
        root.set("backgroundColor", self.background_color)

        # Metadata
        if self.metadata:
            meta_elem = ET.SubElement(root, "metadata")
            for key, value in self.metadata.items():
                m = ET.SubElement(meta_elem, "property")
                m.set("name", key)
                m.text = value

        # Variables (for PX includes)
        if self.variables:
            vars_elem = ET.SubElement(root, "variables")
            for var_name, var_type in self.variables.items():
                var_elem = ET.SubElement(vars_elem, "variable")
                var_elem.set("name", var_name)
                var_elem.set("type", var_type)

        # Root widget
        if self.root_widget:
            root.append(self.root_widget.to_xml())

        return root

    def to_string(self, pretty: bool = True) -> str:
        """Serialize PX file to XML string."""
        xml_root = self.to_xml()
        if pretty:
            ET.indent(xml_root, space="  ")
        return ET.tostring(xml_root, encoding="unicode", xml_declaration=True)

    def save(self, path: Path) -> None:
        """Save PX file to disk."""
        path.write_text(self.to_string())

    @classmethod
    def from_xml(cls, elem: ET.Element) -> "PXFile":
        """Create PXFile from XML element."""
        px_file = cls(
            name=elem.get("name", ""),
            version=elem.get("version", "4.0"),
            width=int(elem.get("width", "1200")),
            height=int(elem.get("height", "800")),
            background_color=elem.get("backgroundColor", "#ffffff")
        )

        # Metadata
        meta_elem = elem.find("metadata")
        if meta_elem is not None:
            for prop in meta_elem.findall("property"):
                px_file.metadata[prop.get("name", "")] = prop.text or ""

        # Variables
        vars_elem = elem.find("variables")
        if vars_elem is not None:
            for var in vars_elem.findall("variable"):
                px_file.variables[var.get("name", "")] = var.get("type", "baja:Component")

        # Root widget
        for child in elem:
            if child.tag == "widget":
                px_file.root_widget = PXWidget.from_xml(child)
                break

        return px_file

    @classmethod
    def load(cls, path: Path) -> "PXFile":
        """Load PX file from disk."""
        tree = ET.parse(path)
        return cls.from_xml(tree.getroot())


class PXGraphicsGenerator:
    """Generates PX graphics from BAS equipment data."""

    # Standard PX widget templates for common BAS equipment
    WIDGET_TEMPLATES = {
        "ahu": {
            "widgets": [
                # Main casing
                {"type": PXWidgetType.CANVAS_PANE, "name": "casing", "x": 50, "y": 50, "width": 600, "height": 400,
                 "properties": {"backgroundColor": "#f5f5f5", "borderColor": "#333", "borderWidth": "2"}},

                # Supply fan
                {"type": PXWidgetType.BOUND_LABEL, "name": "sf_label", "x": 80, "y": 220, "width": 80, "height": 40,
                 "properties": {"text": "SF", "fontSize": "12", "horizontalAlignment": "center"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "sf_status", "x": 80, "y": 265, "width": 80, "height": 25,
                 "properties": {"format": "on/off"}},

                # Return fan
                {"type": PXWidgetType.BOUND_LABEL, "name": "rf_label", "x": 540, "y": 220, "width": 80, "height": 40,
                 "properties": {"text": "RF", "fontSize": "12", "horizontalAlignment": "center"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "rf_status", "x": 540, "y": 265, "width": 80, "height": 25,
                 "properties": {"format": "on/off"}},

                # Cooling coil
                {"type": PXWidgetType.BOUND_LABEL, "name": "cc_label", "x": 250, "y": 80, "width": 100, "height": 30,
                 "properties": {"text": "CC", "fontSize": "12", "horizontalAlignment": "center", "backgroundColor": "#cce5ff"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "cc_valve", "x": 250, "y": 115, "width": 100, "height": 25,
                 "properties": {"format": ".0f", "units": "%"}},

                # Heating coil
                {"type": PXWidgetType.BOUND_LABEL, "name": "hc_label", "x": 250, "y": 350, "width": 100, "height": 30,
                 "properties": {"text": "HC", "fontSize": "12", "horizontalAlignment": "center", "backgroundColor": "#ffccbc"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "hc_valve", "x": 250, "y": 385, "width": 100, "height": 25,
                 "properties": {"format": ".0f", "units": "%"}},

                # Temperatures
                {"type": PXWidgetType.BOUND_VALUE, "name": "sat", "x": 580, "y": 120, "width": 80, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "SAT"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "mat", "x": 120, "y": 60, "width": 80, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "MAT"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "rat", "x": 580, "y": 340, "width": 80, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "RAT"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "oat", "x": 30, "y": 30, "width": 80, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "OAT"}},

                # Dampers
                {"type": PXWidgetType.BOUND_LABEL, "name": "oa_damper", "x": 30, "y": 50, "width": 60, "height": 20,
                 "properties": {"text": "OA", "fontSize": "10"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "oa_pos", "x": 30, "y": 75, "width": 60, "height": 20,
                 "properties": {"format": ".0f", "units": "%"}},
                {"type": PXWidgetType.BOUND_LABEL, "name": "ra_damper", "x": 590, "y": 50, "width": 60, "height": 20,
                 "properties": {"text": "RA", "fontSize": "10"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "ra_pos", "x": 590, "y": 75, "width": 60, "height": 20,
                 "properties": {"format": ".0f", "units": "%"}},

                # Filter
                {"type": PXWidgetType.BOUND_LABEL, "name": "filter_label", "x": 150, "y": 180, "width": 50, "height": 100,
                 "properties": {"text": "FILT", "fontSize": "10", "rotation": "90", "backgroundColor": "#e8eaf6"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "filter_dp", "x": 150, "y": 290, "width": 50, "height": 25,
                 "properties": {"format": ".2f", "units": "inWC", "label": "DP"}},

                # Duct connections
                {"type": PXWidgetType.LABEL, "name": "sa_label", "x": 620, "y": 180, "width": 40, "height": 25,
                 "properties": {"text": "SA →", "fontSize": "10", "foregroundColor": "#1976d2"}},
                {"type": PXWidgetType.LABEL, "name": "ra_label", "x": 620, "y": 280, "width": 40, "height": 25,
                 "properties": {"text": "RA →", "fontSize": "10", "foregroundColor": "#ef6c00"}},
            ],
            "bindings": {
                "sf_status": "slot:points/SF_S",
                "sf_label": "slot:points/SF_C",
                "rf_status": "slot:points/RF_S",
                "rf_label": "slot:points/RF_C",
                "cc_valve": "slot:points/CC_V",
                "hc_valve": "slot:points/HC_V",
                "sat": "slot:points/SAT",
                "mat": "slot:points/MAT",
                "rat": "slot:points/RAT",
                "oat": "slot:points/OAT",
                "oa_pos": "slot:points/OAD_P",
                "ra_pos": "slot:points/RAD_P",
                "filter_dp": "slot:points/FILT_DP",
            }
        },
        "vav": {
            "widgets": [
                {"type": PXWidgetType.CANVAS_PANE, "name": "casing", "x": 50, "y": 50, "width": 300, "height": 200,
                 "properties": {"backgroundColor": "#fff", "borderColor": "#333", "borderWidth": "2"}},

                # Damper
                {"type": PXWidgetType.BOUND_LABEL, "name": "damper_label", "x": 80, "y": 90, "width": 50, "height": 60,
                 "properties": {"text": "DMPR", "fontSize": "10", "backgroundColor": "#e0e0e0"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "damper_pos", "x": 80, "y": 155, "width": 50, "height": 25,
                 "properties": {"format": ".0f", "units": "%"}},

                # Reheat coil
                {"type": PXWidgetType.BOUND_LABEL, "name": "rh_label", "x": 160, "y": 80, "width": 80, "height": 80,
                 "properties": {"text": "RH", "fontSize": "12", "horizontalAlignment": "center", "backgroundColor": "#ffccbc"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "rh_valve", "x": 160, "y": 165, "width": 80, "height": 25,
                 "properties": {"format": ".0f", "units": "%"}},

                # Discharge temp
                {"type": PXWidgetType.BOUND_VALUE, "name": "dat", "x": 270, "y": 90, "width": 60, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "DAT"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "airflow", "x": 220, "y": 30, "width": 80, "height": 25,
                 "properties": {"format": ".0f", "units": "CFM", "label": "Flow"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "zone_temp", "x": 270, "y": 140, "width": 60, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "Zone"}},

                # Duct connections
                {"type": PXWidgetType.LABEL, "name": "sa_label", "x": 320, "y": 95, "width": 30, "height": 25,
                 "properties": {"text": "SA →", "fontSize": "10", "foregroundColor": "#1976d2"}},
            ],
            "bindings": {
                "damper_pos": "slot:points/DMPR_P",
                "rh_valve": "slot:points/RHV_P",
                "dat": "slot:points/DAT",
                "airflow": "slot:points/CFM",
                "zone_temp": "slot:points/ZN_T",
            }
        },
        "chiller": {
            "widgets": [
                {"type": PXWidgetType.CANVAS_PANE, "name": "casing", "x": 50, "y": 50, "width": 500, "height": 300,
                 "properties": {"backgroundColor": "#e3f2fd", "borderColor": "#1976d2", "borderWidth": "2"}},

                # Compressor
                {"type": PXWidgetType.BOUND_LABEL, "name": "comp_label", "x": 100, "y": 140, "width": 100, "height": 60,
                 "properties": {"text": "COMP", "fontSize": "12", "horizontalAlignment": "center"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "comp_status", "x": 100, "y": 205, "width": 100, "height": 25,
                 "properties": {"format": "on/off"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "comp_speed", "x": 100, "y": 235, "width": 100, "height": 25,
                 "properties": {"format": ".0f", "units": "%"}},

                # Evaporator
                {"type": PXWidgetType.BOUND_LABEL, "name": "evap_label", "x": 250, "y": 80, "width": 100, "height": 100,
                 "properties": {"text": "EVAP", "fontSize": "12", "horizontalAlignment": "center", "backgroundColor": "#cce5ff"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "chw_supply", "x": 250, "y": 185, "width": 100, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "CHWS"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "chw_return", "x": 250, "y": 215, "width": 100, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "CHWR"}},

                # Condenser
                {"type": PXWidgetType.BOUND_LABEL, "name": "cond_label", "x": 400, "y": 80, "width": 100, "height": 100,
                 "properties": {"text": "COND", "fontSize": "12", "horizontalAlignment": "center", "backgroundColor": "#ffccbc"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "cws_temp", "x": 400, "y": 40, "width": 100, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "CWS"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "cwr_temp", "x": 400, "y": 235, "width": 100, "height": 25,
                 "properties": {"format": ".1f", "units": "°F", "label": "CWR"}},

                # EXV
                {"type": PXWidgetType.BOUND_LABEL, "name": "exv_label", "x": 250, "y": 40, "width": 50, "height": 30,
                 "properties": {"text": "EXV", "fontSize": "10", "horizontalAlignment": "center"}},
                {"type": PXWidgetType.BOUND_VALUE, "name": "exv_pos", "x": 250, "y": 10, "width": 50, "height": 25,
                 "properties": {"format": ".0f", "units": "%"}},

                # Piping labels
                {"type": PXWidgetType.LABEL, "name": "chws_label", "x": 350, "y": 160, "width": 40, "height": 25,
                 "properties": {"text": "CHWS →", "fontSize": "10", "foregroundColor": "#1976d2"}},
                {"type": PXWidgetType.LABEL, "name": "chwr_label", "x": 350, "y": 200, "width": 40, "height": 25,
                 "properties": {"text": "CHWR →", "fontSize": "10", "foregroundColor": "#1976d2"}},
            ],
            "bindings": {
                "comp_status": "slot:points/COMP_S",
                "comp_speed": "slot:points/COMP_SPD",
                "chw_supply": "slot:points/CHWS_T",
                "chw_return": "slot:points/CHWR_T",
                "cws_temp": "slot:points/CWS_T",
                "cwr_temp": "slot:points/CWR_T",
                "exv_pos": "slot:points/EXV_P",
            }
        },
    }

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()

    def generate_equipment_px(
        self,
        equipment_type: str,
        equipment_name: str,
        equipment_id: str,
        point_mappings: dict[str, str] | None = None,
        use_variables: bool = False,
        variable_prefix: str = "equip"
    ) -> PXFile:
        """Generate a PX file for a specific equipment type."""

        if equipment_type not in self.WIDGET_TEMPLATES:
            raise ValueError(f"Unknown equipment type: {equipment_type}")

        template = self.WIDGET_TEMPLATES[equipment_type]

        # Create root canvas pane
        root = PXWidget(
            widget_type=PXWidgetType.CANVAS_PANE,
            name="root",
            x=0, y=0,
            width=700,
            height=500,
            properties={
                "backgroundColor": "#ffffff",
                "scaling": "none"
            }
        )

        # Create widgets from template
        widget_map = {}
        for i, widget_def in enumerate(template["widgets"]):
            widget = PXWidget(
                widget_type=widget_def["type"],
                name=widget_def["name"],
                x=widget_def["x"],
                y=widget_def["y"],
                width=widget_def["width"],
                height=widget_def["height"],
                properties=widget_def.get("properties", {}),
                ordinal=i
            )
            widget_map[widget_def["name"]] = widget
            root.children.append(widget)

        # Apply bindings
        bindings = template.get("bindings", {})
        for widget_name, ord_str in bindings.items():
            if widget_name in widget_map:
                widget = widget_map[widget_name]
                final_ord = ord_str

                # Apply point mappings if provided
                if point_mappings:
                    for key, value in point_mappings.items():
                        if key in ord_str:
                            final_ord = ord_str.replace(key, value)

                # Convert to variable-based ORD for PX includes
                if use_variables:
                    base_ord = PXOrd(final_ord)
                    final_ord = str(base_ord.to_variable_ord(variable_prefix))

                # Determine binding type based on widget type
                widget_type = widget.widget_type
                if widget_type in [PXWidgetType.BOUND_LABEL, PXWidgetType.BOUND_VALUE]:
                    binding_type = PXBindingType.BOUND_LABEL if "Label" in widget_type else PXBindingType.BOUND_VALUE
                elif widget_type == PXWidgetType.HYPERLINK:
                    binding_type = PXBindingType.HYPERLINK
                else:
                    binding_type = PXBindingType.VALUE

                binding = PXBinding(
                    property_name="value",
                    binding_type=binding_type,
                    ord=PXOrd(final_ord)
                )
                widget.bindings.append(binding)

        # Create PX file
        px_file = PXFile(
            name=equipment_name,
            width=700,
            height=500,
            root_widget=root,
            metadata={
                "equipmentType": equipment_type,
                "equipmentId": equipment_id,
                "generatedBy": "BAS Assistant PX Generator",
                "generatedAt": "2024-01-01T00:00:00Z"
            }
        )

        # Add variables if using includes
        if use_variables:
            px_file.variables[variable_prefix] = "baja:Component"

        return px_file

    def generate_px_include(
        self,
        equipment_type: str,
        include_name: str,
        variable_name: str = "equip"
    ) -> PXFile:
        """Generate a PX include file with variable placeholders."""
        return self.generate_equipment_px(
            equipment_type=equipment_type,
            equipment_name=include_name,
            equipment_id="",
            use_variables=True,
            variable_prefix=variable_name
        )

    def create_equipment_schedule_px(
        self,
        schedule_name: str,
        equipment_list: list[dict],  # [{name, type, id, folder_ord}]
        row_include_name: str = "equip_row",
        header_include_name: str = "schedule_header"
    ) -> tuple[PXFile, PXFile, PXFile]:
        """Create equipment schedule with header and row includes."""

        # Header include
        header_root = PXWidget(
            widget_type=PXWidgetType.CANVAS_PANE,
            name="header_root",
            x=0, y=0, width=800, height=40,
            properties={"backgroundColor": "#333", "foregroundColor": "#fff", "scaling": "none"}
        )

        headers = ["Equipment", "Status", "Temperature", "Setpoint", "Flow", "Alarm"]
        col_widths = [180, 100, 120, 120, 100, 180]
        x = 0
        for i, (header, width) in enumerate(zip(headers, col_widths)):
            label = PXWidget(
                widget_type=PXWidgetType.LABEL,
                name=f"header_{i}",
                x=x, y=5, width=width, height=30,
                properties={"text": header, "fontSize": "11", "horizontalAlignment": "center",
                            "fontWeight": "bold", "foregroundColor": "#fff"},
                ordinal=i
            )
            header_root.children.append(label)
            x += width

        header_px = PXFile(
            name=header_include_name,
            width=800, height=40,
            root_widget=header_root,
            metadata={"type": "schedule_header"}
        )

        # Row include (odd)
        row_root = PXWidget(
            widget_type=PXWidgetType.CANVAS_PANE,
            name="row_root",
            x=0, y=0, width=800, height=35,
            properties={"backgroundColor": "#f5f5f5", "scaling": "none"}
        )

        row_widgets = [
            ("equip_name", PXWidgetType.BOUND_LABEL, 0, 180, "${equip}/name"),
            ("status", PXWidgetType.BOUND_VALUE, 180, 100, "slot:points/Status"),
            ("temp", PXWidgetType.BOUND_VALUE, 280, 120, "slot:points/ZoneTemp"),
            ("setpoint", PXWidgetType.BOUND_VALUE, 400, 120, "slot:points/ZoneTempSP"),
            ("flow", PXWidgetType.BOUND_VALUE, 520, 100, "slot:points/CFM"),
            ("alarm", PXWidgetType.BOUND_LABEL, 620, 180, "slot:alarms"),
        ]

        for i, (name, wtype, x, width, ord_str) in enumerate(row_widgets):
            widget = PXWidget(
                widget_type=wtype,
                name=name,
                x=x, y=5, width=width, height=25,
                properties={"format": ".1f", "horizontalAlignment": "center"} if wtype == PXWidgetType.BOUND_VALUE else
                           {"horizontalAlignment": "center", "fontSize": "11"},
                ordinal=i
            )
            binding = PXBinding(
                property_name="value",
                binding_type=PXBindingType.BOUND_LABEL if wtype == PXWidgetType.BOUND_LABEL else PXBindingType.BOUND_VALUE,
                ord=PXOrd(ord_str)
            )
            widget.bindings.append(binding)
            row_root.children.append(widget)

        row_px = PXFile(
            name=row_include_name,
            width=800, height=35,
            root_widget=row_root,
            variables={"equip": "baja:Component"},
            metadata={"type": "schedule_row", "rowType": "odd"}
        )

        # Even row include (alternate color)
        even_row_root = PXWidget(
            widget_type=PXWidgetType.CANVAS_PANE,
            name="row_root",
            x=0, y=0, width=800, height=35,
            properties={"backgroundColor": "#e8e8e8", "scaling": "none"}
        )

        for widget in row_root.children:
            even_row_root.children.append(PXWidget(
                widget_type=widget.widget_type,
                name=widget.name,
                x=widget.x, y=widget.y, width=widget.width, height=widget.height,
                properties={**widget.properties, "backgroundColor": "#e8e8e8"},
                bindings=widget.bindings.copy(),
                ordinal=widget.ordinal
            ))

        even_row_px = PXFile(
            name=f"{row_include_name}_even",
            width=800, height=35,
            root_widget=even_row_root,
            variables={"equip": "baja:Component"},
            metadata={"type": "schedule_row", "rowType": "even"}
        )

        # Main schedule file
        schedule_root = PXWidget(
            widget_type=PXWidgetType.SCROLL_PANE,
            name="schedule_root",
            x=0, y=0, width=820, height=600,
            properties={"backgroundColor": "#fff"}
        )

        # Add header include
        header_include = PXWidget(
            widget_type=PXWidgetType.PX_INCLUDE,
            name="header_include",
            x=0, y=0, width=800, height=40,
            properties={"includeFile": f"px/includes/{header_include_name}.px"},
            ordinal=0
        )
        schedule_root.children.append(header_include)

        # Add row includes for each equipment
        y = 40
        for idx, equip in enumerate(equipment_list):
            row_include = PXWidget(
                widget_type=PXWidgetType.PX_INCLUDE,
                name=f"row_{idx}",
                x=0, y=y, width=800, height=35,
                properties={
                    "includeFile": f"px/includes/{row_include_name}.px",
                    "variables": f"{equip['folder_ord']}"
                },
                ordinal=idx + 1
            )
            schedule_root.children.append(row_include)
            y += 35

        schedule_px = PXFile(
            name=schedule_name,
            width=820, height=600,
            root_widget=schedule_root,
            metadata={"type": "equipment_schedule", "rowCount": str(len(equipment_list))}
        )

        return schedule_px, header_px, row_px, even_row_px

    def parse_existing_px(self, px_path: Path) -> PXFile:
        """Parse an existing PX file."""
        return PXFile.load(px_path)

    def extract_widget_tree(self, px_file: PXFile) -> list[dict]:
        """Extract widget tree as list of dictionaries for analysis."""
        result = []

        def walk(widget: PXWidget, depth: int = 0, parent_path: str = ""):
            path = f"{parent_path}/{widget.name}" if parent_path else widget.name
            result.append({
                "path": path,
                "type": widget.widget_type,
                "name": widget.name,
                "bounds": {"x": widget.x, "y": widget.y, "width": widget.width, "height": widget.height},
                "properties": widget.properties,
                "bindings": [
                    {
                        "property": b.property_name,
                        "type": b.binding_type.value,
                        "ord": str(b.ord),
                        "format": b.format_string
                    }
                    for b in widget.bindings
                ],
                "depth": depth
            })
            for child in widget.children:
                walk(child, depth + 1, path)

        if px_file.root_widget:
            walk(px_file.root_widget)

        return result

    def convert_to_internal_graphics(self, px_file: PXFile) -> dict:
        """Convert PX file to internal graphics format."""
        from .graphics import GraphicDefinition, GraphicElement, GraphicType, BindingType, GraphicBinding

        elements = []
        bindings = []

        def walk(widget: PXWidget, layer: str = "default"):
            # Convert widget to graphic element
            element = GraphicElement(
                element_type=widget.widget_type.replace("kitPx:", "").lower(),
                x=widget.x / px_file.width,
                y=widget.y / px_file.height,
                width=widget.width / px_file.width,
                height=widget.height / px_file.height,
                fill=widget.properties.get("backgroundColor"),
                stroke=widget.properties.get("borderColor"),
                stroke_width=float(widget.properties.get("borderWidth", "1")),
                text=widget.properties.get("text"),
                font_size=float(widget.properties.get("fontSize", "12")),
                font_family=widget.properties.get("fontFamily", "Arial"),
                layer=layer
            )
            elements.append(element)

            # Convert bindings
            for binding in widget.bindings:
                if binding.ord.ord:
                    g_binding = GraphicBinding(
                        point_name=binding.ord.ord,
                        binding_type=BindingType.VALUE,  # Default, could be enhanced
                        x=element.x,
                        y=element.y,
                        label=widget.properties.get("label"),
                        format=binding.format_string
                    )
                    bindings.append(g_binding)

            for child in widget.children:
                walk(child, layer)

        if px_file.root_widget:
            walk(px_file.root_widget)

        graphic = GraphicDefinition(
            graphic_id=px_file.name,
            name=px_file.name,
            graphic_type=GraphicType.EQUIPMENT,
            width=px_file.width,
            height=px_file.height,
            background=px_file.background_color,
            elements=elements,
            bindings=bindings,
            metadata=px_file.metadata
        )

        return graphic


# Convenience functions
def load_px_file(path: Path) -> PXFile:
    """Load a PX file from disk."""
    return PXFile.load(path)


def save_px_file(px_file: PXFile, path: Path) -> None:
    """Save a PX file to disk."""
    px_file.save(path)


def generate_ahu_px(name: str, equipment_id: str, use_variables: bool = False) -> PXFile:
    """Generate an AHU PX graphic."""
    generator = PXGraphicsGenerator()
    return generator.generate_equipment_px("ahu", name, equipment_id, use_variables=use_variables)


def generate_vav_px(name: str, equipment_id: str, use_variables: bool = False) -> PXFile:
    """Generate a VAV PX graphic."""
    generator = PXGraphicsGenerator()
    return generator.generate_equipment_px("vav", name, equipment_id, use_variables=use_variables)


def generate_chiller_px(name: str, equipment_id: str, use_variables: bool = False) -> PXFile:
    """Generate a Chiller PX graphic."""
    generator = PXGraphicsGenerator()
    return generator.generate_equipment_px("chiller", name, equipment_id, use_variables=use_variables)


def generate_equipment_schedule(
    name: str,
    equipment_list: list[dict]
) -> tuple[PXFile, PXFile, PXFile, PXFile]:
    """Generate equipment schedule with includes."""
    generator = PXGraphicsGenerator()
    return generator.create_equipment_schedule_px(name, equipment_list)
