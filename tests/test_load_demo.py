from pathlib import Path

from bas_assistant.validation import ValidationEngine
from scripts import load_demo, load_full_system


def test_build_demo_seed_rows_are_rich_and_consistent() -> None:
    equipment_rows, point_rows, controller_rows = load_demo.build_demo_seed_rows()

    assert len(equipment_rows) >= 15
    assert len(point_rows) >= 200
    assert len(controller_rows) == 5
    assert {row["Equipment ID"] for row in equipment_rows} >= {
        "AHU-1",
        "VAV-101",
        "CHLR-1",
        "BLR-1",
        "CT-1",
        "RTU-1",
        "FCU-1",
        "ERU-1",
        "MAU-1",
        "EF-1",
        "HX-1",
        "UH-1",
        "RP-1",
        "DOAS-1",
    }
    assert all(row["Points"] for row in equipment_rows)
    assert all(row["Owned Points"] for row in controller_rows)


def test_load_demo_project_writes_project_and_example_csvs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    examples_dir = tmp_path / "examples"

    project = load_demo.load_demo_project(data_dir, examples_dir)

    assert project.metadata.project_id == load_demo.DEMO_PROJECT_ID
    assert project.metadata.name == load_demo.DEMO_PROJECT_NAME
    assert len(project.equipment) >= 15
    assert len(project.points) >= 200
    assert len(project.controllers) == 5
    assert any(
        address.protocol.value == "BACnet/MSTP"
        for controller in project.controllers
        for address in controller.network_addresses
    )
    equipment_types = {equipment.id: equipment.type.value for equipment in project.equipment}
    assert equipment_types["CT-1"] == "CT"
    assert equipment_types["HX-1"] == "HX"
    assert equipment_types["ERU-1"] == "ERU"
    assert equipment_types["FCU-1"] == "FCU"
    assert equipment_types["MAU-1"] == "MAU"
    assert equipment_types["EF-1"] == "EF"
    assert equipment_types["UH-1"] == "TU"
    validation_report = ValidationEngine().validate(project)
    assert validation_report.errors == []
    assert validation_report.warnings == []
    assert (data_dir / "projects" / load_demo.DEMO_PROJECT_ID / "project.json").exists()
    assert (examples_dir / "equipment_schedule.csv").exists()
    assert (examples_dir / "point_list.csv").exists()
    assert (examples_dir / "controller_schedule.csv").exists()


def test_full_system_provisioner_generates_scenarios_and_niagara_pages(tmp_path: Path) -> None:
    report = load_full_system.provision_full_system(
        project_id="full-system-test",
        project_name="Full System Test",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
    )

    assert report["equipment_count"] == 24
    assert report["point_count"] == 236
    assert report["controller_count"] == 5
    assert set(report["scenarios"]) == set(load_full_system.REQUIRED_SCENARIOS)
    assert report["graphics_count"] >= 28
    assert (
        tmp_path
        / "output"
        / "full-system-test"
        / "exports"
        / "niagara"
        / "full-system-test.bog"
    ).exists()
