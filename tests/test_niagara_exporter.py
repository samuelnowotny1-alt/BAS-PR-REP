import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from bas_assistant.exporters.niagara import NiagaraExporter
from bas_assistant.models import (
    Controller,
    ControllerNetworkAddress,
    Equipment,
    EquipmentType,
    Point,
    PointDirection,
    PointKind,
    Project,
    ProjectMetadata,
    Protocol,
)
from bas_assistant.models.equipment import EquipmentTemplateRef


def build_project() -> Project:
    project = Project(
        metadata=ProjectMetadata(
            project_id="niagara-test",
            name="Niagara Test",
            client="Codex",
            timezone="America/Chicago",
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            name="Main Plant Controller",
            vendor="JCI",
            model="M4-CGM",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[
                ControllerNetworkAddress(
                    protocol=Protocol.BACNET_IP,
                    address="10.1.2.3",
                    network_number=2001,
                )
            ],
        )
    )
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            building="Admin",
            floor="1",
            served_area="Office Wing",
            controller_id="MPC-1",
            child_equipment_ids=["VAV-101"],
        )
    )
    project.add_equipment(
        Equipment(
            id="VAV-101",
            type=EquipmentType.VAV,
            building="Admin",
            floor="1",
            parent_equipment_id="AHU-1",
            controller_id="MPC-1",
        )
    )
    project.add_point(
        Point(
            name="AHU-1_SAT",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=PointKind.SENSOR,
            direction=PointDirection.INPUT,
            units="degF",
            bacnet_object_type="AI",
            bacnet_instance=101,
            description="Supply air temperature",
        )
    )
    project.add_point(
        Point(
            name="AHU-1_SAT_SP",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=PointKind.SETPOINT,
            direction=PointDirection.OUTPUT,
            units="degF",
            bacnet_object_type="AV",
            bacnet_instance=102,
            description="Supply air temperature setpoint",
        )
    )
    return project


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_niagara_export_includes_ord_hierarchy_px_and_bindings(tmp_path: Path) -> None:
    exporter = NiagaraExporter(build_project())

    result = exporter.export(tmp_path)

    assert result.success
    wxf_dir = tmp_path / "niagara-test_wxf"
    station = load_json(wxf_dir / "station.json")
    navigation = load_json(wxf_dir / "navigation.json")
    points = load_json(wxf_dir / "points.json")
    devices = load_json(wxf_dir / "devices.json")
    alarms = load_json(wxf_dir / "alarms.json")
    schedules = load_json(wxf_dir / "schedules.json")
    trends = load_json(wxf_dir / "trends.json")
    ahu_page = load_json(wxf_dir / "graphics" / "AHU-1.json")
    station_xml = ET.parse(wxf_dir / "station.wxf").getroot()
    ahu_page_xml = ET.parse(wxf_dir / "graphics" / "AHU-1.px").getroot()

    assert station["station"]["ord"] == "station:|slot:/"
    assert any(slot["slotType"] == "px:PxContainer" for slot in station["station"]["slots"])
    assert station_xml.tag == "station"
    assert station_xml.find("./slots") is not None
    assert station_xml.find("./slots/slot[@name='Px']") is not None

    navigation_xml = ET.parse(wxf_dir / "navigation.wxf").getroot()
    assert navigation_xml.find("./children/navNode[@name='Admin']") is not None

    building = navigation["navigation"]["children"][0]
    floor = building["children"][0]
    equipment = floor["children"][0]
    point_nav = equipment["children"][0]
    assert equipment["pxPageRef"]["ord"] == "station:|slot:/Px/Equipment/AHU-1"
    assert equipment["parentOrd"] == f"station:|slot:{floor['slotPath']}"
    assert point_nav["annotations"]["pointOrd"] == "station:|slot:/Drivers/BacnetNetwork/MPC-1/Points/AHU-1_SAT"

    point_export = points["points"][0]
    assert point_export["ord"] == "station:|slot:/Drivers/BacnetNetwork/MPC-1/Points/AHU-1_SAT"
    assert point_export["proxyExt"]["bacnetProxyExt"]["objectType"] == "AI"
    assert point_export["facets"]["units"] == "degF"
    assert point_export["annotations"]["equipmentOrd"] == "station:|slot:/Config/Equipment/Admin/1/AHU-1"
    points_xml = ET.parse(wxf_dir / "points.wxf").getroot()
    assert points_xml.find("./point/proxyExt/bacnetProxyExt/objectType") is not None
    assert points_xml.findtext("./point/proxyExt/bacnetProxyExt/objectType") == "AI"
    assert points_xml.findtext("./point/pointBinding/ord") == point_export["pointBinding"]["ord"]

    device_export = devices["devices"][0]
    assert device_export["ord"] == "station:|slot:/Drivers/BacnetNetwork/MPC-1"
    assert device_export["children"][0]["parentOrd"] == device_export["ord"]
    assert device_export["networkExt"]["addresses"][0]["address"] == "10.1.2.3"
    devices_xml = ET.parse(wxf_dir / "devices.wxf").getroot()
    assert devices_xml.findtext("./device/networkExt/addresses/address/host") == "10.1.2.3"

    if alarms["alarms"]:
        alarms_xml = ET.parse(wxf_dir / "alarms.wxf").getroot()
        assert alarms_xml.find("./alarmExt/limits/low") is not None or alarms_xml.find("./alarmExt/limits/high") is not None

    schedules_xml = ET.parse(wxf_dir / "schedules.wxf").getroot()
    assert schedules["schedules"][0]["entries"]["monday"]["occupied"] == "07:00"
    assert schedules_xml.findtext("./schedule/entries/day[@name='monday']/occupied") == "07:00"

    if trends["trends"]:
        trends_xml = ET.parse(wxf_dir / "trends.wxf").getroot()
        assert trends_xml.findtext("./historyExt/historyConfig/interval") == "15m"
        assert trends_xml.findtext("./historyExt/historyConfig/enabled") == "true"

    page = ahu_page["pxPage"]
    assert page["ord"] == "station:|slot:/Px/Equipment/AHU-1"
    assert page["navigation"]["back"] == "station:|slot:/Px/Dashboard/dashboard_main"
    assert page["equipmentOrd"] == "station:|slot:/Config/Equipment/Admin/1/AHU-1"
    assert page["components"]["root"]["children"][0]["parentId"] == "root"
    assert page["bindings"][0]["sourceOrd"].startswith("station:|slot:/Drivers/BacnetNetwork/MPC-1/Points/")
    assert ahu_page_xml.tag == "pxPage"
    assert ahu_page_xml.find("./bindings") is not None
    assert ahu_page_xml.find("./components/canvas/children/component[@type='px:BoundLabel']") is not None
    assert ahu_page_xml.find("./bindings/binding[@type='sensor']") is not None
    assert ahu_page_xml.find("./navigation/breadcrumbs/crumb") is not None

    bog_path = tmp_path / "niagara-test.bog"
    assert bog_path.exists()
    with zipfile.ZipFile(bog_path) as archive:
        names = set(archive.namelist())
    assert "station.json" in names
    assert "station.wxf" in names
    assert "graphics/AHU-1.json" in names
    assert "graphics/AHU-1.px" in names


def test_niagara_json_and_xml_outputs_stay_structurally_aligned(tmp_path: Path) -> None:
    exporter = NiagaraExporter(build_project())

    result = exporter.export(tmp_path)

    assert result.success
    wxf_dir = tmp_path / "niagara-test_wxf"

    station_json = load_json(wxf_dir / "station.json")["station"]
    points_json = load_json(wxf_dir / "points.json")["points"]
    devices_json = load_json(wxf_dir / "devices.json")["devices"]
    navigation_json = load_json(wxf_dir / "navigation.json")["navigation"]
    ahu_page_json = load_json(wxf_dir / "graphics" / "AHU-1.json")["pxPage"]

    station_xml = ET.parse(wxf_dir / "station.wxf").getroot()
    points_xml = ET.parse(wxf_dir / "points.wxf").getroot()
    devices_xml = ET.parse(wxf_dir / "devices.wxf").getroot()
    navigation_xml = ET.parse(wxf_dir / "navigation.wxf").getroot()
    ahu_page_xml = ET.parse(wxf_dir / "graphics" / "AHU-1.px").getroot()

    assert len(station_json["slots"]) == len(station_xml.findall("./slots/slot"))
    assert len(points_json) == len(points_xml.findall("./point"))
    assert len(devices_json) == len(devices_xml.findall("./device"))
    assert len(navigation_json["children"]) == len(navigation_xml.findall("./children/navNode"))

    point_ords_json = sorted(point["ord"] for point in points_json)
    point_ords_xml = sorted(point.attrib["ord"] for point in points_xml.findall("./point"))
    assert point_ords_json == point_ords_xml

    device_ords_json = sorted(device["ord"] for device in devices_json)
    device_ords_xml = sorted(device.attrib["ord"] for device in devices_xml.findall("./device"))
    assert device_ords_json == device_ords_xml

    component_count_json = len(ahu_page_json["components"]["root"]["children"])
    component_count_xml = len(ahu_page_xml.findall("./components/canvas/children/component"))
    assert component_count_json == component_count_xml

    binding_ords_json = sorted(binding["sourceOrd"] for binding in ahu_page_json["bindings"] if "sourceOrd" in binding)
    binding_ords_xml = sorted(
        binding.findtext("sourceOrd", default="")
        for binding in ahu_page_xml.findall("./bindings/binding")
        if binding.find("sourceOrd") is not None
    )
    assert binding_ords_json == binding_ords_xml


def test_niagara_export_uses_section_based_ahu_layout(tmp_path: Path) -> None:
    project = build_project()
    ahu = project.get_equipment("AHU-1")
    assert ahu is not None
    ahu.template = EquipmentTemplateRef(
        template_name="ahu_custom",
        parameters={
            "graphic_sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
        },
    )
    project.add_point(
        Point(
            name="AHU-1_CCV_CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=PointKind.ACTUATOR,
            direction=PointDirection.OUTPUT,
            units="%",
            bacnet_object_type="AO",
            bacnet_instance=103,
            description="Cooling coil valve command",
        )
    )

    exporter = NiagaraExporter(project)
    result = exporter.export(tmp_path)

    assert result.success
    ahu_page = load_json(tmp_path / "niagara-test_wxf" / "graphics" / "AHU-1.json")["pxPage"]
    children = ahu_page["components"]["root"]["children"]
    bindings = {binding["label"]: binding for binding in ahu_page["bindings"]}
    cooling_valve_widget = next(
        component for component in children
        if component["slotType"] == "px:BoundLabel" and component["annotations"].get("fullPointName") == "AHU-1_CCV_CMD"
    )

    assert bindings["CCV CMD"]["sourceOrd"].endswith("/AHU-1_CCV_CMD")
    assert bindings["CCV CMD"]["fullLabel"] == "AHU-1_CCV_CMD"
    assert cooling_valve_widget["displayName"] == "CCV CMD"
    assert cooling_valve_widget["position"]["width"] < 240
    assert 460 <= cooling_valve_widget["position"]["x"] <= 560
    assert cooling_valve_widget["position"]["y"] < 180
    rect_count = sum(1 for component in children if component["slotType"] == "px:Rect")
    assert rect_count >= 6


def test_niagara_preview_components_include_rendering_style_metadata() -> None:
    exporter = NiagaraExporter(build_project())

    pages = exporter.preview_pages()

    ahu_page = next(page for page in pages if page.get("slotPath") == "/Px/Equipment/AHU-1")
    children = ahu_page["components"]["root"]["children"]
    line_component = next(component for component in children if component["slotType"] == "px:Line")
    text_component = next(component for component in children if component["slotType"] == "px:Text")

    assert line_component["style"]["strokeWidth"] >= 1
    assert text_component["style"]["fontSize"] >= 8
    assert text_component["style"]["fontFamily"] == "Arial"


def test_niagara_preview_pages_use_compact_binding_labels() -> None:
    exporter = NiagaraExporter(build_project())

    pages = exporter.preview_pages()

    ahu_page = next(page for page in pages if page.get("slotPath") == "/Px/Equipment/AHU-1")
    labels = {binding["fullLabel"]: binding["label"] for binding in ahu_page["bindings"]}
    bound_labels = {
        component["annotations"].get("fullPointName"): component["displayName"]
        for component in ahu_page["components"]["root"]["children"]
        if component["slotType"] == "px:BoundLabel"
    }

    assert labels["AHU-1_SAT"] == "SAT"
    assert labels["AHU-1_SAT_SP"] == "SAT SP"
    assert bound_labels["AHU-1_SAT"] == "SAT"
    assert bound_labels["AHU-1_SAT_SP"] == "SAT SP"


def test_dashboard_preview_cards_clear_header_band() -> None:
    exporter = NiagaraExporter(build_project())

    dashboard_page = exporter.preview_pages()[0]
    children = dashboard_page["components"]["root"]["children"]
    first_card = next(component for component in children if component["slotType"] == "px:LinkButton")

    assert dashboard_page["displayName"] == "Dashboard"
    assert first_card["position"]["y"] >= 100


def test_niagara_exports_connected_system_pages_with_live_bindings(tmp_path: Path) -> None:
    project = build_project()
    plant_equipment = [
        Equipment(id="CHLR-1", type=EquipmentType.CHILLER, subtype="Centrifugal", controller_id="MPC-1"),
        Equipment(id="CHWP-1", type=EquipmentType.PUMP_CHW, controller_id="MPC-1"),
        Equipment(id="CWP-1", type=EquipmentType.PUMP_CW, controller_id="MPC-1"),
        Equipment(id="CT-1", type=EquipmentType.COOLING_TOWER, controller_id="MPC-1"),
        Equipment(id="BLR-1", type=EquipmentType.BOILER, subtype="Condensing", controller_id="MPC-1"),
        Equipment(id="HWP-1", type=EquipmentType.PUMP_HW, controller_id="MPC-1"),
        Equipment(id="HX-1", type=EquipmentType.HEAT_EXCHANGER, controller_id="MPC-1"),
    ]
    for equipment in plant_equipment:
        project.add_equipment(equipment)
        project.add_point(
            Point(
                name=f"{equipment.id} STATUS",
                equipment_id=equipment.id,
                controller_id="MPC-1",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
                bacnet_object_type="BI",
            )
        )

    exporter = NiagaraExporter(project)
    pages = exporter.preview_pages()
    slot_paths = {str(page["slotPath"]) for page in pages}

    assert "/Px/Systems/graphic_system_ahu-1" in slot_paths
    assert "/Px/Systems/graphic_system_cooling_plant" in slot_paths
    assert "/Px/Systems/graphic_system_heating_plant" in slot_paths

    cooling_page = next(
        page for page in pages
        if page["slotPath"] == "/Px/Systems/graphic_system_cooling_plant"
    )
    assert any(
        binding.get("fullLabel") == "CHLR-1 STATUS"
        for binding in cooling_page["bindings"]
    )
    assert any(
        component["slotType"] == "px:LinkButton"
        and component["displayName"] == "CHLR-1"
        for component in cooling_page["components"]["root"]["children"]
    )

    result = exporter.export(tmp_path)
    assert result.success
    graphics_dir = tmp_path / "niagara-test_wxf" / "graphics"
    assert (graphics_dir / "graphic_system_ahu-1.px").exists()
    assert (graphics_dir / "graphic_system_cooling_plant.px").exists()
    assert (graphics_dir / "graphic_system_heating_plant.px").exists()

    cooling_xml = ET.parse(graphics_dir / "graphic_system_cooling_plant.px").getroot()
    assert cooling_xml.find("./bindings/binding/sourceOrd") is not None

    with zipfile.ZipFile(tmp_path / "niagara-test.bog") as archive:
        names = set(archive.namelist())
    assert "graphics/graphic_system_cooling_plant.px" in names
    assert "graphics/graphic_system_heating_plant.px" in names
