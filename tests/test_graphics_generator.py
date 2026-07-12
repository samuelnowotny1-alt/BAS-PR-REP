from pathlib import Path

from bas_assistant.generators.graphics import GraphicsGenerator
from bas_assistant.models import (
    Equipment,
    EquipmentType,
    Point,
    PointDirection,
    PointKind,
    Project,
    ProjectMetadata,
)
from bas_assistant.models.equipment import EquipmentTemplateRef


def _project_with(equipment: list[Equipment], points: list[Point]) -> Project:
    return Project(
        metadata=ProjectMetadata(project_id="TEST", name="Graphics Test"),
        equipment=equipment,
        points=points,
        controllers=[],
    )


def _binding_map(generator: GraphicsGenerator, graphic_id: str) -> dict[str, object]:
    graphic = generator.graphics[graphic_id]
    return {binding.point_name: binding for binding in graphic.bindings}


def test_ahu_bindings_follow_component_anchors() -> None:
    equip = Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id="MPC-1")
    points = [
        Point(name="AHU-1 SAT", equipment_id="AHU-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-1 MAT", equipment_id="AHU-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-1 RAT", equipment_id="AHU-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-1 OAD CMD", equipment_id="AHU-1", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="AHU-1 CCV CMD", equipment_id="AHU-1", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="AHU-1 SF STATUS", equipment_id="AHU-1", kind=PointKind.STATUS, direction=PointDirection.INPUT),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    bindings = _binding_map(generator, "graphic_ahu-1")

    assert bindings["AHU-1 SAT"].x > 0.85
    assert 0.28 <= bindings["AHU-1 SAT"].y <= 0.42
    assert 0.25 <= bindings["AHU-1 MAT"].x <= 0.4
    assert 0.58 <= bindings["AHU-1 MAT"].y <= 0.7
    assert bindings["AHU-1 RAT"].x > 0.9
    assert 0.58 <= bindings["AHU-1 RAT"].y <= 0.72
    assert bindings["AHU-1 OAD CMD"].x < 0.2
    assert 0.45 <= bindings["AHU-1 CCV CMD"].x <= 0.65
    assert bindings["AHU-1 CCV CMD"].y < 0.2
    assert bindings["AHU-1 SF STATUS"].binding_type.value == "status"
    assert 0.65 <= bindings["AHU-1 SF STATUS"].x <= 0.78


def test_ahu_sections_can_be_declared_from_equipment_template() -> None:
    equip = Equipment(
        id="AHU-2",
        type=EquipmentType.AHU,
        controller_id="MPC-2",
        template=EquipmentTemplateRef(
            template_name="ahu_custom",
            parameters={
                "graphic_sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
            },
        ),
    )
    points = [
        Point(name="AHU-2 OAD CMD", equipment_id="AHU-2", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="AHU-2 CCV CMD", equipment_id="AHU-2", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="AHU-2 SAT", equipment_id="AHU-2", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-2"]
    bindings = _binding_map(generator, "graphic_ahu-2")

    assert graphic.metadata["graphic_sections"] == [
        "outside_air",
        "filter",
        "cooling_coil",
        "heating_coil",
        "supply_fan",
        "discharge",
    ]
    assert 0.1 <= bindings["AHU-2 OAD CMD"].x <= 0.2
    assert 0.4 <= bindings["AHU-2 CCV CMD"].x <= 0.55
    assert bindings["AHU-2 SAT"].x > 0.82


def test_ahu_configured_layout_uses_weighted_section_spacing_and_detail_shapes() -> None:
    equip = Equipment(
        id="AHU-3",
        type=EquipmentType.AHU,
        controller_id="MPC-3",
        template=EquipmentTemplateRef(
            template_name="ahu_custom",
            parameters={
                "graphic_sections": "outside_air,filter,cooling_coil,supply_fan,discharge",
            },
        ),
    )
    generator = GraphicsGenerator(_project_with([equip], []))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-3"]
    section_rects = {
        element.stroke: element
        for element in graphic.elements
        if element.element_type == "rect"
        and element.layer == "symbol"
        and element.stroke in {"#455a64", "#3f51b5", "#1976d2", "#546e7a"}
    }

    assert section_rects["#1976d2"].width > section_rects["#3f51b5"].width
    assert section_rects["#546e7a"].width < section_rects["#1976d2"].width

    fan_circles = [
        element for element in graphic.elements
        if element.element_type == "circle" and element.stroke == "#1976d2"
    ]
    coil_lines = [
        element for element in graphic.elements
        if element.element_type == "line" and element.stroke == "#1976d2" and element.height == 0
    ]

    assert fan_circles
    assert len(coil_lines) >= 4


def test_vav_bindings_prefer_damper_reheat_and_discharge_locations() -> None:
    equip = Equipment(id="VAV-1", type=EquipmentType.VAV, controller_id="VMA-1")
    points = [
        Point(name="VAV-1 DMP POS", equipment_id="VAV-1", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="VAV-1 DAT", equipment_id="VAV-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="VAV-1 RHT VLV", equipment_id="VAV-1", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    bindings = _binding_map(generator, "graphic_vav-1")

    assert 0.2 <= bindings["VAV-1 DMP POS"].x <= 0.3
    assert 0.45 <= bindings["VAV-1 DMP POS"].y <= 0.55
    assert 0.8 <= bindings["VAV-1 DAT"].x <= 0.9
    assert 0.45 <= bindings["VAV-1 DAT"].y <= 0.55
    assert 0.5 <= bindings["VAV-1 RHT VLV"].x <= 0.6
    assert 0.45 <= bindings["VAV-1 RHT VLV"].y <= 0.55


def test_ahu_section_parser_normalizes_aliases_and_rejects_unknown_values() -> None:
    valid, invalid = GraphicsGenerator.parse_ahu_graphic_sections(
        "OA, filter_bank, CC, heating, sf, sa, mystery_box"
    )

    assert valid == [
        "outside_air",
        "filter",
        "cooling_coil",
        "heating_coil",
        "supply_fan",
        "discharge",
    ]
    assert invalid == ["mystery_box"]
