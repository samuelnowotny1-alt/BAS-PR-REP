import asyncio
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi import UploadFile
from starlette.requests import Request

from bas_assistant.generators import generate_reports
from bas_assistant.exporters import BACnetExporter, NiagaraExporter
from bas_assistant.importers import CSVImporter
from bas_assistant.models import Controller, ControllerNetworkAddress, Equipment, EquipmentType, Project, ProjectMetadata, Protocol, UnitSystem
from bas_assistant.models.station_sync import StationProbeResult
from bas_assistant.models.types import ValidationCategory, ValidationSeverity
from bas_assistant.validation import ValidationReport, ValidationResult
from ui.api import main


def run_async(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def request(path: str = "/", method: str = "GET", headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [],
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
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    main.configure_runtime_paths(
        data_dir=data_dir,
        output_dir=output_dir,
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'bas_assistant_test.db'}",
    )
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

    saved_project = main.DATA_DIR / "projects" / project_id / "project.json"
    assert saved_project.exists()

    detail = run_async(main.project_detail(request(f"/project/{project_id}"), project_id))
    assert detail.status_code == 200
    assert "Pytest Project" in response_text(detail)


def test_project_detail_page_renders_engineering_status_summary() -> None:
    project_id = create_project("status-project")
    project = main.get_project(project_id)
    project.controllers.append(
        main.Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
            owned_point_names=["AHU-1 SAT"],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            building="Main",
        )
    )
    project.points.append(
        main.Point(
            name="AHU-1 SAT",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            units="degF",
        )
    )
    stored_upload = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(filename="sequence.txt", file=BytesIO(b"AHU-1 SAT shall maintain 55F.")),
            category="documents",
            document_type="text_document",
        )
    )
    main.container.knowledge.ingest_document(
        project=project,
        file_path=stored_upload.path,
        source_name=stored_upload.source_document.name,
        source_type=stored_upload.document_type,
        metadata={**stored_upload.metadata, "category": stored_upload.category},
    )
    main.save_project(project)

    response = run_async(main.project_detail(request(f"/project/{project_id}"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Engineering Status" in text
    assert "Controller Assignment Coverage" in text
    assert "Controller Addressing" in text
    assert "Knowledge Indexed" in text


def test_project_detail_page_surfaces_import_and_parser_signals() -> None:
    project_id = create_project("import-signals-project")
    task_id = main.container.tasks.create_task(
        project_id=project_id,
        task_type="equipment_import",
        payload={"filename": "equipment.csv"},
    )
    main.container.tasks.complete_task(
        task_id,
        result={
            "import_result": {
                "success": True,
                "message": "Imported 1 equipment items",
                "warnings": ["Equipment 'AHU-1': ignored invalid graphic sections mystery_box"],
                "errors": [],
                "count": 1,
            }
        },
    )

    response = run_async(main.project_detail(request(f"/project/{project_id}"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Import & Parser Signals" in text
    assert "equipment.csv" in text
    assert "ignored invalid graphic sections mystery_box" in text


def test_project_memberships_page_renders_for_admin() -> None:
    project_id = create_project()
    admin_request = request(f"/project/{project_id}/memberships")
    admin_request.scope["session"] = {
        "user": {
            "id": 1,
            "username": "admin",
            "email": "admin@example.com",
            "role": "admin",
            "assigned_project_ids": [],
        }
    }

    response = run_async(main.project_memberships_page(admin_request, project_id))

    assert response.status_code == 200
    assert "Bulk Membership Management" in response_text(response)


def test_object_detail_page_renders_artifact_provenance() -> None:
    project_id = create_project("detail-project")
    project = main.get_project(project_id)
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            provenance={"parser": "niagara_station_tree", "source_name": "station.zip"},
        )
    )
    main.save_project(project)
    stored_upload = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=main.UploadFile(filename="station.zip", file=BytesIO(b"zip-bytes")),
            category="archives",
            document_type="archive",
        )
    )
    main.persist_artifact_links(
        project=project,
        stored_upload=stored_upload,
        links=[
            main.ArtifactEntityLink(
                entity_type="equipment",
                entity_key="AHU-1",
                parser_name="niagara_station_tree",
                metadata={"source_name": "station.zip"},
            )
        ],
        parser_name="niagara_station_tree",
    )

    response = run_async(main.equipment_detail_page(request(f"/project/{project_id}/equipment/AHU-1"), project_id, "AHU-1"))

    text = response_text(response)
    assert response.status_code == 200
    assert "Engineering Review" in text
    assert "Review Score" in text
    assert "Validation Context" in text
    assert "Artifact Provenance" in text
    assert "station.zip" in text


def test_controller_detail_page_renders_network_review_context() -> None:
    project_id = create_project("controller-detail-project")
    project = main.get_project(project_id)
    project.controllers.append(
        main.Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP, Protocol.BACNET_MSTP],
            network_addresses=[
                ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10"),
                ControllerNetworkAddress(protocol=Protocol.BACNET_MSTP, address="11", network_number=2001),
            ],
            serves_equipment_ids=["AHU-1"],
            owned_point_names=["AHU-1 SAT"],
            provenance={"parser": "controller_schedule", "source_name": "controller_schedule.csv"},
        )
    )
    project.equipment.append(Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id="MPC-1"))
    main.save_project(project)

    response = run_async(main.controller_detail_page(request(f"/project/{project_id}/controllers/MPC-1"), project_id, "MPC-1"))

    text = response_text(response)
    assert response.status_code == 200
    assert "Engineering Review" in text
    assert "Validation Context" in text
    assert "BACnet/IP" in text
    assert "BACnet/MSTP 11 (net 2001)" in text
    assert "controller_schedule.csv" in text


def test_generation_pages_show_readiness_and_do_not_generate_on_get() -> None:
    project_id = create_project("generation-readiness-project")

    checkout_response = run_async(main.checkout_page(request(f"/project/{project_id}/checkout"), project_id))
    reports_response = run_async(main.reports_page(request(f"/project/{project_id}/reports"), project_id))
    logic_response = run_async(main.logic_page(request(f"/project/{project_id}/logic"), project_id))

    checkout_text = response_text(checkout_response)
    reports_text = response_text(reports_response)
    logic_text = response_text(logic_response)

    assert checkout_response.status_code == 200
    assert "Generation Readiness" in checkout_text
    assert "No Checkout Sheets Generated" in checkout_text
    assert reports_response.status_code == 200
    assert "Generation Readiness" in reports_text
    assert "No Reports Generated" in reports_text
    assert logic_response.status_code == 200
    assert "Generation Readiness" in logic_text
    assert "No Logic Diagrams Generated" in logic_text


def test_generation_post_is_blocked_when_validation_errors_exist() -> None:
    project_id = create_project("blocked-generation-project")
    project = main.get_project(project_id)
    project.equipment.append(Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id=None))
    main.save_project(project)

    response = run_async(main.checkout_page(request(f"/project/{project_id}/checkout/generate", method="POST"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Generation Readiness" in text
    assert "validation errors must be resolved before generation" in text
    assert "No Checkout Sheets Generated" in text


def test_export_page_blocks_submission_when_project_not_ready() -> None:
    project_id = create_project("blocked-export-project")
    project = main.get_project(project_id)
    project.equipment.append(Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id=None))
    main.save_project(project)

    get_response = run_async(main.export_page(request(f"/project/{project_id}/export"), project_id))
    post_response = run_async(
        main.export_project(
            request(f"/project/{project_id}/export", method="POST"),
            project_id,
            vendors=["niagara"],
        )
    )

    get_text = response_text(get_response)
    post_text = response_text(post_response)
    assert get_response.status_code == 200
    assert "Export Readiness" in get_text
    assert "validation errors must be resolved before generation" in get_text
    assert post_response.status_code == 200
    assert "Export Readiness" in post_text
    assert "validation errors must be resolved before generation" in post_text


def test_object_list_pages_render() -> None:
    project_id = create_project("asset-pages")
    project = main.get_project(project_id)
    project.equipment.append(Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id="MPC-1"))
    project.controllers.append(
        main.Controller(
            id="MPC-1",
            type="niagara",
            protocols=[Protocol.BACNET_IP, Protocol.BACNET_MSTP],
            network_addresses=[
                ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.0.0.5"),
                ControllerNetworkAddress(protocol=Protocol.BACNET_MSTP, address="11", network_number=2001),
            ],
        )
    )
    project.points.append(
        main.Point(
            name="AHU-1_SAT",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            units="degF",
        )
    )
    main.save_project(project)

    equipment_response = run_async(main.equipment_list_page(request(f"/project/{project_id}/equipment"), project_id))
    points_response = run_async(main.points_list_page(request(f"/project/{project_id}/points"), project_id))
    controllers_response = run_async(main.controllers_list_page(request(f"/project/{project_id}/controllers"), project_id))

    assert "AHU-1" in response_text(equipment_response)
    assert "AHU-1_SAT" in response_text(points_response)
    assert "MPC-1" in response_text(controllers_response)
    assert "BACnet/IP" in response_text(controllers_response)
    assert "10.0.0.5" in response_text(controllers_response)


def test_project_documents_page_and_download_render() -> None:
    project_id = create_project("docs-project")
    project = main.get_project(project_id)
    stored_upload = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(filename="sequence.txt", file=BytesIO(b"AHU shall start on occupancy.")),
            category="documents",
            document_type="text_document",
        )
    )
    main.container.knowledge.ingest_document(
        project=project,
        file_path=stored_upload.path,
        source_name=stored_upload.source_document.name,
        source_type=stored_upload.document_type,
        metadata={**stored_upload.metadata, "category": stored_upload.category},
    )
    main.save_project(project)

    page_response = run_async(main.project_documents_page(request(f"/project/{project_id}/documents"), project_id))
    detail_response = run_async(main.project_document_detail_page(request(f"/project/{project_id}/documents/{stored_upload.document_record_id}"), project_id, stored_upload.document_record_id))
    knowledge_response = run_async(main.project_knowledge_page(request(f"/project/{project_id}/knowledge"), project_id))
    download_response = run_async(main.project_document_download(project_id, stored_upload.document_record_id))

    assert "Document Library" in response_text(page_response)
    assert "Knowledge Status" in response_text(detail_response)
    assert "Knowledge Library" in response_text(knowledge_response)
    assert page_response.status_code == 200
    assert detail_response.status_code == 200
    assert knowledge_response.status_code == 200
    assert download_response.status_code == 200
    assert download_response.headers["content-disposition"].endswith('filename="sequence.txt"')


def test_project_knowledge_search_page_and_api_return_matching_chunks() -> None:
    project_id = create_project("knowledge-search-project")
    project = main.get_project(project_id)
    stored_upload = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(
                filename="sequence.txt",
                file=BytesIO(
                    b"AHU-1 shall start on occupancy, prove supply fan status, and maintain SAT setpoint at 55F."
                ),
            ),
            category="documents",
            document_type="text_document",
        )
    )
    main.container.knowledge.ingest_document(
        project=project,
        file_path=stored_upload.path,
        source_name=stored_upload.source_document.name,
        source_type=stored_upload.document_type,
        metadata={**stored_upload.metadata, "category": stored_upload.category},
    )
    main.save_project(project)

    page_response = run_async(
        main.project_knowledge_page(
            request(f"/project/{project_id}/knowledge?q=supply+fan"),
            project_id,
            q="supply fan",
        )
    )
    api_response = run_async(main.api_project_knowledge_search(project_id, q="supply fan"))

    page_text = response_text(page_response)
    assert page_response.status_code == 200
    assert "Knowledge Search" in page_text
    assert "sequence.txt" in page_text
    assert "supply fan status" in page_text
    assert f'/project/{project_id}/documents/{stored_upload.document_record_id}' in page_text
    assert api_response["result_count"] >= 1
    assert api_response["results"][0]["source_name"] == "sequence.txt"
    assert "supply fan status" in api_response["results"][0]["excerpt"]
    assert api_response["results"][0]["document_id"] == stored_upload.document_record_id
    assert api_response["results"][0]["document_detail_url"] == f"/project/{project_id}/documents/{stored_upload.document_record_id}"
    assert api_response["results"][0]["document_download_url"] == f"/project/{project_id}/documents/{stored_upload.document_record_id}/download"
    assert api_response["results"][0]["matched_terms"] == ["supply", "fan"]


def test_project_knowledge_search_ranks_exact_phrase_and_full_coverage_first() -> None:
    project_id = create_project("knowledge-ranking-project")
    project = main.get_project(project_id)
    uploads = [
        (
            "exact-sequence.txt",
            b"The supply fan status shall prove within 10 seconds and the supply fan status alarm shall reset automatically.",
        ),
        (
            "partial-sequence.txt",
            b"The supply airflow shall enable on occupancy and prove discharge temperature during operation.",
        ),
    ]
    for filename, content in uploads:
        stored_upload = run_async(
            main.container.uploads.save_project_upload(
                project=project,
                upload=UploadFile(filename=filename, file=BytesIO(content)),
                category="documents",
                document_type="text_document",
            )
        )
        main.container.knowledge.ingest_document(
            project=project,
            file_path=stored_upload.path,
            source_name=stored_upload.source_document.name,
            source_type=stored_upload.document_type,
            metadata={**stored_upload.metadata, "category": stored_upload.category},
        )
    main.save_project(project)

    api_response = run_async(main.api_project_knowledge_search(project_id, q="supply fan status"))

    assert api_response["result_count"] >= 2
    assert api_response["results"][0]["source_name"] == "exact-sequence.txt"
    assert api_response["results"][0]["exact_phrase_match"] is True
    assert api_response["results"][0]["coverage_ratio"] == 1.0
    assert api_response["results"][0]["matched_terms"] == ["supply", "fan", "status"]


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
        (main.project_activity_page, f"/project/{project_id}/activity"),
        (main.project_documents_page, f"/project/{project_id}/documents"),
        (main.project_knowledge_page, f"/project/{project_id}/knowledge"),
        (main.import_page, f"/project/{project_id}/import"),
        (main.validate_page, f"/project/{project_id}/validate"),
        (main.gaps_page, f"/project/{project_id}/gaps"),
        (main.checkout_page, f"/project/{project_id}/checkout"),
        (main.reports_page, f"/project/{project_id}/reports"),
        (main.graphics_page, f"/project/{project_id}/graphics"),
        (main.logic_page, f"/project/{project_id}/logic"),
        (main.export_page, f"/project/{project_id}/export"),
        (main.station_sync_page, f"/project/{project_id}/station-sync"),
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


def test_project_activity_page_renders_task_outcome_summaries() -> None:
    project_id = create_project("activity-project")
    task_id = main.container.tasks.create_task(
        project_id=project_id,
        task_type="equipment_import",
        payload={"filename": "equipment.csv"},
    )
    main.container.tasks.complete_task(
        task_id,
        result={
            "import_result": {
                "success": True,
                "message": "Imported 2 equipment items",
                "warnings": ["Equipment 'AHU-1': ignored invalid graphic sections mystery_box"],
                "errors": [],
                "count": 2,
            }
        },
    )

    response = run_async(main.project_activity_page(request(f"/project/{project_id}/activity"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Outcome Summary" in text
    assert "Imported 2 equipment items" in text
    assert "ignored invalid graphic sections mystery_box" in text
    assert "Warnings" in text


def test_graphics_preview_pages_prefers_equipment_pages() -> None:
    project = Project(
        metadata=ProjectMetadata(project_id="preview-test", name="Preview Test"),
        equipment=[
            Equipment(id="AHU-1", type=EquipmentType.AHU),
        ],
        points=[
            main.Point(
                name="AHU-1_SAT",
                equipment_id="AHU-1",
                kind=main.PointKind.SENSOR,
                direction=main.PointDirection.INPUT,
                units="degF",
            )
        ],
        controllers=[],
    )

    pages = main.graphics_preview_pages(project)

    assert pages
    assert all(str(page.get("slotPath", "")).startswith("/Px/Equipment/") for page in pages)


def test_graphics_page_includes_symbol_library() -> None:
    project_id = create_project()
    project = main.projects[project_id]
    project.equipment.append(Equipment(id="AHU-1", type=EquipmentType.AHU))
    project.points.append(
        main.Point(
            name="AHU-1_SAT",
            equipment_id="AHU-1",
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            units="degF",
        )
    )

    response = run_async(main.graphics_page(request(f"/project/{project_id}/graphics"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Graphics Library" in text
    assert "Library Symbol" in text
    assert "ahu" in text


def test_station_sync_save_persists_configuration() -> None:
    project_id = create_project()

    response = run_async(
        main.save_station_sync_config(
            request(f"/project/{project_id}/station-sync/save", method="POST"),
            project_id,
            enabled="on",
            protocol="oBIX/HTTP",
            host="10.1.2.3",
            port=8443,
            use_tls="on",
            verify_tls=None,
            station_name="JACE-1",
            username="station-user",
            password="secret",
            obix_path="/obix",
            timeout_seconds=12,
        )
    )

    project = main.projects[project_id]
    assert response.status_code == 200
    assert project.station_connection is not None
    assert project.station_connection.enabled is True
    assert project.station_connection.host == "10.1.2.3"
    assert project.station_connection.port == 8443
    assert project.station_connection.use_tls is True
    assert project.station_connection.verify_tls is False
    assert project.station_connection.station_name == "JACE-1"
    assert main.station_sync_passwords[project_id] == "secret"
    assert "Station sync configuration saved." in response_text(response)


def test_station_sync_probe_updates_last_probe_status(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = create_project()

    def fake_probe(self, config, password=None):
        assert config.host == "jace.local"
        assert password == "topsecret"
        return StationProbeResult(
            success=True,
            endpoint=config.obix_url(),
            status_code=200,
            message="Station endpoint responded.",
        )

    monkeypatch.setattr(main.StationSyncService, "probe", fake_probe)

    response = run_async(
        main.probe_station_sync(
            request(f"/project/{project_id}/station-sync/probe", method="POST"),
            project_id,
            enabled="on",
            protocol="oBIX/HTTP",
            host="jace.local",
            port=443,
            use_tls="on",
            verify_tls="on",
            station_name="JACE-TEST",
            username="niagara",
            password="topsecret",
            obix_path="/obix",
            timeout_seconds=10,
        )
    )

    project = main.projects[project_id]
    assert response.status_code == 200
    assert project.station_connection is not None
    assert project.station_connection.last_test_status == "success"
    assert project.station_connection.last_test_message == "Station endpoint responded."
    assert "Station endpoint responded." in response_text(response)


def test_validate_page_includes_filters_and_export_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = create_project()
    report = ValidationReport(project_id=project_id, total_rules_run=3, total_objects_checked=1)
    report.add_result(
        ValidationResult(
            object_type="equipment",
            object_id="AHU-1",
            rule_id="COMP-001",
            severity=ValidationSeverity.ERROR,
            category=ValidationCategory.COMPLETENESS,
            message="Equipment is missing controller assignment",
            field="controller_id",
            passed=False,
        )
    )
    monkeypatch.setattr(main.ValidationEngine, "validate", lambda self, project: report)

    response = run_async(main.validate_page(request(f"/project/{project_id}/validate"), project_id))

    assert response.status_code == 200
    text = response_text(response)
    assert "Findings Explorer" in text
    assert 'id="validation-group-by"' in text
    assert 'id="validation-object-filter"' in text
    assert "Fix path" in text
    assert "Recommended Fix" in text
    assert "Selected Finding" in text
    assert "Inspect" in text
    assert f'/project/{project_id}/validate/report.json' in text
    assert f'/project/{project_id}/validate/report.csv' in text
    assert "Re-run Validation" in text


def test_validation_report_export_returns_json() -> None:
    project_id = create_project()

    response = run_async(main.validation_report_export(project_id))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{project_id}-validation-report.json"'
    )


def test_validation_report_export_returns_csv() -> None:
    project_id = create_project()

    response = run_async(main.validation_report_csv_export(project_id))

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{project_id}-validation-report.csv"'
    )
    body = response.body.decode()
    assert "severity,object_type,object_id,rule_id,category,field,message" in body


def test_import_data_without_uploaded_files_redirects() -> None:
    project_id = create_project()

    response = run_async(main.import_data(request(f"/project/{project_id}/import", method="POST"), project_id))

    assert response.status_code == 303
    assert response.headers["location"] == f"/project/{project_id}?imported=1"


def test_htmx_import_returns_inline_result_summary() -> None:
    project_id = create_project("htmx-import-project")
    upload = UploadFile(filename="sequence.txt", file=BytesIO(b"AHU sequence notes"))

    response = run_async(
        main.import_data(
            request(
                f"/project/{project_id}/import",
                method="POST",
                headers=[(b"hx-request", b"true")],
            ),
            project_id,
            supporting_files=[upload],
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "Import Complete" in text
    assert "Latest Task Outcomes" in text
    assert "Knowledge status: indexed" in text


def test_import_workspace_view_returns_recent_uploads_and_task_summary() -> None:
    project_id = create_project("import-workspace-project")
    project = main.get_project(project_id)
    run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(filename="notes.txt", file=BytesIO(b"sequence notes")),
            category="documents",
            document_type="text_document",
        )
    )
    task_id = main.container.tasks.create_task(
        project_id=project_id,
        task_type="artifact_ingestion",
        payload={"filename": "notes.txt"},
    )
    main.container.tasks.complete_task(
        task_id,
        result={"knowledge_status": "indexed", "chunk_count": 1},
    )

    workspace_view = main.container.project_queries.import_workspace_view(project_id)

    assert workspace_view is not None
    assert workspace_view["project_id"] == project_id
    assert len(workspace_view["recent_uploads"]) == 1
    assert workspace_view["recent_uploads"][0]["filename"] == "notes.txt"
    assert workspace_view["import_status_view"]["tasks"][0]["task_type"] == "artifact_ingestion"
    assert workspace_view["import_status_view"]["tasks"][0]["outcome_summary"]["summary_text"] == "Knowledge status: indexed"


def test_import_page_renders_recent_ingestion_outcomes_and_parser_support() -> None:
    project_id = create_project("import-page-project")
    project = main.get_project(project_id)
    stored_upload = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(filename="notes.txt", file=BytesIO(b"sequence notes")),
            category="documents",
            document_type="text_document",
        )
    )
    task_id = main.container.tasks.create_task(
        project_id=project_id,
        task_type="artifact_ingestion",
        payload={"filename": "notes.txt"},
    )
    main.container.tasks.complete_task(
        task_id,
        result={
            "knowledge_status": "indexed",
            "chunk_count": 1,
        },
    )
    main.save_project(project)

    response = run_async(main.import_page(request(f"/project/{project_id}/import"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Latest Ingestion Outcomes" in text
    assert "Knowledge status: indexed" in text
    assert "Recent Project Uploads" in text
    assert "stored only" in text


def test_load_demo_returns_htmx_redirect_header() -> None:
    response = run_async(
        main.api_load_demo(
            request(
                "/api/load-demo",
                method="POST",
                headers=[(b"hx-request", b"true")],
            )
        )
    )

    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/project/demo-hvac-project"
    assert "demo-hvac-project" in main.projects


def test_export_project_renders_partial_and_writes_vendor_output() -> None:
    project_id = create_project()
    project = main.get_project(project_id)
    project.controllers.append(
        main.Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
            owned_point_names=["AHU-1 SAT"],
        )
    )
    project.equipment.append(Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id="MPC-1"))
    project.points.append(
        main.Point(
            name="AHU-1 SAT",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            units="degF",
        )
    )
    main.save_project(project)

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
    controller_template = (examples_dir / "controller_schedule.csv").read_text()
    assert "MS/TP MAC" in controller_template
    assert "Network Number" in controller_template
    assert "BACnet/IP,BACnet/MSTP" in controller_template


def test_add_assumption_redirects_with_valid_category() -> None:
    project_id = create_project()

    response = run_async(
        main.add_assumption(
            request=request(f"/project/{project_id}/assumptions", method="POST"),
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


def test_review_decisions_persist_reload_and_drive_report_summary() -> None:
    project_id = create_project("review-persistence-project")
    project = main.get_project(project_id)

    add_response = run_async(
        main.add_assumption(
            request=request(f"/project/{project_id}/assumptions", method="POST"),
            project_id=project_id,
            category="design",
            title="Design Weather",
            description="Use summer design conditions for sizing.",
            status="verified",
            impacts="coil sizing",
        )
    )
    assert add_response.status_code == 303

    gap_report = main.analyze_gaps(project)
    assert gap_report.gaps
    gap_id = gap_report.gaps[0].gap_id
    resolve_response = run_async(
        main.resolve_gap(
            request=request(f"/project/{project_id}/gaps/{gap_id}/resolve", method="POST"),
            project_id=project_id,
            gap_id=gap_id,
            resolution_notes="Accepted for current intake slice.",
        )
    )
    assert resolve_response.status_code == 303

    approval_response = run_async(
        main.approve_review_outputs(
            project_id=project_id,
            notes="Ready for downstream report generation.",
        )
    )
    assert approval_response.status_code == 303

    persisted = main.container.projects.get(project_id)
    assert persisted is not None
    assert len(persisted.review_state.assumptions) == 1
    assert persisted.review_state.assumptions[0].status == "verified"
    assert persisted.review_state.gap_decisions[0].gap_id == gap_id
    assert persisted.review_state.approvals[0].approval_key == "outputs-ready"

    main.projects.clear()
    main.container.projects.clear_cache()

    reloaded = main.get_project(project_id)
    assert len(reloaded.review_state.assumptions) == 1
    assert reloaded.review_state.gap_decisions[0].resolution_notes == "Accepted for current intake slice."
    assert reloaded.review_state.approvals[0].notes == "Ready for downstream report generation."

    report_paths = generate_reports(reloaded, main.OUTPUT_DIR / project_id / "reports")
    summary_text = report_paths["summary"].read_text(encoding="utf-8")
    assert "## Review Decisions" in summary_text
    assert "- Assumptions captured: **1**" in summary_text
    assert "- Gap resolutions recorded: **1**" in summary_text
    assert "- Output approval: **approved**" in summary_text
    assert "Ready for downstream report generation." in summary_text


def test_mapping_decision_persists_and_changes_generated_relationships() -> None:
    project_id = create_project("mapping-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            serves_equipment_ids=["AHU-1"],
            owned_point_names=["AHU-1 SAT"],
        )
    )
    project.add_controller(
        Controller(
            id="MPC-2",
            protocols=[Protocol.BACNET_IP],
            serves_equipment_ids=["AHU-1"],
            owned_point_names=["AHU-1 SAT"],
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SAT",
            equipment_id="AHU-1",
            controller_id=None,
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            units="degF",
        )
    )
    main.save_project(project)

    mappings_page = run_async(main.mappings_page(request(f"/project/{project_id}/mappings"), project_id))
    mappings_text = response_text(mappings_page)
    assert mappings_page.status_code == 200
    assert "Relationship Mappings" in mappings_text
    assert "equipment_controller" not in mappings_text
    assert "point controller" in mappings_text.lower()
    assert "MPC-1" in mappings_text
    assert "MPC-2" in mappings_text

    response = run_async(
        main.save_mapping_decision(
            project_id=project_id,
            mapping_key="point-controller:AHU-1 SAT",
            mapped_to="MPC-2",
            notes="Controller schedule is authoritative.",
        )
    )
    assert response.status_code == 303

    main.projects.clear()
    main.container.projects.clear_cache()
    reloaded = main.get_project(project_id)
    assert reloaded.effective_point_controller_id("AHU-1 SAT") == "MPC-2"

    report_paths = generate_reports(reloaded, main.OUTPUT_DIR / project_id / "reports")
    point_schedule = pd.read_excel(report_paths["point_schedule"], sheet_name="Point Schedule")
    controller_schedule = pd.read_excel(report_paths["controller_schedule"], sheet_name="Controller Schedule")
    assert point_schedule.loc[0, "Controller"] == "MPC-2"
    mpc2_row = controller_schedule.loc[controller_schedule["Controller ID"] == "MPC-2"].iloc[0]
    assert mpc2_row["Owned Points"] == 1


def test_review_release_page_blocks_then_allows_approval() -> None:
    project_id = create_project("review-release-project")

    page = run_async(main.review_release_page(request(f"/project/{project_id}/review"), project_id))
    assert page.status_code == 200
    assert "Needs review" in response_text(page)

    blocked = run_async(
        main.approve_release_readiness(
            project_id=project_id,
            notes="Should not pass yet.",
        )
    )
    assert blocked.status_code == 303
    assert blocked.headers["location"] == f"/project/{project_id}/review?ready=0"

    project = main.get_project(project_id)
    project.metadata.client = "Client"
    project.metadata.location = "Site"
    project.metadata.engineer_of_record = "Engineer"
    project.metadata.programmer = "Programmer"
    project.metadata.commissioning_agent = "CxA"
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.10", network_number=2001)],
        )
    )
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            point_names=["AHU-1 SAT"],
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SAT",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            units="degF",
            bacnet_object_type="AI",
            bacnet_instance=101,
        )
    )
    main.save_project(project)

    run_async(
        main.add_assumption(
            request=request(f"/project/{project_id}/assumptions", method="POST"),
            project_id=project_id,
            category="design",
            title="Basis",
            description="Accepted design basis.",
            status="accepted",
        )
    )

    allowed = run_async(
        main.approve_release_readiness(
            project_id=project_id,
            notes="Ready for generated outputs.",
        )
    )
    assert allowed.status_code == 303
    assert allowed.headers["location"] == f"/project/{project_id}/review?ready=1"
    reloaded = main.get_project(project_id)
    assert reloaded.review_state.approvals[0].approval_key == "outputs-ready"


def test_reimport_replaces_conflicting_rows_with_warning(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="REIMPORT-1", name="Reimport Project"))
    importer = CSVImporter(project)
    equipment_csv = tmp_path / "equipment_schedule.csv"
    equipment_csv.write_text(
        "Equipment ID,Equipment Type,Controller ID,Served Area\n"
        "AHU-1,AHU,MPC-1,North Wing\n"
    )
    points_csv = tmp_path / "point_list.csv"
    points_csv.write_text(
        "Point Name,Equipment ID,Point Kind,Direction,Controller ID,Units\n"
        "AHU-1 SAT,AHU-1,sensor,input,MPC-1,degF\n"
    )

    first_equipment = importer.import_equipment_schedule(equipment_csv, "equip_csv")
    first_points = importer.import_point_list(points_csv, "points_csv")
    assert first_equipment.success
    assert first_points.success

    equipment_csv.write_text(
        "Equipment ID,Equipment Type,Controller ID,Served Area\n"
        "AHU-1,AHU,MPC-2,South Wing\n"
    )
    points_csv.write_text(
        "Point Name,Equipment ID,Point Kind,Direction,Controller ID,Units\n"
        "AHU-1 SAT,AHU-1,sensor,input,MPC-2,degC\n"
    )

    second_equipment = importer.import_equipment_schedule(equipment_csv, "equip_csv_2")
    second_points = importer.import_point_list(points_csv, "points_csv_2")
    assert second_equipment.success
    assert second_points.success
    assert second_equipment.warnings
    assert second_points.warnings
    assert project.get_equipment("AHU-1").controller_id == "MPC-2"
    assert project.get_equipment("AHU-1").served_area == "South Wing"
    assert project.get_point("AHU-1 SAT").controller_id == "MPC-2"
    assert project.get_point("AHU-1 SAT").units == "degC"


def test_mapping_decision_flows_into_niagara_and_bacnet_exports(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="EXPORT-MAP", name="Export Mapping"))
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id="MPC-1"))
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.1", network_number=1001)],
        )
    )
    project.add_controller(
        Controller(
            id="MPC-2",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.2", network_number=1002)],
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SAT",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            units="degF",
        )
    )
    project.review_state.mapping_decisions.append(
        main.MappingReviewDecision(
            mapping_key="point-controller:AHU-1 SAT",
            mapped_to="MPC-2",
            status="accepted",
            notes="Override controller from field review.",
        )
    )

    niagara_result = NiagaraExporter(project).export(tmp_path / "niagara")
    bacnet_result = BACnetExporter(project).export(tmp_path / "bacnet")

    assert niagara_result.success
    assert bacnet_result.success

    niagara_points = json.loads((tmp_path / "niagara" / "EXPORT-MAP_wxf" / "points.json").read_text())
    assert niagara_points["points"][0]["ord"] == "station:|slot:/Drivers/BacnetNetwork/MPC-2/Points/AHU-1_SAT"

    bacnet_points = pd.read_csv(tmp_path / "bacnet" / "csv" / "points.csv")
    assert bacnet_points.loc[0, "Controller"] == "MPC-2"


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


def test_equipment_graphic_sections_update_route_persists_to_equipment() -> None:
    project_id = create_project()
    project = main.projects[project_id]
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))

    response = run_async(
        main.update_equipment_graphics_config(
            project_id=project_id,
            equipment_id="AHU-1",
            graphic_sections="outside_air, filter, cooling_coil, supply_fan, discharge",
        )
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/project/{project_id}"
    assert main.equipment_graphic_sections(project.get_equipment("AHU-1")) == (
        "outside_air,filter,cooling_coil,supply_fan,discharge"
    )


def test_csv_importer_reads_equipment_graphic_sections(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="CSV-1", name="CSV Project"))
    importer = CSVImporter(project)
    csv_path = tmp_path / "equipment_schedule.csv"
    csv_path.write_text(
        "Equipment ID,Equipment Type,Graphic Sections\n"
        "AHU-1,AHU,\"outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge\"\n"
    )

    result = importer.import_equipment_schedule(csv_path, "equip_csv")

    assert result.success
    equipment = project.get_equipment("AHU-1")
    assert equipment is not None
    assert main.equipment_graphic_sections(equipment) == (
        "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge"
    )


def test_csv_importer_warns_on_invalid_graphic_sections(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="CSV-2", name="CSV Project"))
    importer = CSVImporter(project)
    csv_path = tmp_path / "equipment_schedule.csv"
    csv_path.write_text(
        "Equipment ID,Equipment Type,Graphic Sections\n"
        "AHU-1,AHU,\"outside_air,mystery_box,filter\"\n"
    )

    result = importer.import_equipment_schedule(csv_path, "equip_csv")

    assert result.success
    assert result.warnings
    equipment = project.get_equipment("AHU-1")
    assert equipment is not None
    assert main.equipment_graphic_sections(equipment) == "outside_air,filter"


def test_csv_importer_reads_controller_network_addresses(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="CSV-CTRL", name="CSV Controller Project"))
    importer = CSVImporter(project)
    csv_path = tmp_path / "controller_schedule.csv"
    csv_path.write_text(
        "Controller ID,Protocols,IP Address,MS/TP MAC,Network Number,Owned Points\n"
        "MPC-1,\"BACnet/IP,BACnet/MSTP\",192.168.10.10,11,2001,\"AHU-1 SAT\"\n"
    )

    result = importer.import_controller_schedule(csv_path, "controller_csv")

    assert result.success
    controller = project.get_controller("MPC-1")
    assert controller is not None
    assert {protocol.value for protocol in controller.protocols} == {"BACnet/IP", "BACnet/MSTP"}
    assert {(address.protocol.value, address.address, address.network_number) for address in controller.network_addresses} == {
        ("BACnet/IP", "192.168.10.10", None),
        ("BACnet/MSTP", "11", 2001),
    }


def test_equipment_graphic_preset_route_applies_sections() -> None:
    project_id = create_project()
    project = main.projects[project_id]
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))

    response = run_async(
        main.apply_equipment_graphics_preset(
            project_id=project_id,
            equipment_id="AHU-1",
            preset_value="outside_air,energy_recovery,filter,cooling_coil,heating_coil,supply_fan,discharge",
        )
    )

    assert response.status_code == 303
    assert main.equipment_graphic_sections(project.get_equipment("AHU-1")) == (
        "outside_air,energy_recovery,filter,cooling_coil,heating_coil,supply_fan,discharge"
    )


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


def test_controller_schedule_report_includes_network_address_columns(tmp_path: Path) -> None:
    project = Project(
        metadata=ProjectMetadata(
            project_id="controller-report-project",
            name="Controller Report Project",
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            name="Main Plant Controller",
            type="MPC",
            protocols=[Protocol.BACNET_IP, Protocol.BACNET_MSTP],
            network_addresses=[
                ControllerNetworkAddress(
                    protocol=Protocol.BACNET_IP,
                    address="192.168.1.10",
                ),
                ControllerNetworkAddress(
                    protocol=Protocol.BACNET_MSTP,
                    address="11",
                    network_number=2001,
                ),
            ],
        )
    )

    report_paths = generate_reports(project, tmp_path / "reports")

    controller_schedule = pd.read_excel(report_paths["controller_schedule"], sheet_name="Controller Schedule")
    network_summary = pd.read_excel(report_paths["controller_schedule"], sheet_name="Network Addresses")

    assert controller_schedule.loc[0, "IP Addresses"] == "192.168.1.10"
    assert str(controller_schedule.loc[0, "MS/TP MACs"]) == "11"
    assert str(controller_schedule.loc[0, "Network Numbers"]) == "2001"
    assert set(network_summary["Protocol"]) == {"BACnet/IP", "BACnet/MSTP"}
