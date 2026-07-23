from pathlib import Path

from bas_assistant.generators.graphics import GraphicsGenerator, generate_graphics
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


def test_blow_through_ahu_renders_supply_fan_ahead_of_coils() -> None:
    equip = Equipment(
        id="AHU-2B",
        type=EquipmentType.AHU,
        controller_id="MPC-2B",
        template=EquipmentTemplateRef(
            template_name="ahu_blowthrough",
            parameters={
                "duct_profile": "blow_through_horizontal",
                "graphic_sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
            },
        ),
    )
    points = [
        Point(name="AHU-2B SF STATUS", equipment_id="AHU-2B", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="AHU-2B CCV CMD", equipment_id="AHU-2B", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-2b"]
    bindings = _binding_map(generator, "graphic_ahu-2b")

    assert graphic.metadata["duct_profile"] == "blow_through_horizontal"
    assert graphic.metadata["rendered_graphic_sections"] == [
        "outside_air",
        "filter",
        "supply_fan",
        "cooling_coil",
        "heating_coil",
        "discharge",
    ]
    assert bindings["AHU-2B SF STATUS"].x < bindings["AHU-2B CCV CMD"].x


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
    section_bodies = [
        element
        for element in graphic.elements
        if element.element_type == "rect"
        and element.layer == "symbol"
        and element.stroke == "#475569"
        and element.fill == "#ffffff"
    ]
    outer_casing = [
        element
        for element in graphic.elements
        if element.element_type == "rect"
        and element.layer == "symbol"
        and element.stroke == "#5b5b57"
    ]

    assert len(section_bodies) == 0
    assert outer_casing

    fan_circles = [
        element for element in graphic.elements
        if element.element_type == "circle" and element.stroke == "#1976d2"
    ]
    fan_blades = [
        element for element in graphic.elements
        if element.element_type == "line" and getattr(element, "css_class", "") == "fan-blade"
    ]
    coil_lines = [
        element for element in graphic.elements
        if element.element_type == "line" and element.stroke == "#1976d2" and element.height != 0
    ]
    filter_slashes = [
        element for element in graphic.elements
        if element.element_type == "line" and element.stroke == "#3f51b5" and element.height < 0
    ]
    damper_blades = [
        element for element in graphic.elements
        if element.element_type == "line" and element.stroke == "#455a64" and element.height > 0
    ]

    assert fan_circles
    assert len(fan_blades) == 6
    assert len(coil_lines) >= 4
    assert filter_slashes
    assert damper_blades


def test_svg_export_includes_fan_and_airflow_animation_classes() -> None:
    equip = Equipment(
        id="AHU-4",
        type=EquipmentType.AHU,
        controller_id="MPC-4",
        template=EquipmentTemplateRef(
            template_name="ahu_custom",
            parameters={
                "graphic_sections": "outside_air,filter,cooling_coil,supply_fan,discharge",
            },
        ),
    )
    generator = GraphicsGenerator(_project_with([equip], []))

    generator.generate_all()
    svg = generator._graphic_to_svg(generator.graphics["graphic_ahu-4"])

    assert "@keyframes fan-spin" in svg
    assert svg.count('class="fan-blade"') == 6
    assert 'class="airflow-path airflow-supply"' in svg


def test_svg_export_renders_station_style_binding_widgets() -> None:
    equip = Equipment(id="AHU-4B", type=EquipmentType.AHU, controller_id="MPC-4B")
    points = [
        Point(name="AHU-4B SAT", equipment_id="AHU-4B", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-4B SF STATUS", equipment_id="AHU-4B", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="AHU-4B OAD CMD", equipment_id="AHU-4B", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="AHU-4B SAT SP", equipment_id="AHU-4B", kind=PointKind.SETPOINT, direction=PointDirection.OUTPUT, units="degF"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    svg = generator._graphic_to_svg(generator.graphics["graphic_ahu-4b"])

    assert 'class="station-widget station-widget-value"' in svg
    assert 'class="station-widget station-widget-status"' in svg
    assert 'class="station-widget station-widget-command"' in svg
    assert 'class="station-widget station-widget-setpoint"' in svg
    assert 'class="station-status-lamp"' in svg
    assert ">AUTO<" in svg
    assert ">ON<" in svg


def test_binding_order_is_deterministic_for_unsorted_points() -> None:
    equip = Equipment(id="AHU-4C", type=EquipmentType.AHU, controller_id="MPC-4C")
    points = [
        Point(name="AHU-4C SF STATUS", equipment_id="AHU-4C", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="AHU-4C SAT", equipment_id="AHU-4C", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-4C OAD CMD", equipment_id="AHU-4C", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="AHU-4C DAT", equipment_id="AHU-4C", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    binding_names = [binding.point_name for binding in generator.graphics["graphic_ahu-4c"].bindings]

    assert binding_names == [
        "AHU-4C OAD CMD",
        "AHU-4C SF STATUS",
        "AHU-4C SAT",
        "AHU-4C DAT",
    ]


def test_ahu_graphic_records_isometric_asset_placements() -> None:
    equip = Equipment(
        id="AHU-5",
        type=EquipmentType.AHU,
        controller_id="MPC-5",
        template=EquipmentTemplateRef(
            template_name="ahu_custom",
            parameters={
                "graphic_sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
            },
        ),
    )
    generator = GraphicsGenerator(_project_with([equip], []))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-5"]
    placements = graphic.metadata.get("asset_placements", [])

    assert any(placement["asset_id"] == "ahu_drawthrough_doubledeck" for placement in placements)
    assert any(placement["asset_id"] == "rectangular_supply_duct" for placement in placements)
    assert any(placement["asset_id"] == "mixing_damper_bank" and placement["role"] == "section:outside_air" for placement in placements)
    assert any(placement["asset_id"] == "filter_bank_vcell" and placement["role"] == "section:filter" for placement in placements)
    assert any(placement["asset_id"] == "cooling_coil_chw" and placement["role"] == "section:cooling_coil" for placement in placements)
    assert any(placement["asset_id"] == "heating_coil_hw" and placement["role"] == "section:heating_coil" for placement in placements)
    assert any(placement["asset_id"] == "supply_fan_plenum" and placement["role"] == "section:supply_fan" for placement in placements)


def test_ahu_graphic_records_explicit_asset_point_relations() -> None:
    equip = Equipment(
        id="AHU-6",
        type=EquipmentType.AHU,
        controller_id="MPC-6",
        template=EquipmentTemplateRef(
            template_name="ahu_custom",
            parameters={
                "graphic_sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
            },
        ),
    )
    points = [
        Point(name="AHU-6 CCV CMD", equipment_id="AHU-6", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="AHU-6 SF STATUS", equipment_id="AHU-6", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="AHU-6 SAT", equipment_id="AHU-6", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-6"]
    relations = graphic.metadata.get("asset_point_relations", [])

    cooling_valve = next(relation for relation in relations if relation["point_name"] == "AHU-6 CCV CMD")
    supply_fan = next(relation for relation in relations if relation["point_name"] == "AHU-6 SF STATUS")
    sat = next(relation for relation in relations if relation["point_name"] == "AHU-6 SAT")

    assert cooling_valve["asset_id"] == "cooling_coil_chw"
    assert cooling_valve["asset_role"] == "section:cooling_coil"
    assert cooling_valve["component"] == "cooling_valve"
    assert cooling_valve["target_key"] == "cooling_valve"
    assert cooling_valve["visual_hint"] == "valve_position"

    assert supply_fan["asset_id"] == "supply_fan_plenum"
    assert supply_fan["asset_role"] == "section:supply_fan"
    assert supply_fan["component"] == "supply_fan"
    assert supply_fan["target_key"] == "fan_status"
    assert supply_fan["visual_hint"] == "fan_spin"

    assert sat["asset_role"] in {"section:discharge", "internal_supply_path"}
    assert sat["relation_kind"] == "telemetry"


def test_ahu_specialty_sections_use_realistic_assets() -> None:
    equip = Equipment(
        id="AHU-7",
        type=EquipmentType.AHU,
        controller_id="MPC-7",
        template=EquipmentTemplateRef(
            template_name="ahu_specialty",
            parameters={
                "graphic_sections": "outside_air,energy_recovery,filter,humidifier,return_fan,discharge",
            },
        ),
    )
    points = [
        Point(name="AHU-7 HUMIDITY", equipment_id="AHU-7", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="%"),
        Point(name="AHU-7 RF STATUS", equipment_id="AHU-7", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="AHU-7 ENERGY WHEEL STATUS", equipment_id="AHU-7", kind=PointKind.STATUS, direction=PointDirection.INPUT),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-7"]
    placements = graphic.metadata.get("asset_placements", [])

    assert any(placement["asset_id"] == "energy_recovery_wheel" for placement in placements)
    assert any(placement["asset_id"] == "steam_humidifier_grid" for placement in placements)
    assert any(placement["asset_id"] == "relief_fan_housed" and placement["role"] == "section:return_fan" for placement in placements)


def test_coil_sections_render_hydronic_accessories() -> None:
    equip = Equipment(
        id="AHU-8",
        type=EquipmentType.AHU,
        controller_id="MPC-8",
        template=EquipmentTemplateRef(
            template_name="ahu_hydronic",
            parameters={
                "graphic_sections": "outside_air,cooling_coil,heating_coil,discharge",
            },
        ),
    )
    points = [
        Point(name="AHU-8 CCV CMD", equipment_id="AHU-8", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="AHU-8 HCV CMD", equipment_id="AHU-8", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-8"]

    assert any(element.css_class == "pipe-flange" for element in graphic.elements)
    assert any(element.css_class == "flex-connector" for element in graphic.elements)
    assert any(element.css_class == "pipe-strainer" for element in graphic.elements)


def test_vav_graphic_uses_isometric_asset_layout() -> None:
    equip = Equipment(id="VAV-2", type=EquipmentType.VAV, controller_id="VMA-2")
    points = [
        Point(name="VAV-2 DMP POS", equipment_id="VAV-2", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="VAV-2 DAT", equipment_id="VAV-2", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="VAV-2 RHT VLV", equipment_id="VAV-2", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_vav-2"]
    placements = graphic.metadata.get("asset_placements", [])

    assert any(placement["asset_id"] == "vav_reheat_terminal" for placement in placements)
    assert any(element.css_class == "vav-shell" for element in graphic.elements)
    assert any(element.css_class == "flex-connector" for element in graphic.elements)
    assert any(element.css_class == "damper-frame" for element in graphic.elements)
    assert any(element.css_class == "discharge-sensor" for element in graphic.elements)
    assert any(element.css_class == "airflow-path airflow-supply" for element in graphic.elements)

    relations = graphic.metadata.get("asset_point_relations", [])
    assert any(relation["asset_id"] == "vav_reheat_terminal" for relation in relations)


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

    assert 0.28 <= bindings["VAV-1 DMP POS"].x <= 0.36
    assert 0.38 <= bindings["VAV-1 DMP POS"].y <= 0.48
    assert 0.8 <= bindings["VAV-1 DAT"].x <= 0.9
    assert 0.38 <= bindings["VAV-1 DAT"].y <= 0.48
    assert 0.52 <= bindings["VAV-1 RHT VLV"].x <= 0.6
    assert 0.38 <= bindings["VAV-1 RHT VLV"].y <= 0.48


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


def test_rtu_graphic_uses_packaged_rooftop_asset_and_dx_components() -> None:
    equip = Equipment(id="RTU-1", type=EquipmentType.RTU, controller_id="MPC-RTU")
    points = [
        Point(name="RTU-1 DX SAT", equipment_id="RTU-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="RTU-1 COMP STATUS", equipment_id="RTU-1", kind=PointKind.STATUS, direction=PointDirection.INPUT),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_rtu-1"]
    placements = graphic.metadata.get("asset_placements", [])

    assert any(placement["asset_id"] == "rtu_packaged_rooftop" for placement in placements)
    assert any(placement["asset_id"] == "cooling_coil_dx" for placement in placements)
    assert any(placement["role"] == "condenser_fan" for placement in placements)


def test_plant_equipment_graphics_use_isometric_assets() -> None:
    equipment = [
        Equipment(id="CH-1", type=EquipmentType.CHILLER, controller_id="PLANT-1"),
        Equipment(id="BLR-1", type=EquipmentType.BOILER, controller_id="PLANT-1"),
        Equipment(id="CHWP-1", type=EquipmentType.PUMP_CHW, controller_id="PLANT-1"),
        Equipment(id="CT-1", type=EquipmentType.COOLING_TOWER, controller_id="PLANT-1"),
    ]
    generator = GraphicsGenerator(_project_with(equipment, []))

    generator.generate_all()

    assert any(
        placement["asset_id"] == "chiller_air_cooled"
        for placement in generator.graphics["graphic_ch-1"].metadata.get("asset_placements", [])
    )
    assert any(
        placement["asset_id"] == "boiler_condensing"
        for placement in generator.graphics["graphic_blr-1"].metadata.get("asset_placements", [])
    )
    assert any(
        placement["asset_id"] == "pump_end_suction"
        for placement in generator.graphics["graphic_chwp-1"].metadata.get("asset_placements", [])
    )
    assert any(
        placement["asset_id"] == "cooling_tower_open_cell"
        for placement in generator.graphics["graphic_ct-1"].metadata.get("asset_placements", [])
    )


def test_plant_graphics_choose_more_realistic_variants_from_subtype_tags_and_points() -> None:
    equipment = [
        Equipment(id="CH-2", type=EquipmentType.CHILLER, subtype="Water-Cooled Centrifugal", controller_id="PLANT-2"),
        Equipment(id="BLR-2", type=EquipmentType.BOILER, subtype="Firetube", controller_id="PLANT-2"),
        Equipment(id="HWP-2", type=EquipmentType.PUMP_HW, tags=["vertical-inline"], controller_id="PLANT-2"),
        Equipment(id="CT-2", type=EquipmentType.COOLING_TOWER, controller_id="PLANT-2"),
    ]
    points = [
        Point(name="CH-2 CW SUPPLY TEMP", equipment_id="CH-2", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="BLR-2 BURNER MANAGEMENT STATUS", equipment_id="BLR-2", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="CT-2 CELL FAN STATUS", equipment_id="CT-2", kind=PointKind.STATUS, direction=PointDirection.INPUT),
    ]
    generator = GraphicsGenerator(_project_with(equipment, points))

    generator.generate_all()

    assert any(
        placement["asset_id"] == "chiller_centrifugal_water_cooled"
        for placement in generator.graphics["graphic_ch-2"].metadata.get("asset_placements", [])
    )
    assert any(
        placement["asset_id"] == "boiler_firetube"
        for placement in generator.graphics["graphic_blr-2"].metadata.get("asset_placements", [])
    )
    assert any(
        placement["asset_id"] == "pump_vertical_inline"
        for placement in generator.graphics["graphic_hwp-2"].metadata.get("asset_placements", [])
    )
    assert any(
        placement["asset_id"] == "cooling_tower_induced_draft"
        for placement in generator.graphics["graphic_ct-2"].metadata.get("asset_placements", [])
    )


def test_specialty_ahu_points_bind_to_energy_recovery_and_uv_sections() -> None:
    equip = Equipment(
        id="AHU-9",
        type=EquipmentType.AHU,
        controller_id="MPC-9",
        template=EquipmentTemplateRef(
            template_name="ahu_iaq",
            parameters={
                "graphic_sections": "outside_air,energy_recovery,uv,supply_fan,discharge",
            },
        ),
    )
    points = [
        Point(name="AHU-9 ENERGY WHEEL STATUS", equipment_id="AHU-9", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="AHU-9 UV LAMP STATUS", equipment_id="AHU-9", kind=PointKind.STATUS, direction=PointDirection.INPUT),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    bindings = _binding_map(generator, "graphic_ahu-9")
    relations = generator.graphics["graphic_ahu-9"].metadata.get("asset_point_relations", [])

    assert 0.24 <= bindings["AHU-9 ENERGY WHEEL STATUS"].x <= 0.42
    assert 0.34 <= bindings["AHU-9 ENERGY WHEEL STATUS"].y <= 0.56
    assert 0.44 <= bindings["AHU-9 UV LAMP STATUS"].x <= 0.62
    assert 0.34 <= bindings["AHU-9 UV LAMP STATUS"].y <= 0.56

    wheel = next(relation for relation in relations if relation["point_name"] == "AHU-9 ENERGY WHEEL STATUS")
    uv = next(relation for relation in relations if relation["point_name"] == "AHU-9 UV LAMP STATUS")
    assert wheel["asset_role"] == "section:energy_recovery"
    assert wheel["visual_hint"] == "wheel_rotation"
    assert uv["asset_role"] == "section:uv"
    assert uv["visual_hint"] == "uv_bank_state"


def test_water_side_and_tower_point_names_map_to_realistic_anchors() -> None:
    equipment = [
        Equipment(id="CH-3", type=EquipmentType.CHILLER, controller_id="PLANT-3"),
        Equipment(id="CT-3", type=EquipmentType.COOLING_TOWER, controller_id="PLANT-3"),
    ]
    points = [
        Point(name="CH-3 CHWS TEMP", equipment_id="CH-3", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="CH-3 CHWR TEMP", equipment_id="CH-3", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="CT-3 CELL FAN STATUS", equipment_id="CT-3", kind=PointKind.STATUS, direction=PointDirection.INPUT),
    ]
    generator = GraphicsGenerator(_project_with(equipment, points))

    generator.generate_all()
    chiller_bindings = _binding_map(generator, "graphic_ch-3")
    tower_bindings = _binding_map(generator, "graphic_ct-3")
    tower_relations = generator.graphics["graphic_ct-3"].metadata.get("asset_point_relations", [])

    assert 0.14 <= chiller_bindings["CH-3 CHWS TEMP"].x <= 0.26
    assert 0.68 <= chiller_bindings["CH-3 CHWS TEMP"].y <= 0.8
    assert 0.74 <= chiller_bindings["CH-3 CHWR TEMP"].x <= 0.86
    assert 0.68 <= chiller_bindings["CH-3 CHWR TEMP"].y <= 0.8
    assert 0.44 <= tower_bindings["CT-3 CELL FAN STATUS"].x <= 0.56
    assert 0.18 <= tower_bindings["CT-3 CELL FAN STATUS"].y <= 0.3

    tower_fan = next(relation for relation in tower_relations if relation["point_name"] == "CT-3 CELL FAN STATUS")
    assert tower_fan["visual_hint"] == "fan_spin"


def test_graphics_confidence_records_explicit_and_inferred_decisions() -> None:
    equip = Equipment(
        id="AHU-10",
        type=EquipmentType.AHU,
        subtype="Vertical Upflow Fan Array",
        controller_id="MPC-10",
        template=EquipmentTemplateRef(
            template_name="ahu_vertical",
            parameters={
                "graphic_sections": "outside_air,filter,cooling_coil,supply_fan,discharge",
            },
        ),
        tags=["fan-array"],
    )
    points = [
        Point(name="AHU-10 SAT", equipment_id="AHU-10", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-10 SF VFD SPEED", equipment_id="AHU-10", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="%"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-10"]
    confidence = graphic.metadata["graphics_confidence"]
    inferences = graphic.metadata["graphics_inference"]

    assert graphic.metadata["duct_profile"] == "vertical_upflow"
    assert inferences["graphic_sections"]["source"] == "explicit_template"
    assert inferences["duct_profile"]["source"] == "subtype_or_tag_inference"
    assert confidence["score"] >= 0.8
    assert confidence["unclassified_points"] == 0


def test_blow_through_duct_profile_is_inferred_from_subtype_text() -> None:
    equip = Equipment(
        id="AHU-10B",
        type=EquipmentType.AHU,
        subtype="Blow-through air handler",
        controller_id="MPC-10B",
        template=EquipmentTemplateRef(
            template_name="ahu_blowthrough_inferred",
            parameters={
                "graphic_sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
            },
        ),
    )
    generator = GraphicsGenerator(_project_with([equip], []))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-10b"]

    assert graphic.metadata["duct_profile"] == "blow_through_horizontal"
    assert graphic.metadata["rendered_graphic_sections"][2] == "supply_fan"


def test_graphics_confidence_flags_unclassified_noisy_points() -> None:
    equip = Equipment(id="AHU-11", type=EquipmentType.AHU, controller_id="MPC-11")
    points = [
        Point(name="AHU-11 FLT DP", equipment_id="AHU-11", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="inWC"),
        Point(name="AHU-11 SMOKE DET", equipment_id="AHU-11", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="AHU-11 FREEZE STAT", equipment_id="AHU-11", kind=PointKind.STATUS, direction=PointDirection.INPUT),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-11"]
    confidence = graphic.metadata["graphics_confidence"]
    issues = graphic.metadata.get("graphics_issues", [])

    assert confidence["classified_points"] >= 1
    assert confidence["unclassified_points"] >= 1
    assert any(issue["code"] == "unclassified_point" and issue["point_name"] == "AHU-11 SMOKE DET" for issue in issues)
    assert any(issue["code"] == "unclassified_point" and issue["point_name"] == "AHU-11 FREEZE STAT" for issue in issues)


def test_noisy_real_world_names_still_bind_core_ahu_components() -> None:
    equip = Equipment(id="AHU-12", type=EquipmentType.AHU, controller_id="MPC-12")
    points = [
        Point(name="AHU-12 LAT", equipment_id="AHU-12", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-12 SF VFD SPEED", equipment_id="AHU-12", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="%"),
        Point(name="AHU-12 OAD POS", equipment_id="AHU-12", kind=PointKind.ACTUATOR, direction=PointDirection.OUTPUT, units="%"),
        Point(name="AHU-12 FLT DP", equipment_id="AHU-12", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="inWC"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    bindings = _binding_map(generator, "graphic_ahu-12")
    confidence = generator.graphics["graphic_ahu-12"].metadata["graphics_confidence"]

    assert bindings["AHU-12 LAT"].x > 0.8
    assert 0.02 <= bindings["AHU-12 SF VFD SPEED"].x <= 0.98
    assert 0.1 <= bindings["AHU-12 OAD POS"].x <= 0.2
    assert 0.28 <= bindings["AHU-12 FLT DP"].x <= 0.38
    assert confidence["score"] >= 0.75


def test_ahu_sections_infer_from_equipment_metadata_and_select_realistic_assets() -> None:
    equip = Equipment(
        id="AHU-13",
        type=EquipmentType.AHU,
        controller_id="MPC-13",
        subtype="Energy recovery draw-through air handler",
        notes="Unit includes prefilter section, UV-C lamps, discharge attenuator, and return fan section.",
        tags=["economizer", "fan-array-ready"],
    )
    points = [
        Point(name="AHU-13 SAT", equipment_id="AHU-13", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-13 UV STATUS", equipment_id="AHU-13", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="AHU-13 FILTER DP", equipment_id="AHU-13", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="inwc"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    graphic = generator.graphics["graphic_ahu-13"]
    sections = graphic.metadata["graphic_sections"]
    placements = graphic.metadata.get("asset_placements", [])

    assert "prefilter" in sections
    assert "energy_recovery" in sections
    assert "uv" in sections
    assert "sound_attenuator" in sections
    assert "return_fan" in sections
    assert any(placement["asset_id"] == "filter_bank_panel" and placement["role"] == "section:prefilter" for placement in placements)
    assert any(placement["asset_id"] == "energy_recovery_wheel" and placement["role"] == "section:energy_recovery" for placement in placements)
    assert any(placement["asset_id"] == "uv_c_lamp_bank" and placement["role"] == "section:uv" for placement in placements)
    assert any(placement["asset_id"] == "sound_attenuator_baffle" and placement["role"] == "section:sound_attenuator" for placement in placements)


def test_standard_ahu_supply_fan_defaults_to_scroll_without_plenum_evidence() -> None:
    equip = Equipment(
        id="AHU-14",
        type=EquipmentType.AHU,
        controller_id="MPC-14",
        notes="Draw-through office air handler with belt-driven supply fan.",
        template=EquipmentTemplateRef(
            template_name="ahu_custom",
            parameters={
                "graphic_sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
            },
        ),
    )
    generator = GraphicsGenerator(_project_with([equip], []))

    generator.generate_all()
    placements = generator.graphics["graphic_ahu-14"].metadata.get("asset_placements", [])

    assert any(placement["asset_id"] == "supply_fan_scroll" and placement["role"] == "section:supply_fan" for placement in placements)


def test_dense_bindings_spread_across_grid_for_many_points_on_same_component() -> None:
    equip = Equipment(id="AHU-15", type=EquipmentType.AHU, controller_id="MPC-15")
    points = [
        Point(name=f"AHU-15 SF STATUS {index}", equipment_id="AHU-15", kind=PointKind.STATUS, direction=PointDirection.INPUT)
        for index in range(1, 8)
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    bindings = [binding for binding in generator.graphics["graphic_ahu-15"].bindings if "SF STATUS" in binding.point_name]
    unique_x = {round(binding.x, 3) for binding in bindings}
    unique_y = {round(binding.y, 3) for binding in bindings}

    assert len(unique_x) > 1
    assert len(unique_y) > 3


def test_binding_labels_trim_equipment_prefix_for_operator_readability() -> None:
    equip = Equipment(id="AHU-10", type=EquipmentType.AHU, controller_id="MPC-10")
    points = [
        Point(name="AHU-10 SAT", equipment_id="AHU-10", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-10 SF STATUS", equipment_id="AHU-10", kind=PointKind.STATUS, direction=PointDirection.INPUT),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    generator.generate_all()
    bindings = _binding_map(generator, "graphic_ahu-10")

    assert bindings["AHU-10 SAT"].label == "SAT"
    assert bindings["AHU-10 SF STATUS"].label == "SF STATUS"


def test_discharge_air_points_prefer_discharge_anchor_over_supply_temp_match() -> None:
    equip = Equipment(id="AHU-11", type=EquipmentType.AHU, controller_id="MPC-11")
    points = [
        Point(name="AHU-11 DAT", equipment_id="AHU-11", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-11 SAT", equipment_id="AHU-11", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
    ]
    generator = GraphicsGenerator(_project_with([equip], points))

    assert generator._classify_point_component(points[0], EquipmentType.AHU) == "discharge_temp"
    assert generator._classify_point_component(points[1], EquipmentType.AHU) == "supply_temp"


def test_generate_graphics_fixture_output_contains_station_widget_markup(tmp_path: Path) -> None:
    equip = Equipment(id="AHU-12", type=EquipmentType.AHU, controller_id="MPC-12")
    points = [
        Point(name="AHU-12 SAT", equipment_id="AHU-12", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-12 SF STATUS", equipment_id="AHU-12", kind=PointKind.STATUS, direction=PointDirection.INPUT),
    ]
    project = _project_with([equip], points)

    result = generate_graphics(project, tmp_path)
    svg_text = result["svg"][0].read_text(encoding="utf-8")

    assert 'class="station-widget station-widget-value"' in svg_text
    assert 'class="station-widget station-widget-status"' in svg_text
    assert ">SAT<" in svg_text
    assert ">SF STATUS<" in svg_text


def test_full_system_generation_includes_airside_and_plant_overviews() -> None:
    equipment = [
        Equipment(id="CHLR-1", type=EquipmentType.CHILLER, subtype="Centrifugal", controller_id="CPC-1"),
        Equipment(id="CHWP-1", type=EquipmentType.PUMP_CHW, controller_id="CPC-1"),
        Equipment(id="CWP-1", type=EquipmentType.PUMP_CW, controller_id="CPC-1"),
        Equipment(id="CT-1", type=EquipmentType.COOLING_TOWER, controller_id="CPC-1"),
        Equipment(id="BLR-1", type=EquipmentType.BOILER, subtype="Condensing", controller_id="CPC-1"),
        Equipment(id="HWP-1", type=EquipmentType.PUMP_HW, controller_id="CPC-1"),
        Equipment(id="HX-1", type=EquipmentType.HEAT_EXCHANGER, controller_id="CPC-1"),
        Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id="MPC-1", child_equipment_ids=["VAV-101"]),
        Equipment(id="VAV-101", type=EquipmentType.VAV, controller_id="VAV-101", parent_equipment_id="AHU-1"),
    ]
    points = [
        Point(name="CHLR-1 STATUS", equipment_id="CHLR-1", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="CHLR-1 CHWST", equipment_id="CHLR-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="CHWP-1 FLOW", equipment_id="CHWP-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="GPM"),
        Point(name="CWP-1 STATUS", equipment_id="CWP-1", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="CT-1 FAN STATUS", equipment_id="CT-1", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="BLR-1 STATUS", equipment_id="BLR-1", kind=PointKind.STATUS, direction=PointDirection.INPUT),
        Point(name="BLR-1 HWS", equipment_id="BLR-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="HWP-1 FLOW", equipment_id="HWP-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="GPM"),
        Point(name="HX-1 PRI LWT", equipment_id="HX-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="AHU-1 SAT", equipment_id="AHU-1", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="degF"),
        Point(name="VAV-101 FLOW", equipment_id="VAV-101", kind=PointKind.SENSOR, direction=PointDirection.INPUT, units="CFM"),
    ]
    generator = GraphicsGenerator(_project_with(equipment, points))

    generator.generate_all()

    assert "graphic_system_ahu-1" in generator.graphics
    assert "graphic_system_cooling_plant" in generator.graphics
    assert "graphic_system_heating_plant" in generator.graphics

    cooling = generator.graphics["graphic_system_cooling_plant"]
    heating = generator.graphics["graphic_system_heating_plant"]
    cooling_ids = {
        placement["equipment_id"]
        for placement in cooling.metadata["asset_placements"]
    }
    heating_ids = {
        placement["equipment_id"]
        for placement in heating.metadata["asset_placements"]
    }

    assert {"CHLR-1", "CHWP-1", "CWP-1", "CT-1", "AHU-1"} <= cooling_ids
    assert {"BLR-1", "HWP-1", "HX-1", "AHU-1"} <= heating_ids
    assert {binding.point_name for binding in cooling.bindings} >= {"CHLR-1 STATUS", "CHLR-1 CHWST"}
    assert {binding.point_name for binding in heating.bindings} >= {"BLR-1 STATUS", "BLR-1 HWS"}
