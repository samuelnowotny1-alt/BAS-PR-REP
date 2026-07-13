#!/usr/bin/env python3
"""
Test script for PX Graphics Generator

This script demonstrates the PX (Presentation XML) generation capabilities
for Tridium Niagara Framework graphics.
"""

import sys
from pathlib import Path

# Add the project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bas_assistant import (
    PXWidgetType,
    PXBindingType,
    PXOrd,
    PXBinding,
    PXWidget,
    PXFile,
    PXGraphicsGenerator,
    generate_ahu_px,
    generate_vav_px,
    generate_chiller_px,
    generate_equipment_schedule,
    save_px_file,
    load_px_file,
)


def test_px_ord():
    """Test PX ORD parsing and manipulation."""
    print("=" * 60)
    print("Testing PX ORD Parsing")
    print("=" * 60)

    # Absolute ORD
    abs_ord = PXOrd("station:|slot:/Drivers/BacnetNetwork/AHU_01/points/SAT")
    print(f"Absolute ORD: {abs_ord}")
    print(f"  Is absolute: {abs_ord.is_absolute}")
    print(f"  Is relative: {abs_ord.is_relative}")
    print(f"  Base component: {abs_ord.base_component}")
    print(f"  Point path: {abs_ord.point_path}")

    # Relative ORD
    rel_ord = PXOrd("slot:points/SAT")
    print(f"\nRelative ORD: {rel_ord}")
    print(f"  Is absolute: {rel_ord.is_absolute}")
    print(f"  Is relative: {rel_ord.is_relative}")
    print(f"  Base component: {rel_ord.base_component}")
    print(f"  Point path: {rel_ord.point_path}")

    # Variable ORD for PX includes
    var_ord = abs_ord.to_variable_ord("zone")
    print(f"\nVariable ORD: {var_ord}")


def test_px_binding():
    """Test PX binding creation and XML serialization."""
    print("\n" + "=" * 60)
    print("Testing PX Binding")
    print("=" * 60)

    binding = PXBinding(
        property_name="value",
        binding_type=PXBindingType.BOUND_VALUE,
        ord=PXOrd("slot:points/SAT"),
        format_string=".1f",
        degrade_behavior="hide"
    )

    xml_elem = binding.to_xml()
    print(f"Binding XML:\n{ET.tostring(xml_elem, encoding='unicode')}")


def test_px_widget():
    """Test PX widget creation and XML serialization."""
    print("\n" + "=" * 60)
    print("Testing PX Widget")
    print("=" * 60)

    # Create a canvas pane with children
    canvas = PXWidget(
        widget_type=PXWidgetType.CANVAS_PANE,
        name="main_canvas",
        x=0, y=0, width=800, height=600,
        properties={"backgroundColor": "#ffffff", "borderColor": "#333"}
    )

    # Add a bound label
    label = PXWidget(
        widget_type=PXWidgetType.BOUND_LABEL,
        name="sat_label",
        x=100, y=50, width=200, height=30,
        properties={"text": "SAT", "fontSize": "14", "horizontalAlignment": "center"},
        bindings=[
            PXBinding(
                property_name="text",
                binding_type=PXBindingType.BOUND_LABEL,
                ord=PXOrd("slot:points/SAT"),
                format_string=".1f"
            )
        ]
    )
    canvas.children.append(label)

    # Add a bound value
    value = PXWidget(
        widget_type=PXWidgetType.BOUND_VALUE,
        name="sat_value",
        x=100, y=85, width=200, height=25,
        properties={"format": ".1f", "units": "°F"},
        bindings=[
            PXBinding(
                property_name="value",
                binding_type=PXBindingType.VALUE,
                ord=PXOrd("slot:points/SAT"),
                format_string=".1f"
            )
        ]
    )
    canvas.children.append(value)

    xml_elem = canvas.to_xml()
    print(f"Widget XML (truncated):\n{ET.tostring(xml_elem, encoding='unicode')[:2000]}...")


def test_px_file():
    """Test complete PX file creation and saving."""
    print("\n" + "=" * 60)
    print("Testing PX File Creation")
    print("=" * 60)

    # Create a simple PX file with canvas and some widgets
    px_file = PXFile(
        name="test_graphic",
        width=800,
        height=600,
        background_color="#ffffff"
    )

    # Root canvas
    canvas = PXWidget(
        widget_type=PXWidgetType.CANVAS_PANE,
        name="root_canvas",
        x=0, y=0, width=800, height=600,
        properties={"backgroundColor": "#ffffff"}
    )

    # Title label
    title = PXWidget(
        widget_type=PXWidgetType.LABEL,
        name="title",
        x=50, y=20, width=700, height=40,
        properties={"text": "AHU-01 Graphic", "fontSize": "24", "horizontalAlignment": "center",
                   "fontWeight": "bold", "foregroundColor": "#1976d2"}
    )
    canvas.children.append(title)

    # SAT display
    sat_label = PXWidget(
        widget_type=PXWidgetType.BOUND_LABEL,
        name="sat_label",
        x=100, y=100, width=150, height=30,
        properties={"text": "Supply Air Temp", "fontSize": "14"},
        bindings=[PXBinding("text", PXBindingType.BOUND_LABEL, PXOrd("slot:points/SAT"))]
    )
    canvas.children.append(sat_label)

    sat_value = PXWidget(
        widget_type=PXWidgetType.BOUND_VALUE,
        name="sat_value",
        x=260, y=100, width=100, height=30,
        properties={"format": ".1f", "units": "°F"},
        bindings=[PXBinding("value", PXBindingType.VALUE, PXOrd("slot:points/SAT"), ".1f")]
    )
    canvas.children.append(sat_value)

    # Fan status
    fan_label = PXWidget(
        widget_type=PXWidgetType.BOUND_LABEL,
        name="fan_label",
        x=100, y=150, width=150, height=30,
        properties={"text": "Supply Fan", "fontSize": "14"},
        bindings=[PXBinding("text", PXBindingType.BOUND_LABEL, PXOrd("slot:points/SF_S"))]
    )
    canvas.children.append(fan_label)

    fan_status = PXWidget(
        widget_type=PXWidgetType.BOUND_VALUE,
        name="fan_status",
        x=260, y=150, width=100, height=30,
        properties={"format": "on/off"},
        bindings=[PXBinding("value", PXBindingType.VALUE, PXOrd("slot:points/SF_S"), "on/off")]
    )
    canvas.children.append(fan_status)

    # Cooling coil valve
    cc_label = PXWidget(
        widget_type=PXWidgetType.BOUND_LABEL,
        name="cc_label",
        x=100, y=200, width=150, height=30,
        properties={"text": "Cooling Coil Valve", "fontSize": "14"},
        bindings=[PXBinding("text", PXBindingType.BOUND_LABEL, PXOrd("slot:points/CC_V"))]
    )
    canvas.children.append(cc_label)

    cc_value = PXWidget(
        widget_type=PXWidgetType.BOUND_VALUE,
        name="cc_value",
        x=260, y=200, width=100, height=30,
        properties={"format": ".0f", "units": "%"},
        bindings=[PXBinding("value", PXBindingType.VALUE, PXOrd("slot:points/CC_V"), ".0f")]
    )
    canvas.children.append(cc_value)

    px_file.root_widget = canvas

    # Save to file
    output_path = Path("test_ahu_graphic.px")
    px_file.save(output_path)
    print(f"Saved PX file to: {output_path}")
    print(f"File size: {output_path.stat().st_size} bytes")

    # Show first 3000 chars of XML
    xml_content = px_file.to_string()
    print(f"\nPX File XML (first 3000 chars):\n{xml_content[:3000]}...")

    # Test loading
    loaded = load_px_file(output_path)
    print(f"\nLoaded PX file: {loaded.name}")
    print(f"  Width: {loaded.width}, Height: {loaded.height}")
    print(f"  Root widget: {loaded.root_widget.widget_type if loaded.root_widget else 'None'}")
    print(f"  Children count: {len(loaded.root_widget.children) if loaded.root_widget else 0}")


def test_ahu_px_generation():
    """Test AHU PX graphic generation."""
    print("\n" + "=" * 60)
    print("Testing AHU PX Generation")
    print("=" * 60)

    output_path = Path("ahu_graphic.px")
    generate_ahu_px("AHU-01", output_path)
    print(f"Generated AHU PX: {output_path}")
    print(f"File size: {output_path.stat().st_size} bytes")

    # Load and verify
    loaded = load_px_file(output_path)
    print(f"  Name: {loaded.name}")
    print(f"  Root: {loaded.root_widget.widget_type if loaded.root_widget else 'None'}")
    print(f"  Widgets: {count_widgets(loaded.root_widget) if loaded.root_widget else 0}")


def test_vav_px_generation():
    """Test VAV PX graphic generation."""
    print("\n" + "=" * 60)
    print("Testing VAV PX Generation")
    print("=" * 60)

    output_path = Path("vav_graphic.px")
    generate_vav_px("VAV-101", output_path)
    print(f"Generated VAV PX: {output_path}")
    print(f"File size: {output_path.stat().st_size} bytes")

    loaded = load_px_file(output_path)
    print(f"  Name: {loaded.name}")
    print(f"  Widgets: {count_widgets(loaded.root_widget) if loaded.root_widget else 0}")


def test_chiller_px_generation():
    """Test Chiller PX graphic generation."""
    print("\n" + "=" * 60)
    print("Testing Chiller PX Generation")
    print("=" * 60)

    output_path = Path("chiller_graphic.px")
    generate_chiller_px("CH-01", output_path)
    print(f"Generated Chiller PX: {output_path}")
    print(f"File size: {output_path.stat().st_size} bytes")

    loaded = load_px_file(output_path)
    print(f"  Name: {loaded.name}")
    print(f"  Widgets: {count_widgets(loaded.root_widget) if loaded.root_widget else 0}")


def test_equipment_schedule():
    """Test equipment schedule generation with PX includes."""
    print("\n" + "=" * 60)
    print("Testing Equipment Schedule Generation")
    print("=" * 60)

    output_path = Path("equipment_schedule.px")
    generate_equipment_schedule(["AHU-01", "AHU-02", "AHU-03", "VAV-101", "VAV-102"], output_path)
    print(f"Generated Equipment Schedule: {output_path}")
    print(f"File size: {output_path.stat().st_size} bytes")

    loaded = load_px_file(output_path)
    print(f"  Name: {loaded.name}")
    print(f"  Variables: {loaded.variables}")
    print(f"  Widgets: {count_widgets(loaded.root_widget) if loaded.root_widget else 0}")


def count_widgets(widget: PXWidget | None) -> int:
    """Recursively count widgets in tree."""
    if widget is None:
        return 0
    return 1 + sum(count_widgets(child) for child in widget.children)


def test_px_include_variables():
    """Test PX include with variable substitution."""
    print("\n" + "=" * 60)
    print("Testing PX Include Variables")
    print("=" * 60)

    # Create an include file (zone detail)
    include = PXFile(
        name="zone_detail",
        width=200,
        height=100,
        background_color="#ffffff",
        variables={"zone": "baja:Component"}  # Variable for PX include
    )

    canvas = PXWidget(
        widget_type=PXWidgetType.CANVAS_PANE,
        name="zone_canvas",
        x=0, y=0, width=200, height=100,
        properties={"backgroundColor": "#f5f5f5", "borderColor": "#ccc", "borderWidth": "1"}
    )

    # Equipment label with variable ORD
    equip_label = PXWidget(
        widget_type=PXWidgetType.BOUND_LABEL,
        name="equip_name",
        x=10, y=10, width=180, height=25,
        properties={"text": "Equipment", "fontSize": "12", "fontWeight": "bold"},
        bindings=[PXBinding("text", PXBindingType.BOUND_LABEL,
                            PXOrd("$(zone)"))]  # Variable ORD
    )
    canvas.children.append(equip_label)

    # Zone temp with variable ORD
    temp_label = PXWidget(
        widget_type=PXWidgetType.BOUND_LABEL,
        name="zone_temp_label",
        x=10, y=40, width=80, height=25,
        properties={"text": "Zone Temp", "fontSize": "11"},
        bindings=[PXBinding("text", PXBindingType.BOUND_LABEL,
                            PXOrd("$(zone)/points/ZN_T"))]
    )
    canvas.children.append(temp_label)

    temp_value = PXWidget(
        widget_type=PXWidgetType.BOUND_VALUE,
        name="zone_temp_value",
        x=100, y=40, width=90, height=25,
        properties={"format": ".1f", "units": "°F"},
        bindings=[PXBinding("value", PXBindingType.VALUE,
                            PXOrd("$(zone)/points/ZN_T"), ".1f")]
    )
    canvas.children.append(temp_value)

    # Hyperlink to detail graphic
    link = PXWidget(
        widget_type=PXWidgetType.PX_LINK,
        name="detail_link",
        x=10, y=70, width=180, height=25,
        properties={"text": "View Detail", "fontSize": "11", "foregroundColor": "#1976d2"},
        bindings=[PXBinding("hyperlink", PXBindingType.HYPERLINK,
                            PXOrd("$(zone)/graphic/detail"))]
    )
    canvas.children.append(link)

    include.root_widget = canvas
    include.save(Path("zone_detail_include.px"))
    print("Created zone_detail_include.px with variables")

    # Show the variables section
    xml = include.to_string()
    print("Variables section:")
    for line in xml.split('\n'):
        if 'variable' in line.lower() or 'variables' in line.lower():
            print(f"  {line.strip()}")


# Need to import ET for XML output
import xml.etree.ElementTree as ET


if __name__ == "__main__":
    print("BAS Assistant - PX Graphics Generator Test Suite")
    print("=" * 60)

    try:
        test_px_ord()
        test_px_binding()
        test_px_widget()
        test_px_file()
        test_ahu_px_generation()
        test_vav_px_generation()
        test_chiller_px_generation()
        test_equipment_schedule()
        test_px_include_variables()

        print("\n" + "=" * 60)
        print("All tests completed successfully!")
        print("=" * 60)
        print("\nGenerated files:")
        for f in Path(".").glob("*.px"):
            print(f"  {f} ({f.stat().st_size} bytes)")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)