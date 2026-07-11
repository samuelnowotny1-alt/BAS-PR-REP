import asyncio
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import Request

from bas_assistant.generators import generate_reports
from bas_assistant.models import Project, ProjectMetadata, UnitSystem
from ui.api import main


def run_async(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def request(path: str = "/") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "root_path": "",
            "app": main.app,
        }
    )


def response_text(response: Any) -> str:
    if hasattr(response, "body"):
        return response.body.decode()
    return str(response)


@pytest.fixture(autouse=True)
def isolated_ui_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    main.projects.clear()


def create_project(project_id: str = "pytest-project") -> str:
    response = run_async(
        main.api_create_project(
            project_id=project_id,
            name="Pytest Project",
            client="Test Client",
            location="Test Lab",
            unit_system="IP",
            design_phase="CD",
            engineer="Test Engineer",
            programmer="Test Programmer",
            cx_agent="Test Cx",
            naming_standard="ASHRAE-135",
        )
    )

    assert response.status_code == 200
    assert f'data-redirect="/project/{project_id}"' in response_text(response)
    return project_id


def test_home_and_new_project_pages_load() -> None:
    home = run_async(main.index(request("/")))
    assert home.status_code == 200

    new_project = run_async(main.new_project_page(request("/project/new")))

    assert new_project.status_code == 200
    text = response_text(new_project)
    assert 'method="post" action="/project/new"' in text
    assert 'hx-post="/api/project/new"' in text


def test_create_project_persists_form_fields_and_detail_loads() -> None:
    project_id = create_project()

    project = main.projects[project_id]
    assert project.metadata.project_id == project_id
    assert project.metadata.name == "Pytest Project"
    assert project.metadata.client == "Test Client"
    assert project.metadata.location == "Test Lab"
    assert project.metadata.unit_system == UnitSystem.IP
    assert project.metadata.design_phase == "CD"
    assert project.metadata.engineer_of_record == "Test Engineer"
    assert project.metadata.programmer == "Test Programmer"
    assert project.metadata.commissioning_agent == "Test Cx"
    assert project.metadata.naming_standard == "ASHRAE-135"

    saved_project = main.OUTPUT_DIR / "projects" / project_id / "project.json"
    assert saved_project.exists()

    detail = run_async(main.project_detail(request(f"/project/{project_id}"), project_id))
    assert detail.status_code == 200
    assert "Pytest Project" in response_text(detail)


def test_non_htmx_create_project_returns_redirect() -> None:
    response = run_async(
        main.create_project(
            project_id="redirect-project",
            name="Redirect Project",
            client="Client",
            location="Lab",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/project/redirect-project"
    assert "redirect-project" in main.projects


def test_main_project_pages_render_for_empty_project() -> None:
    project_id = create_project()

    page_calls = [
        (main.project_detail, f"/project/{project_id}"),
        (main.import_page, f"/project/{project_id}/import"),
        (main.validate_page, f"/project/{project_id}/validate"),
        (main.gaps_page, f"/project/{project_id}/gaps"),
        (main.checkout_page, f"/project/{project_id}/checkout"),
        (main.reports_page, f"/project/{project_id}/reports"),
        (main.graphics_page, f"/project/{project_id}/graphics"),
        (main.logic_page, f"/project/{project_id}/logic"),
        (main.export_page, f"/project/{project_id}/export"),
        (main.sequence_page, f"/project/{project_id}/sequence"),
        (main.troubleshoot_page, f"/project/{project_id}/troubleshoot"),
        (main.assumptions_page, f"/project/{project_id}/assumptions"),
    ]

    for handler, path in page_calls:
        response = run_async(handler(request(path), project_id))
        assert response.status_code == 200, path
        assert response_text(response), path


def test_generation_post_handlers_render() -> None:
    project_id = create_project()

    handlers = [
        main.validate_page,
        main.gaps_page,
        main.checkout_page,
        main.reports_page,
        main.graphics_page,
        main.logic_page,
    ]

    for handler in handlers:
        response = run_async(handler(request(), project_id))
        assert response.status_code == 200, handler.__name__
        assert response_text(response), handler.__name__


def test_import_data_without_uploaded_files_redirects() -> None:
    project_id = create_project()

    response = run_async(main.import_data(project_id))

    assert response.status_code == 303
    assert response.headers["location"] == f"/project/{project_id}?imported=1"


def test_export_project_renders_partial_and_writes_vendor_output() -> None:
    project_id = create_project()

    response = run_async(
        main.export_project(
            request(f"/project/{project_id}/export"),
            project_id=project_id,
            vendors=["niagara"],
        )
    )

    assert response.status_code == 200
    text = response_text(response)
    assert "Niagara Export" in text
    assert "SUCCESS" in text
    assert (main.OUTPUT_DIR / project_id / "exports" / "niagara").exists()


def test_sequence_parse_endpoint_renders_result_partial() -> None:
    project_id = create_project()

    response = run_async(
        main.parse_sequence(
            request(f"/project/{project_id}/sequence/parse"),
            project_id=project_id,
            equipment_id="AHU-1",
            sequence_text="When occupied, start the supply fan and maintain SAT setpoint.",
        )
    )

    assert response.status_code == 200
    text = response_text(response)
    assert "Parsed Sequence" in text
    assert "AHU-1" in text


def test_sample_csv_api_generates_expected_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)

    result = run_async(main.api_create_sample_data())

    assert result["message"] == "Sample CSVs created in /examples"
    examples_dir = tmp_path / "examples"
    assert (examples_dir / "equipment_schedule.csv").exists()
    assert (examples_dir / "point_list.csv").exists()
    assert (examples_dir / "controller_schedule.csv").exists()


def test_add_assumption_redirects_with_valid_category() -> None:
    project_id = create_project()

    response = run_async(
        main.add_assumption(
            project_id=project_id,
            category="design",
            title="Design Weather",
            description="Use local design weather assumptions.",
            status="pending",
            impacts="coil sizing,fan power",
        )
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/project/{project_id}/assumptions"


def test_read_only_project_api_endpoints() -> None:
    project_id = create_project()

    summary = run_async(main.api_project_summary(project_id))
    equipment = run_async(main.api_equipment_list(project_id))
    points = run_async(main.api_points_list(project_id))
    controllers = run_async(main.api_controllers_list(project_id))

    assert summary["project_id"] == project_id
    assert summary["equipment_count"] == 0
    assert equipment == []
    assert points == []
    assert controllers == []


def test_report_generation_handles_empty_point_list(tmp_path: Path) -> None:
    project = Project(
        metadata=ProjectMetadata(
            project_id="empty-report-project",
            name="Empty Report Project",
        )
    )

    report_paths = generate_reports(project, tmp_path / "reports")

    assert "point_schedule" in report_paths
    assert report_paths["point_schedule"].exists()
