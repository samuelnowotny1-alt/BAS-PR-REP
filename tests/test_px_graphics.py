import xml.etree.ElementTree as ET

from bas_assistant.generators.px_graphics import PXBinding, PXBindingType, PXFile, PXOrd, PXWidget, PXWidgetType


def test_px_binding_round_trips_spectrum_stops() -> None:
    binding = PXBinding(
        property_name="foregroundColor",
        binding_type=PXBindingType.SPECTRUM,
        ord=PXOrd("station:|slot:/Drivers/NiagaraNetwork/AHU-1/points/AHU-1_SAT"),
        degrade_behavior="showError",
        spectrum_stops=[
            {"value": "45", "color": "#0000ff"},
            {"value": "55", "color": "#00ff00"},
            {"value": "65", "color": "#ff0000"},
        ],
    )

    parsed = PXBinding.from_xml(binding.to_xml())

    assert parsed.binding_type == PXBindingType.SPECTRUM
    assert parsed.degrade_behavior == "showError"
    assert parsed.spectrum_stops == [
        {"value": "45", "color": "#0000ff"},
        {"value": "55", "color": "#00ff00"},
        {"value": "65", "color": "#ff0000"},
    ]


def test_px_file_round_trips_widget_bindings_with_spectrum() -> None:
    px_file = PXFile(
        name="AHU-1",
        root_widget=PXWidget(
            widget_type=PXWidgetType.BOUND_VALUE,
            name="sat",
            bindings=[
                PXBinding(
                    property_name="value",
                    binding_type=PXBindingType.VALUE,
                    ord=PXOrd("station:|slot:/Drivers/BacnetNetwork/MPC-1/Points/AHU-1_SAT"),
                    format_string=".1f",
                ),
                PXBinding(
                    property_name="foregroundColor",
                    binding_type=PXBindingType.SPECTRUM,
                    ord=PXOrd("station:|slot:/Drivers/BacnetNetwork/MPC-1/Points/AHU-1_SAT"),
                    spectrum_stops=[
                        {"value": "45", "color": "#0000ff"},
                        {"value": "55", "color": "#00ff00"},
                    ],
                ),
            ],
        ),
    )

    xml_root = ET.fromstring(px_file.to_string())
    parsed = PXFile.from_xml(xml_root)

    assert parsed.root_widget is not None
    assert len(parsed.root_widget.bindings) == 2
    spectrum_binding = parsed.root_widget.bindings[1]
    assert spectrum_binding.property_name == "foregroundColor"
    assert spectrum_binding.binding_type == PXBindingType.SPECTRUM
    assert spectrum_binding.spectrum_stops == [
        {"value": "45", "color": "#0000ff"},
        {"value": "55", "color": "#00ff00"},
    ]
