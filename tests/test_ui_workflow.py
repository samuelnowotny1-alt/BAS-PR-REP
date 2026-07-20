import asyncio
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from fastapi import UploadFile
from starlette.requests import Request

from bas_assistant.generators import generate_reports
from bas_assistant.exporters import BACnetExporter, HoneywellExporter, JCIExporter, NiagaraExporter, SiemensExporter, TridiumExporter
from bas_assistant.importers import CSVImporter
from bas_assistant.models import Controller, ControllerNetworkAddress, Equipment, EquipmentType, Project, ProjectMetadata, Protocol, UnitSystem
from bas_assistant.models import SourceDocument
from bas_assistant.models.station_sync import StationProbeResult
from bas_assistant.models.types import ValidationCategory, ValidationSeverity
from bas_assistant.validation import ValidationEngine, ValidationReport, ValidationResult
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


def form_request(path: str, data: dict[str, str], method: str = "POST") -> Request:
    body = urlencode(data).encode()

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(body)).encode()),
            ],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "root_path": "",
            "app": main.app,
        },
        receive,
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
    home_text = response_text(home)
    assert 'hx-post="/api/load-demo"' in home_text
    assert "Load Demo Project" in home_text

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

    ledger_response = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="project.created",
            entity_type="project",
        )
    )
    ledger_text = response_text(ledger_response)
    assert "Project created: Pytest Project" in ledger_text
    assert "Test Client" in ledger_text


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
    assert "Development Status" in text
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
    assert "Completeness" in text
    assert "Provenance Summary" in text
    assert "Validation Context" in text
    assert "Artifact Provenance" in text
    assert "station.zip" in text
    assert f"/project/{project_id}/documents/{stored_upload.document_record_id}" in text


def test_document_detail_page_renders_structured_coverage_links() -> None:
    project_id = create_project("document-coverage-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    main.save_project(project)
    stored_upload = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(filename="sequence.txt", file=BytesIO(b"AHU-1 supply fan status sequence")),
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
    main.persist_artifact_links(
        project=project,
        stored_upload=stored_upload,
        links=[
            main.ArtifactEntityLink(
                entity_type="equipment",
                entity_key="AHU-1",
                parser_name="sequence_import",
                metadata={"source_name": "sequence.txt"},
            )
        ],
        parser_name="sequence_import",
    )

    response = run_async(
        main.project_document_detail_page(
            request(f"/project/{project_id}/documents/{stored_upload.document_record_id}"),
            project_id,
            stored_upload.document_record_id,
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "Structured Coverage" in text
    assert f"/project/{project_id}/equipment/AHU-1" in text


def test_documents_page_filters_by_mode_and_linked_entity_type() -> None:
    project_id = create_project("document-filter-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    main.save_project(project)
    uploaded = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(filename="sequence.txt", file=BytesIO(b"sequence text")),
            category="documents",
            document_type="text_document",
        )
    )
    main.persist_artifact_links(
        project=project,
        stored_upload=uploaded,
        links=[main.ArtifactEntityLink(entity_type="equipment", entity_key="AHU-1", parser_name="sequence_import")],
        parser_name="sequence_import",
    )
    generated_path = Path("/tmp/generated_report.md")
    generated_path.write_text("generated")
    main.register_generated_output(
        project=project,
        file_path=generated_path,
        document_name="generated_report.md",
        document_type="generated_report",
        parser_name="report_generator",
        links=[main.ArtifactEntityLink(entity_type="equipment", entity_key="AHU-1", relationship_type="generated_output", parser_name="report_generator")],
    )

    response = run_async(
        main.project_documents_page(
            request(f"/project/{project_id}/documents?mode=generated&linked_entity_type=equipment"),
            project_id,
            mode="generated",
            linked_entity_type="equipment",
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "generated_report.md" in text
    assert "sequence.txt" not in text
    assert "Active Filters" in text


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


def test_equipment_detail_page_shows_sequence_coverage_summary(tmp_path: Path) -> None:
    project_id = create_project("equipment-sequence-detail-project")
    project = main.get_project(project_id)
    sequence_path = tmp_path / "ahu-sequence.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status. AHU-1 SAT-SP shall maintain 55F.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        main.Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
            owned_point_names=["AHU-1 SF-CMD"],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.points.append(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )
    main.save_project(project)

    response = run_async(main.equipment_detail_page(request(f"/project/{project_id}/equipment/AHU-1"), project_id, "AHU-1"))

    text = response_text(response)
    assert response.status_code == 200
    assert "Sequence Coverage" in text
    assert "AHU-1 SF-STS" in text
    assert "Open object" in text


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


def test_checkout_and_logic_pages_surface_sequence_review_context_after_generation() -> None:
    project_id = create_project("generated-sequence-context-project")
    project = main.get_project(project_id)
    sequence_path = main.OUTPUT_DIR / project_id / "sequence.txt"
    sequence_path.parent.mkdir(parents=True, exist_ok=True)
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.points.append(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )
    main.save_project(project)

    checkout_response = run_async(main.checkout_page(request(f"/project/{project_id}/checkout/generate", method="POST"), project_id))
    logic_response = run_async(main.logic_page(request(f"/project/{project_id}/logic/generate", method="POST"), project_id))

    checkout_text = response_text(checkout_response)
    logic_text = response_text(logic_response)
    assert checkout_response.status_code == 200
    assert logic_response.status_code == 200
    assert "Sequence Review: attention" in checkout_text
    assert "AHU-1 SF-STS" in checkout_text
    assert "Status/proof point" in checkout_text
    assert "Sequence Review: attention" in logic_text
    assert "AHU-1 SF-STS" in logic_text
    assert "Status/proof point" in logic_text


def test_generation_readiness_surfaces_sequence_coverage_debt() -> None:
    project_id = create_project("sequence-readiness-project")
    project = main.get_project(project_id)
    sequence_path = main.OUTPUT_DIR / project_id / "sequence.txt"
    sequence_path.parent.mkdir(parents=True, exist_ok=True)
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.points.append(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )
    main.save_project(project)

    response = run_async(main.reports_page(request(f"/project/{project_id}/reports"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Generation Readiness" in text
    assert "sequence-reviewed equipment items still have missing point coverage or control-family gaps" in text


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


def test_generated_documents_page_surfaces_stale_missing_and_unregistered_outputs() -> None:
    project_id = create_project("generated-review-project")
    project = main.get_project(project_id)

    reports_dir = main.OUTPUT_DIR / project_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_path = reports_dir / "00_Project_Summary.md"
    summary_path.write_text("summary", encoding="utf-8")

    missing_validation_path = reports_dir / "04_Validation_Report.md"
    main.register_generated_output(
        project=project,
        file_path=missing_validation_path,
        document_name=missing_validation_path.name,
        document_type="generated_validation_report",
        parser_name="report_generator",
        links=[],
        metadata={"generator": "reports", "report_key": "validation"},
    )
    project.metadata.updated_at = datetime.now() + timedelta(minutes=10)

    review = main.build_generated_output_review(project)
    page_response = run_async(
        main.project_documents_page(
            request(f"/project/{project_id}/documents?mode=generated"),
            project_id,
            mode="generated",
        )
    )
    page_text = response_text(page_response)

    assert review["status"] == "blocked"
    assert review["error_count"] == 1
    assert review["warning_count"] >= 2
    assert "Generated Output Review" in page_text
    assert "Registered generated documents are missing on disk" in page_text
    assert "Generated files exist but are not registered in the library" in page_text
    assert "Generated outputs look stale against the current project data" in page_text


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
    main.persist_artifact_links(
        project=project,
        stored_upload=stored_upload,
        links=[
            main.ArtifactEntityLink(
                entity_type="equipment",
                entity_key="AHU-1",
                parser_name="sequence_import",
                metadata={"source_name": "sequence.txt"},
            )
        ],
        parser_name="sequence_import",
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
    assert api_response["query_terms"] == ["supply", "fan"]
    assert api_response["source_hits"][0]["source_name"] == "sequence.txt"
    assert api_response["results"][0]["linked_objects"][0]["entity_key"] == "AHU-1"
    assert api_response["source_hits"][0]["linked_objects"][0]["object_url"] == f"/project/{project_id}/equipment/AHU-1"


def test_project_knowledge_page_filters_by_source_type_and_linked_entity() -> None:
    project_id = create_project("knowledge-filter-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    main.save_project(project)
    text_upload = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(filename="sequence.txt", file=BytesIO(b"AHU-1 supply fan status sequence")),
            category="documents",
            document_type="text_document",
        )
    )
    main.container.knowledge.ingest_document(
        project=project,
        file_path=text_upload.path,
        source_name=text_upload.source_document.name,
        source_type=text_upload.document_type,
        metadata={**text_upload.metadata, "category": text_upload.category},
    )
    main.persist_artifact_links(
        project=project,
        stored_upload=text_upload,
        links=[main.ArtifactEntityLink(entity_type="equipment", entity_key="AHU-1", parser_name="sequence_import")],
        parser_name="sequence_import",
    )
    archive_upload = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(filename="station.zip", file=BytesIO(b"zip-bytes")),
            category="archives",
            document_type="archive",
        )
    )
    main.container.knowledge.ingest_document(
        project=project,
        file_path=archive_upload.path,
        source_name=archive_upload.source_document.name,
        source_type=archive_upload.document_type,
        metadata={**archive_upload.metadata, "category": archive_upload.category},
    )
    main.save_project(project)

    response = run_async(
        main.project_knowledge_page(
            request(f"/project/{project_id}/knowledge?q=sequence&source_type=text_document&linked_entity_type=equipment"),
            project_id,
            q="sequence",
            source_type="text_document",
            linked_entity_type="equipment",
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "sequence.txt" in text
    assert "station.zip" not in text
    assert "All source types" in text


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


def test_validation_findings_include_object_links_and_sequence_fix_groups() -> None:
    project = Project(metadata=ProjectMetadata(project_id="validation-meta", name="Validation Meta"))
    report = ValidationReport(project_id="validation-meta")
    report.results.append(
        ValidationResult(
            object_type="equipment",
            object_id="AHU-1",
            rule_id="COMP-007",
            severity=ValidationSeverity.WARNING,
            category=ValidationCategory.COMPLETENESS,
            field="point_names",
            message="Missing sequence point coverage",
            passed=False,
        )
    )

    findings = main.serialize_validation_findings(report, "validation-meta")

    assert findings[0]["fix_group"] == "sequence_coverage"
    assert findings[0]["sequence_related"] == "true"
    assert findings[0]["object_url"] == "/project/validation-meta/equipment/AHU-1"


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


def test_equipment_list_page_filters_attention_and_missing_controller() -> None:
    project_id = create_project("equipment-filter-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    project.add_equipment(Equipment(id="AHU-2", type=EquipmentType.AHU, controller_id="MPC-1", provenance={"source_name": "equip.csv"}))
    main.save_project(project)

    response = run_async(
        main.equipment_list_page(
            request(f"/project/{project_id}/equipment?controller_state=missing"),
            project_id,
            controller_state="missing",
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "AHU-1" in text
    assert "AHU-2" not in text
    assert "Apply Filters" in text


def test_controller_list_page_filters_missing_addressing() -> None:
    project_id = create_project("controller-filter-project")
    project = main.get_project(project_id)
    project.add_controller(Controller(id="MPC-1", protocols=[Protocol.BACNET_IP]))
    project.add_controller(
        Controller(
            id="MPC-2",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.0.0.5")],
            provenance={"source_name": "ctrl.csv"},
        )
    )
    main.save_project(project)

    response = run_async(
        main.controllers_list_page(
            request(f"/project/{project_id}/controllers?addressing_state=missing"),
            project_id,
            addressing_state="missing",
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "MPC-1" in text
    assert "MPC-2" not in text


def test_project_detail_renders_object_health_shortcuts() -> None:
    project_id = create_project("detail-health-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    project.add_point(main.Point(name="AHU-1 SAT", equipment_id="AHU-1", kind=main.PointKind.SENSOR, direction=main.PointDirection.INPUT))
    project.add_controller(Controller(id="MPC-1", protocols=[Protocol.BACNET_IP]))
    main.save_project(project)

    response = run_async(main.project_detail(request(f"/project/{project_id}"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Equipment Review" in text
    assert f"/project/{project_id}/equipment?controller_state=missing" in text
    assert f"/project/{project_id}/controllers?addressing_state=missing" in text


def test_equipment_list_page_filters_by_validation_fix_group() -> None:
    project_id = create_project("validation-filter-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHUONE", type=EquipmentType.AHU, controller_id="MPC-1"))
    project.add_equipment(Equipment(id="AHU-2", type=EquipmentType.AHU, controller_id="MPC-1"))
    main.save_project(project)

    response = run_async(
        main.equipment_list_page(
            request(f"/project/{project_id}/equipment?fix_group=naming"),
            project_id,
            fix_group="naming",
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "AHUONE" in text
    assert "AHU-2" not in text
    assert "All fix groups" in text


def test_bulk_remediation_fills_missing_equipment_provenance() -> None:
    project_id = create_project("bulk-remediation-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id="MPC-1"))
    project.add_equipment(Equipment(id="AHU-2", type=EquipmentType.AHU, controller_id="MPC-1", provenance={"source_name": "equip.csv"}))
    main.save_project(project)

    response = run_async(
        main.bulk_remediate_object_list(
            project_id=project_id,
            entity_plural="equipment",
            action="fill_missing_provenance",
            status="",
            controller_state="",
            addressing_state="",
            provenance_state="missing",
            equipment_type="",
            point_kind="",
            protocol="",
            validation_category="",
            fix_group="",
        )
    )

    updated_project = main.get_project(project_id)
    assert response.status_code == 303
    assert "remediation_count=1" in response.headers["location"]
    assert updated_project.get_equipment("AHU-1").provenance["source_name"] == "bulk_remediation"
    assert updated_project.get_equipment("AHU-2").provenance["source_name"] == "equip.csv"

    activity_response = run_async(main.project_activity_page(request(f"/project/{project_id}/activity"), project_id))
    activity_text = response_text(activity_response)
    assert "Change Ledger" in activity_text
    assert "Fill Missing Provenance updated 1 equipment" in activity_text


def test_bulk_remediation_preview_shows_proposed_equipment_changes() -> None:
    project_id = create_project("bulk-preview-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id="MPC-1"))
    main.save_project(project)

    response = run_async(
        main.preview_bulk_remediate_object_list(
            request(f"/project/{project_id}/equipment/bulk-remediate/preview", method="POST"),
            project_id=project_id,
            entity_plural="equipment",
            action="fill_missing_provenance",
            status="",
            controller_state="",
            addressing_state="",
            provenance_state="missing",
            equipment_type="",
            point_kind="",
            protocol="",
            validation_category="",
            fix_group="",
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "Preview Changes" in text
    assert "provenance.source_name" in text
    assert "AHU-1" in text


def test_project_detail_renders_validation_triage_shortcuts() -> None:
    project_id = create_project("validation-triage-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHUONE", type=EquipmentType.AHU, controller_id="MPC-1"))
    main.save_project(project)

    response = run_async(main.project_detail(request(f"/project/{project_id}"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Validation Triage" in text
    assert f"/project/{project_id}/equipment?fix_group=naming" in text


def test_sequence_page_and_parse_show_structured_coverage_review(tmp_path: Path) -> None:
    project_id = create_project("sequence-page-project")
    project = main.get_project(project_id)
    sequence_path = tmp_path / "ahu-sequence.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        main.Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.points.append(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )
    main.save_project(project)

    page_response = run_async(main.sequence_page(request(f"/project/{project_id}/sequence"), project_id))
    parse_response = run_async(
        main.parse_sequence(
            request(f"/project/{project_id}/sequence/parse", method="POST"),
            project_id,
            equipment_id="AHU-1",
            sequence_text="AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        )
    )

    page_text = response_text(page_response)
    parse_text = response_text(parse_response)
    assert page_response.status_code == 200
    assert "Sequence Coverage Board" in page_text
    assert "Tracked Equipment" in page_text
    assert "Control Intent Checks" in page_text
    assert "Missing Intent Families" in page_text
    assert "AHU-1 SF-STS" in page_text
    assert parse_response.status_code == 200
    assert "Structured Coverage Review" in parse_text
    assert "Missing References" in parse_text


def test_sequence_workspace_summarizes_equipment_attention_counts(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="sequence-workspace", name="Sequence Workspace"))
    sequence_path = tmp_path / "seq.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.points.append(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )

    workspace = main.build_sequence_workspace(project)

    assert workspace["summary"]["equipment_count"] == 1
    assert workspace["summary"]["attention"] == 1
    assert workspace["summary"]["missing_refs"] >= 1
    assert workspace["summary"]["missing_checks"] >= 1
    assert "AHU-1 SF-STS" in workspace["reviews"][0]["missing_refs"]
    assert workspace["reviews"][0]["equipment_url"] == "/project/sequence-workspace/equipment/AHU-1"


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
    assert "Change Ledger" in text
    assert "equipment_import completed" in text


def test_system_ledger_page_renders_project_and_remediation_history() -> None:
    project_id = create_project("ledger-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    main.save_project(project)

    run_async(
        main.bulk_remediate_object_list(
            project_id=project_id,
            entity_plural="equipment",
            action="fill_missing_provenance",
            status="",
            controller_state="",
            addressing_state="",
            provenance_state="missing",
            equipment_type="",
            point_kind="",
            protocol="",
            validation_category="",
            fix_group="",
        )
    )

    response = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="bulk_remediation.applied",
            entity_type="equipment",
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "System Ledger" in text
    assert "Fill Missing Provenance updated 1 equipment" in text
    assert "AHU-1" in text


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


def test_graphics_library_page_includes_symbol_library() -> None:
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

    response = run_async(main.graphics_library_page(request(f"/project/{project_id}/graphics/library"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Known Unit Graphics" in text
    assert "Isometric Asset Library" in text
    assert "Legacy Flat Symbol Reference" in text
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

    ledger_response = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="station_sync.config_saved",
            entity_type="station_sync",
        )
    )
    ledger_text = response_text(ledger_response)
    assert "Station sync configuration saved" in ledger_text
    assert "JACE-1" in ledger_text


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


def test_build_ingestion_result_envelope_normalizes_parser_summary() -> None:
    envelope = main.build_ingestion_result_envelope(
        task_type="artifact_ingestion",
        source_name="station.zip",
        parser_name="niagara_station_tree",
        knowledge_result=SimpleNamespace(status="indexed", chunk_count=4),
        parser_result={"equipment_added": 2, "points_added": 5, "controllers_added": 1, "warnings": ["warn"]},
        artifact_diff={"added": ["equipment:AHU-1"], "removed": [], "unchanged": ["point:AHU-1 SF-STS"]},
    )

    assert envelope["knowledge_status"] == "indexed"
    assert envelope["chunk_count"] == 4
    assert envelope["parser_summary"]["parser_name"] == "niagara_station_tree"
    assert envelope["parser_summary"]["object_counts"] == {"equipment": 2, "points": 5, "controllers": 1}
    assert envelope["parser_summary"]["added_count"] == 1
    assert envelope["parser_summary"]["warning_count"] == 1


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
    assert "Equipment Editor" in text
    assert "Point Editor" in text
    assert "Controller Editor" in text
    assert 'data-inline-save-row' in text
    assert 'data-inline-input' in text


def test_import_editor_can_add_and_delete_equipment_rows() -> None:
    project_id = create_project("inline-equipment-project")

    save_response = run_async(
        main.save_import_editor_row(
            form_request(
                f"/project/{project_id}/import/editor/equipment/save",
                {
                    "original_key": "",
                    "id": "AHU-1",
                    "type": "AHU",
                    "subtype": "Main",
                    "building": "Tower",
                    "floor": "3",
                    "controller_id": "MPC-1",
                    "status": "design",
                    "notes": "Inline row",
                },
            ),
            project_id,
            "equipment",
        )
    )

    save_text = response_text(save_response)
    project = main.get_project(project_id)
    equipment = project.get_equipment("AHU-1")
    assert save_response.status_code == 200
    assert "Row saved and project validation refreshed." in save_text
    assert equipment is not None
    assert equipment.building == "Tower"
    assert equipment.notes == "Inline row"

    delete_response = run_async(
        main.delete_import_editor_row(
            request(f"/project/{project_id}/import/editor/equipment/AHU-1/delete", method="POST"),
            project_id,
            "equipment",
            "AHU-1",
        )
    )

    assert delete_response.status_code == 200
    assert "Row deleted and project validation refreshed." in response_text(delete_response)
    assert main.get_project(project_id).get_equipment("AHU-1") is None


def test_import_editor_can_save_points_and_controllers() -> None:
    project_id = create_project("inline-point-controller-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    main.save_project(project)

    controller_response = run_async(
        main.save_import_editor_row(
            form_request(
                f"/project/{project_id}/import/editor/controllers/save",
                {
                    "original_key": "",
                    "id": "MPC-1",
                    "type": "MPC",
                    "vendor": "Alerton",
                    "model": "Unitary",
                    "protocols": "BACnet/IP",
                    "address": "192.168.10.10",
                    "serves_equipment_ids": "AHU-1",
                    "owned_point_names": "AHU-1 SAT",
                },
            ),
            project_id,
            "controllers",
        )
    )
    point_response = run_async(
        main.save_import_editor_row(
            form_request(
                f"/project/{project_id}/import/editor/points/save",
                {
                    "original_key": "",
                    "name": "AHU-1 SAT",
                    "equipment_id": "AHU-1",
                    "controller_id": "MPC-1",
                    "kind": "sensor",
                    "direction": "input",
                    "units": "degF",
                    "bacnet_object_type": "AI",
                    "description": "Supply air temp",
                },
            ),
            project_id,
            "points",
        )
    )

    saved_project = main.get_project(project_id)
    controller = saved_project.get_controller("MPC-1")
    point = saved_project.get_point("AHU-1 SAT")
    assert controller_response.status_code == 200
    assert point_response.status_code == 200
    assert controller is not None
    assert point is not None
    assert controller.network_addresses[0].address == "192.168.10.10"
    assert controller.protocols[0] == Protocol.BACNET_IP
    assert point.bacnet_object_type == "AI"
    assert point.description == "Supply air temp"


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
    assert (main.OUTPUT_DIR / "demo-hvac-project" / "checkout").exists()
    assert (main.OUTPUT_DIR / "demo-hvac-project" / "reports").exists()
    assert (main.OUTPUT_DIR / "demo-hvac-project" / "graphics").exists()
    assert (main.OUTPUT_DIR / "demo-hvac-project" / "logic").exists()
    assert (main.OUTPUT_DIR / "demo-hvac-project" / "exports").exists()
    demo_project = main.get_project("demo-hvac-project")
    submittal_paths = [Path(document.path) for document in demo_project.source_documents if document.type == "submittal"]
    assert submittal_paths
    assert all(path.is_relative_to(main.DATA_DIR / "projects" / "demo-hvac-project" / "source_documents") for path in submittal_paths)

    documents_response = run_async(
        main.project_documents_page(
            request("/project/demo-hvac-project/documents?mode=generated"),
            "demo-hvac-project",
            mode="generated",
        )
    )
    documents_text = response_text(documents_response)
    assert documents_response.status_code == 200
    assert "00_Project_Summary.md" in documents_text
    assert "graphics_niagara.json" in documents_text
    assert "checkout_sheets.xlsx" in documents_text

    ledger_response = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id="demo-hvac-project",
            event_type="project.demo_loaded",
            entity_type="project",
        )
    )
    ledger_text = response_text(ledger_response)
    assert "Demo project loaded with generated outputs" in ledger_text
    assert "demo-hvac-project" in ledger_text


def test_demo_generated_pages_use_output_mount_links() -> None:
    run_async(
        main.api_load_demo(
            request(
                "/api/load-demo",
                method="POST",
                headers=[(b"hx-request", b"true")],
            )
        )
    )

    documents_response = run_async(
        main.project_documents_page(
            request("/project/demo-hvac-project/documents?mode=generated"),
            "demo-hvac-project",
            mode="generated",
        )
    )
    graphics_response = run_async(
        main.graphics_page(
            request("/project/demo-hvac-project/graphics"),
            "demo-hvac-project",
        )
    )

    documents_text = response_text(documents_response)
    graphics_text = response_text(graphics_response)

    assert documents_response.status_code == 200
    assert graphics_response.status_code == 200
    assert "/output/demo-hvac-project/" in graphics_text
    assert "/static/output/" not in documents_text
    assert "/static/output/" not in graphics_text


def test_duplicate_project_route_copies_data_outputs_and_generated_documents() -> None:
    run_async(
        main.api_load_demo(
            request(
                "/api/load-demo",
                method="POST",
                headers=[(b"hx-request", b"true")],
            )
        )
    )

    response = run_async(
        main.duplicate_project_route(
            request("/project/demo-hvac-project/duplicate", method="POST"),
            "demo-hvac-project",
            name="Demo HVAC Project - Copy",
            new_project_id="demo-hvac-project-copy",
        )
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/project/demo-hvac-project-copy"

    duplicate = main.get_project("demo-hvac-project-copy")
    assert duplicate.metadata.name == "Demo HVAC Project - Copy"
    assert len(duplicate.equipment) > 0
    assert len(duplicate.points) > 0
    assert len(duplicate.controllers) > 0
    assert (main.OUTPUT_DIR / "demo-hvac-project-copy" / "reports" / "00_Project_Summary.md").exists()

    documents_response = run_async(
        main.project_documents_page(
            request("/project/demo-hvac-project-copy/documents?mode=generated"),
            "demo-hvac-project-copy",
            mode="generated",
        )
    )
    documents_text = response_text(documents_response)
    assert documents_response.status_code == 200
    assert "00_Project_Summary.md" in documents_text
    assert "graphics_niagara.json" in documents_text

    detail_response = run_async(main.project_detail(request("/project/demo-hvac-project-copy"), "demo-hvac-project-copy"))
    detail_text = response_text(detail_response)
    assert "Duplicate" in detail_text

    home_response = run_async(main.index(request("/")))
    home_text = response_text(home_response)
    assert "Duplicate Project" in home_text


def test_duplicate_project_route_assigns_unique_ids_for_repeat_copies() -> None:
    project_id = create_project("duplicate-repeat-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    main.save_project(project)

    first = run_async(
        main.duplicate_project_route(
            request(f"/project/{project_id}/duplicate", method="POST"),
            project_id,
            name="Repeat Copy",
            new_project_id=f"{project_id}-copy",
        )
    )
    second = run_async(
        main.duplicate_project_route(
            request(f"/project/{project_id}/duplicate", method="POST"),
            project_id,
            name="Repeat Copy",
            new_project_id=f"{project_id}-copy",
        )
    )

    assert first.status_code == 303
    assert first.headers["location"] == f"/project/{project_id}-copy"
    assert second.status_code == 303
    assert second.headers["location"] == f"/project/{project_id}-copy-2"
    assert main.get_project(f"{project_id}-copy").metadata.name == "Repeat Copy"
    assert main.get_project(f"{project_id}-copy-2").metadata.name == "Repeat Copy"


def test_duplicate_project_route_skips_uploaded_documents_and_knowledge() -> None:
    project_id = create_project("duplicate-clean-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    main.save_project(project)

    stored_upload = run_async(
        main.container.uploads.save_project_upload(
            project=project,
            upload=UploadFile(filename="sequence.txt", file=BytesIO(b"AHU-1 shall start on occupancy.")),
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
    generated_path = main.OUTPUT_DIR / project_id / "reports" / "00_Project_Summary.md"
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generated_path.write_text("summary", encoding="utf-8")
    main.register_generated_output(
        project=project,
        file_path=generated_path,
        document_name=generated_path.name,
        document_type="generated_project_summary",
        parser_name="report_generator",
        links=[main.ArtifactEntityLink(entity_type="equipment", entity_key="AHU-1", relationship_type="generated_output", parser_name="report_generator")],
    )
    main.save_project(project)

    response = run_async(
        main.duplicate_project_route(
            request(f"/project/{project_id}/duplicate", method="POST"),
            project_id,
            name="Duplicate Clean Copy",
            new_project_id=f"{project_id}-copy",
        )
    )

    assert response.status_code == 303
    duplicate_id = f"{project_id}-copy"
    duplicate = main.get_project(duplicate_id)
    assert duplicate.source_documents == []

    documents_response = run_async(main.project_documents_page(request(f"/project/{duplicate_id}/documents"), duplicate_id))
    knowledge_response = run_async(main.project_knowledge_page(request(f"/project/{duplicate_id}/knowledge"), duplicate_id))
    documents_text = response_text(documents_response)
    knowledge_text = response_text(knowledge_response)

    assert "00_Project_Summary.md" in documents_text
    assert "sequence.txt" not in documents_text
    assert "No knowledge records indexed yet." in knowledge_text


def test_duplicate_project_route_handles_projects_with_partial_outputs() -> None:
    project_id = create_project("partial-output-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    main.save_project(project)

    report_path = main.OUTPUT_DIR / project_id / "reports" / "00_Project_Summary.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("summary", encoding="utf-8")
    main.register_generated_output(
        project=project,
        file_path=report_path,
        document_name=report_path.name,
        document_type="generated_project_summary",
        parser_name="report_generator",
        links=[main.ArtifactEntityLink(entity_type="equipment", entity_key="AHU-1", relationship_type="generated_output", parser_name="report_generator")],
    )

    response = run_async(
        main.duplicate_project_route(
            request(f"/project/{project_id}/duplicate", method="POST"),
            project_id,
            name="Partial Output Copy",
            new_project_id=f"{project_id}-copy",
        )
    )

    assert response.status_code == 303
    duplicate_id = f"{project_id}-copy"
    assert (main.OUTPUT_DIR / duplicate_id / "reports" / "00_Project_Summary.md").exists()
    documents_response = run_async(
        main.project_documents_page(
            request(f"/project/{duplicate_id}/documents?mode=generated"),
            duplicate_id,
            mode="generated",
        )
    )
    assert documents_response.status_code == 200
    assert "00_Project_Summary.md" in response_text(documents_response)


def test_admin_user_and_membership_changes_write_ledger_entries() -> None:
    project_id = create_project("admin-ledger-project")
    admin_request = request("/admin/users", method="POST")
    admin_request.scope["session"] = {
        "user": {
            "id": 1,
            "username": "admin",
            "email": "admin@example.com",
            "role": "admin",
            "assigned_project_ids": [],
        }
    }

    create_response = run_async(
        main.admin_create_user(
            admin_request,
            username="fieldtech",
            email="fieldtech@example.com",
            password="secret123",
            role="technician",
            project_ids=[project_id],
            access_level="viewer",
        )
    )
    assert create_response.status_code == 303

    created_user = next(user for user in main.container.auth.list_users() if user.username == "fieldtech")
    update_response = run_async(
        main.admin_update_user(
            admin_request,
            user_id=created_user.id,
            role="engineer",
            is_active="true",
            project_ids=[project_id],
            access_level="editor",
        )
    )
    assert update_response.status_code == 303

    membership_request = form_request(
        f"/project/{project_id}/memberships",
        {f"user_access_{created_user.id}": "owner"},
    )
    membership_request.scope["session"] = admin_request.scope["session"]
    membership_response = run_async(main.project_memberships_update(membership_request, project_id))
    assert membership_response.status_code == 303

    create_ledger = response_text(
        run_async(
            main.system_ledger_page(
                request("/activity/ledger"),
                event_type="admin.user_created",
                entity_type="user",
            )
        )
    )
    update_ledger = response_text(
        run_async(
            main.system_ledger_page(
                request("/activity/ledger"),
                event_type="admin.user_updated",
                entity_type="user",
            )
        )
    )
    membership_ledger = response_text(
        run_async(
            main.system_ledger_page(
                request("/activity/ledger"),
                project_id=project_id,
                event_type="admin.project_memberships_updated",
                entity_type="membership",
            )
        )
    )

    assert "User created: fieldtech" in create_ledger
    assert "fieldtech@example.com" in create_ledger
    assert "User updated: fieldtech" in update_ledger
    assert "engineer" in update_ledger
    assert "Project memberships updated for admin-ledger-project" in membership_ledger
    assert "owner" in membership_ledger


def test_tabular_reimport_writes_ledger_replacement_entry() -> None:
    project_id = create_project("reimport-ledger-project")
    first_upload = UploadFile(
        filename="equipment.csv",
        file=BytesIO(b"Equipment ID,Equipment Type,Served Area\nAHU-1,AHU,North Wing\n"),
    )
    second_upload = UploadFile(
        filename="equipment.csv",
        file=BytesIO(b"Equipment ID,Equipment Type,Served Area\nAHU-1,AHU,South Wing\n"),
    )

    first_response = run_async(
        main.import_data(
            request(f"/project/{project_id}/import", method="POST"),
            project_id,
            equipment_file=first_upload,
        )
    )
    second_response = run_async(
        main.import_data(
            request(f"/project/{project_id}/import", method="POST"),
            project_id,
            equipment_file=second_upload,
        )
    )

    assert first_response.status_code == 303
    assert second_response.status_code == 303
    assert main.get_project(project_id).get_equipment("AHU-1").served_area == "South Wing"

    ledger_response = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="import.tabular_applied",
            entity_type="equipment",
        )
    )
    ledger_text = response_text(ledger_response)
    assert "equipment.csv updated project equipment" in ledger_text
    assert "Re-import detected" in ledger_text
    assert "1 replacements" in ledger_text


def test_gap_auto_fix_writes_ledger_entry() -> None:
    project_id = create_project("gap-fix-ledger-project")
    project = main.get_project(project_id)
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.10")],
        )
    )
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id=None))
    main.save_project(project)

    gap_report = main.analyze_gaps(project)
    controller_gap = next(gap for gap in gap_report.gaps if gap.affected_object_type == "equipment" and gap.affected_object_id == "AHU-1" and gap.title.endswith("has no controller"))

    response = run_async(main.fix_gap(controller_gap.gap_id))

    assert response.status_code == 200
    assert main.get_project(project_id).get_equipment("AHU-1").controller_id == "MPC-1"

    ledger_response = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="gap.auto_fixed",
            entity_type="gap",
        )
    )
    ledger_text = response_text(ledger_response)
    assert f"Auto-fix applied for gap {controller_gap.gap_id}" in ledger_text
    assert 'controller_id: "" → "MPC-1"' in ledger_text


def test_system_ledger_page_renders_summary_cards_and_exports() -> None:
    project_id = create_project("ledger-export-project")
    project = main.get_project(project_id)
    project.add_equipment(Equipment(id="AHU-1", type=EquipmentType.AHU))
    main.save_project(project)

    run_async(
        main.bulk_remediate_object_list(
            project_id=project_id,
            entity_plural="equipment",
            action="fill_missing_provenance",
            status="",
            controller_state="",
            addressing_state="",
            provenance_state="missing",
            equipment_type="",
            point_kind="",
            protocol="",
            validation_category="",
            fix_group="",
        )
    )

    page_response = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
        )
    )
    json_response = run_async(main.system_ledger_export_json(project_id=project_id))
    csv_response = run_async(main.system_ledger_export_csv(project_id=project_id))

    page_text = response_text(page_response)
    assert page_response.status_code == 200
    assert "Event Families" in page_text
    assert "bulk_remediation" in page_text
    assert "Export JSON" in page_text
    assert "Export CSV" in page_text

    assert json_response.status_code == 200
    assert json_response.headers["content-disposition"] == 'attachment; filename="system-ledger.json"'
    json_payload = json.loads(json_response.body.decode())
    assert json_payload["row_count"] >= 1
    assert json_payload["rows"][0]["event_family"] == "bulk_remediation"

    assert csv_response.status_code == 200
    assert csv_response.headers["content-disposition"] == 'attachment; filename="system-ledger.csv"'
    csv_text = csv_response.body.decode()
    assert "event_family" in csv_text
    assert "bulk_remediation.applied" in csv_text


def test_system_ledger_supports_pagination_and_date_filters() -> None:
    project_id = create_project("ledger-paging-project")
    for index in range(45):
        main.container.ledger.record_event(
            event_type="test.synthetic",
            summary=f"Synthetic event {index}",
            project_id=project_id,
            entity_type="test",
            entity_key=str(index),
            payload={"index": index},
        )

    first_page = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="test.synthetic",
            entity_type="test",
            page=1,
        )
    )
    second_page = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="test.synthetic",
            entity_type="test",
            page=2,
        )
    )
    filtered_page = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="test.synthetic",
            entity_type="test",
            date_from="9999-01-01",
        )
    )
    filtered_export = run_async(
        main.system_ledger_export_json(
            project_id=project_id,
            event_type="test.synthetic",
            entity_type="test",
            date_from="9999-01-01",
        )
    )

    first_text = response_text(first_page)
    second_text = response_text(second_page)
    filtered_text = response_text(filtered_page)
    filtered_payload = json.loads(filtered_export.body.decode())

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert "Showing page 1 of 2" in first_text
    assert "Synthetic event 44" in first_text
    assert "Synthetic event 0" not in first_text
    assert "Showing page 2 of 2" in second_text
    assert "Synthetic event 0" in second_text
    assert "No ledger entries match the selected filters." in filtered_text
    assert filtered_payload["row_count"] == 0
    assert filtered_payload["filters"]["date_from"] == "9999-01-01"


def test_system_ledger_supports_severity_filters_and_saved_views() -> None:
    project_id = create_project("ledger-severity-project")
    main.container.ledger.record_event(
        event_type="task.failed",
        summary="Synthetic failure",
        project_id=project_id,
        entity_type="task",
        entity_key="1",
        payload={"error_count": 1},
    )
    main.container.ledger.record_event(
        event_type="admin.user_created",
        summary="Synthetic admin update",
        project_id=None,
        entity_type="user",
        entity_key="ops-user",
        payload={"username": "ops-user"},
    )

    critical_page = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            severity="critical",
        )
    )
    admin_saved_view = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            saved_view="admin",
        )
    )
    export_json = run_async(
        main.system_ledger_export_json(
            project_id=project_id,
            severity="critical",
        )
    )

    critical_text = response_text(critical_page)
    admin_text = response_text(admin_saved_view)
    export_payload = json.loads(export_json.body.decode())

    assert critical_page.status_code == 200
    assert "Severity" in critical_text
    assert "Synthetic failure" in critical_text
    assert "critical" in critical_text
    assert "Synthetic admin update" not in critical_text

    assert admin_saved_view.status_code == 200
    assert "Admin Changes" in admin_text
    assert "Synthetic admin update" in admin_text
    assert "warning" in admin_text

    assert export_payload["row_count"] >= 1
    assert export_payload["filters"]["severity"] == "critical"
    assert export_payload["rows"][0]["severity"] == "critical"


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
    assert f'/output/{project_id}/exports/niagara/' in text
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

    ledger_response = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="assumption.added",
            entity_type="assumption",
        )
    )
    ledger_text = response_text(ledger_response)
    assert "Assumption added: Design Weather" in ledger_text
    assert "Use local design weather assumptions." in ledger_text


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

    ledger_response = run_async(
        main.system_ledger_page(
            request("/activity/ledger"),
            project_id=project_id,
            event_type="review.output_approved",
            entity_type="approval",
        )
    )
    ledger_text = response_text(ledger_response)
    assert "Review outputs approved" in ledger_text
    assert "Ready for downstream report generation." in ledger_text


def test_gap_analysis_adds_sequence_generation_gaps() -> None:
    project_id = create_project("gap-sequence-project")
    project = main.get_project(project_id)
    sequence_path = main.OUTPUT_DIR / project_id / "sequence.txt"
    sequence_path.parent.mkdir(parents=True, exist_ok=True)
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
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
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )

    gap_report = main.analyze_gaps(project)
    sequence_gap_titles = {gap.title for gap in gap_report.gaps if "sequence-backed coverage" in gap.title}
    sequence_gap_descriptions = [gap.description for gap in gap_report.gaps if gap.metadata.get("generator") == "graphics"]

    assert "Graphics for AHU-1 is missing sequence-backed coverage" in sequence_gap_titles
    assert "Logic for AHU-1 is missing sequence-backed coverage" in sequence_gap_titles
    assert "Export for AHU-1 is missing sequence-backed coverage" in sequence_gap_titles
    assert any("AHU-1 SF-STS" in description for description in sequence_gap_descriptions)
    assert any("Status/proof point" in description for description in sequence_gap_descriptions)


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


def test_review_release_requires_sequence_coverage_resolution() -> None:
    project_id = create_project("review-sequence-project")
    project = main.get_project(project_id)
    sequence_path = main.OUTPUT_DIR / project_id / "sequence.txt"
    sequence_path.parent.mkdir(parents=True, exist_ok=True)
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.metadata.client = "Client"
    project.metadata.location = "Site"
    project.metadata.engineer_of_record = "Engineer"
    project.metadata.programmer = "Programmer"
    project.metadata.commissioning_agent = "CxA"
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
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
            point_names=["AHU-1 SF-CMD"],
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )
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
    main.save_project(project)

    page = run_async(main.review_release_page(request(f"/project/{project_id}/review"), project_id))
    text = response_text(page)
    assert page.status_code == 200
    assert "Sequence Debt" in text
    assert "Sequence coverage reviewed" in text
    assert "equipment items still have sequence coverage debt to resolve" in text

    blocked = run_async(
        main.approve_release_readiness(
            project_id=project_id,
            notes="Should fail until sequence coverage is resolved.",
        )
    )
    assert blocked.status_code == 303
    assert blocked.headers["location"] == f"/project/{project_id}/review?ready=0"


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
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
            provenance={"parser": "equipment_schedule", "source_doc_id": "equip-doc"},
        )
    )
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
            source=main.PointSource.SEQUENCE,
            source_reference="point-doc:row-1",
            validation_status="valid",
            provenance={"parser": "sequence_parser", "source_doc_id": "point-doc"},
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
    assert bacnet_points.loc[0, "Source"] == "sequence"
    assert bacnet_points.loc[0, "Source Reference"] == "point-doc:row-1"
    assert bacnet_points.loc[0, "Provenance Parser"] == "sequence_parser"
    assert bacnet_points.loc[0, "Effective Controller Mapping"] == "yes"
    assert bacnet_points.loc[0, "Equipment Sequence Reference"] == "AHU-1 sequence.txt"

    bacnet_equipment = pd.read_csv(tmp_path / "bacnet" / "csv" / "equipment.csv")
    assert bacnet_equipment.loc[0, "Sequence Reference"] == "AHU-1 sequence.txt"
    assert bacnet_equipment.loc[0, "Provenance Parser"] == "equipment_schedule"


def test_bacnet_ede_export_includes_lineage_attributes(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="BACNET-LINEAGE", name="BACnet Lineage"))
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.10", network_number=1001)],
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
            source=main.PointSource.SEQUENCE,
            source_reference="seq-doc:req-1",
            validation_status="valid",
            provenance={"parser": "sequence_parser"},
        )
    )

    result = BACnetExporter(project).export(tmp_path / "bacnet")

    assert result.success
    ede_text = (tmp_path / "bacnet" / "project.ede").read_text(encoding="utf-8")
    assert 'source="sequence"' in ede_text
    assert 'sourceReference="seq-doc:req-1"' in ede_text
    assert 'validationStatus="valid"' in ede_text
    assert 'provenanceParser="sequence_parser"' in ede_text
    assert 'sequenceReference="AHU-1 sequence.txt"' in ede_text


def test_tridium_export_includes_review_and_lineage_metadata(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="TRIDIUM-LINEAGE", name="Tridium Lineage"))
    project.validation_status = "warning"
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
            provenance={"parser": "equipment_schedule", "source_doc_id": "equip-doc"},
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.10", network_number=1001)],
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SAT",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            source=main.PointSource.SEQUENCE,
            source_reference="seq-doc:req-1",
            validation_status="valid",
            provenance={"parser": "sequence_parser", "source_doc_id": "seq-doc"},
        )
    )
    project.review_state.approvals.append(
        main.ApprovalReviewDecision(
            approval_key="outputs-ready",
            status="approved",
            notes="Approved for export.",
        )
    )

    result = TridiumExporter(project).export(tmp_path / "tridium")

    assert result.success
    station = json.loads((tmp_path / "tridium" / "TRIDIUM-LINEAGE_fox" / "station.json").read_text())
    components = json.loads((tmp_path / "tridium" / "TRIDIUM-LINEAGE_fox" / "components.json").read_text())
    graphic = json.loads((tmp_path / "tridium" / "TRIDIUM-LINEAGE_fox" / "graphics" / "g_AHU-1.json").read_text())

    assert station["station"]["review"]["validationStatus"] == "warning"
    assert station["station"]["review"]["outputsApproved"] is True

    equipment_component = next(component for component in components["components"] if component["type"] == "equipment")
    point_component = next(component for component in components["components"] if component["name"] == "AHU-1 SAT")
    assert equipment_component["properties"]["sequenceReference"] == "AHU-1 sequence.txt"
    assert equipment_component["properties"]["provenanceParser"] == "equipment_schedule"
    assert point_component["properties"]["source"] == "sequence"
    assert point_component["properties"]["sourceReference"] == "seq-doc:req-1"
    assert point_component["properties"]["provenanceParser"] == "sequence_parser"

    assert graphic["metadata"]["sequenceReference"] == "AHU-1 sequence.txt"
    binding = next(component for component in graphic["components"] if component["type"] == "binding")
    assert binding["source"] == "sequence"
    assert binding["validationStatus"] == "valid"


def test_jci_siemens_and_honeywell_exports_include_lineage_metadata(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="VENDOR-LINEAGE", name="Vendor Lineage"))
    project.validation_status = "warning"
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
            provenance={"parser": "equipment_schedule", "source_doc_id": "equip-doc"},
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.10", network_number=1001)],
        )
    )
    project.add_controller(
        Controller(
            id="MPC-2",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.11", network_number=1002)],
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SAT",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            source=main.PointSource.SEQUENCE,
            source_reference="seq-doc:req-1",
            validation_status="valid",
            provenance={"parser": "sequence_parser", "source_doc_id": "seq-doc"},
        )
    )
    project.review_state.mapping_decisions.append(
        main.MappingReviewDecision(
            mapping_key="point-controller:AHU-1 SAT",
            mapped_to="MPC-2",
            status="accepted",
            notes="Use field-verified controller.",
        )
    )
    project.review_state.approvals.append(
        main.ApprovalReviewDecision(
            approval_key="outputs-ready",
            status="approved",
            notes="Approved for export.",
        )
    )

    jci_result = JCIExporter(project).export(tmp_path / "jci")
    siemens_result = SiemensExporter(project).export(tmp_path / "siemens")
    honeywell_result = HoneywellExporter(project).export(tmp_path / "honeywell")

    assert jci_result.success
    assert siemens_result.success
    assert honeywell_result.success

    jci_points = (tmp_path / "jci" / "VENDOR-LINEAGE_jci" / "points.xml").read_text(encoding="utf-8")
    jci_nae = (tmp_path / "jci" / "VENDOR-LINEAGE_jci" / "nae_config.xml").read_text(encoding="utf-8")
    jci_graphic = json.loads((tmp_path / "jci" / "VENDOR-LINEAGE_jci" / "graphics" / "g_AHU-1.json").read_text())
    assert 'source="sequence"' in jci_points
    assert 'mappedController="true"' in jci_points
    assert 'sequenceReference="AHU-1 sequence.txt"' in jci_points
    assert 'validationStatus="warning"' in jci_nae
    assert jci_graphic["metadata"]["sequenceReference"] == "AHU-1 sequence.txt"
    assert jci_graphic["objects"][1]["source"] == "sequence"

    siemens_points = pd.read_csv(tmp_path / "siemens" / "VENDOR-LINEAGE_siemens" / "desigo_points.csv")
    siemens_equipment = pd.read_csv(tmp_path / "siemens" / "VENDOR-LINEAGE_siemens" / "equipment.csv")
    siemens_graphic = json.loads((tmp_path / "siemens" / "VENDOR-LINEAGE_siemens" / "graphics" / "g_AHU-1.json").read_text())
    assert siemens_points.loc[0, "Source"] == "sequence"
    assert siemens_points.loc[0, "MappedController"] == "yes"
    assert siemens_points.loc[0, "SequenceReference"] == "AHU-1 sequence.txt"
    assert siemens_equipment.loc[0, "SequenceReference"] == "AHU-1 sequence.txt"
    assert siemens_graphic["metadata"]["sequenceReference"] == "AHU-1 sequence.txt"
    assert siemens_graphic["objects"][2]["validationStatus"] == "valid"

    honeywell_points = pd.read_csv(tmp_path / "honeywell" / "VENDOR-LINEAGE_honeywell" / "points.csv")
    honeywell_equipment = pd.read_csv(tmp_path / "honeywell" / "VENDOR-LINEAGE_honeywell" / "equipment.csv")
    honeywell_graphic = json.loads((tmp_path / "honeywell" / "VENDOR-LINEAGE_honeywell" / "graphics" / "g_AHU-1.json").read_text())
    assert honeywell_points.loc[0, "Source"] == "sequence"
    assert honeywell_points.loc[0, "Mapped Controller"] == "yes"
    assert honeywell_points.loc[0, "Sequence Reference"] == "AHU-1 sequence.txt"
    assert honeywell_equipment.loc[0, "Sequence Reference"] == "AHU-1 sequence.txt"
    assert honeywell_graphic["metadata"]["sequenceReference"] == "AHU-1 sequence.txt"
    assert honeywell_graphic["objects"][1]["source"] == "sequence"


def test_logic_generation_includes_sequence_review_metadata(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="LOGIC-SEQ", name="Logic Sequence"))
    sequence_path = tmp_path / "ahu-sequence.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.10", network_number=1001)],
        )
    )
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )

    result = main.generate_logic(project, tmp_path / "logic")

    assert result["json"]
    logic_json = json.loads(result["json"][0].read_text(encoding="utf-8"))
    assert logic_json["metadata"]["sequence_reference"] == "AHU-1 sequence.txt"
    assert logic_json["metadata"]["sequence_review_status"] == "attention"
    assert "AHU-1 SF-STS" in logic_json["metadata"]["sequence_missing_refs"]
    assert "Status/proof point" in logic_json["metadata"]["sequence_missing_families"]


def test_checkout_generation_includes_sequence_review_context(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="CHECKOUT-SEQ", name="Checkout Sequence"))
    sequence_path = tmp_path / "ahu-sequence.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.10", network_number=1001)],
        )
    )
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )

    result = main.generate_checkout_sheets(project, tmp_path / "checkout")

    markdown_text = result["markdown"][0].read_text(encoding="utf-8")
    summary_df = pd.read_excel(result["excel"], sheet_name="Summary")

    assert "**Sequence Reference:** AHU-1 sequence.txt" in markdown_text
    assert "**Sequence Review Status:** attention" in markdown_text
    assert "AHU-1 SF-STS" in markdown_text
    assert "Status/proof point" in markdown_text
    assert summary_df.loc[0, "Sequence Review Status"] == "attention"
    assert "AHU-1 SF-STS" in str(summary_df.loc[0, "Sequence Missing Refs"])


def test_graphics_generation_includes_sequence_review_context(tmp_path: Path) -> None:
    project = Project(metadata=ProjectMetadata(project_id="GRAPHICS-SEQ", name="Graphics Sequence"))
    sequence_path = tmp_path / "ahu-sequence.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="10.1.1.10", network_number=1001)],
        )
    )
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )

    result = main.generate_graphics(project, tmp_path / "graphics")

    assert result["summaries"]
    summary = result["summaries"][0]
    assert summary["sequence_reference"] == "AHU-1 sequence.txt"
    assert summary["sequence_review_status"] == "attention"
    assert "AHU-1 SF-STS" in summary["sequence_missing_refs"]
    assert "Status/proof point" in summary["sequence_missing_families"]


def test_graphics_page_surfaces_sequence_review_context_after_generation() -> None:
    project_id = create_project("graphics-sequence-context-project")
    project = main.get_project(project_id)
    sequence_path = main.OUTPUT_DIR / project_id / "sequence.txt"
    sequence_path.parent.mkdir(parents=True, exist_ok=True)
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.points.append(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )
    main.save_project(project)

    response = run_async(main.graphics_page(request(f"/project/{project_id}/graphics/generate", method="POST"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Sequence Review: attention" in text
    assert "AHU-1 SF-STS" in text
    assert "Status/proof point" in text


def test_graphics_page_loads_persisted_results_and_fullscreen_link() -> None:
    project_id = create_project("graphics-persisted-project")
    project = main.get_project(project_id)
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
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
    main.save_project(project)

    run_async(main.graphics_page(request(f"/project/{project_id}/graphics/generate", method="POST"), project_id))
    response = run_async(main.graphics_page(request(f"/project/{project_id}/graphics"), project_id))

    persisted = main.load_generated_graphics_result(project)
    assert persisted is not None
    graphic_name = persisted["json"][0].stem

    text = response_text(response)
    assert response.status_code == 200
    assert "Validated Delivery Snapshot" in text
    assert "Inspect" in text
    assert "Sim" in text
    assert "Fullscreen" in text
    assert "Active Device Graphics" in text
    assert "Known Unit Library" in text
    assert "Graphics Library" not in text
    assert f"/project/{project_id}/graphics/{graphic_name}" in text
    assert text.count(f"/project/{project_id}/graphics/{graphic_name}/fullscreen") >= 2
    assert f"/project/{project_id}/graphics/{graphic_name}/fullscreen" in text
    assert f"/output/{project_id}/graphics/graphics_svg/{graphic_name}.svg" in text


def test_graphics_fullscreen_page_renders_graphic_context() -> None:
    project_id = create_project("graphics-fullscreen-project")
    project = main.get_project(project_id)
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
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
    main.save_project(project)

    output_dir = main.OUTPUT_DIR / project_id / "graphics"
    output_dir.mkdir(parents=True, exist_ok=True)
    main.generate_graphics(project, output_dir)
    persisted = main.load_generated_graphics_result(project)
    assert persisted is not None
    graphic_name = persisted["json"][0].stem

    response = run_async(
        main.graphics_fullscreen_page(
            request(f"/project/{project_id}/graphics/{graphic_name}/fullscreen"),
            project_id,
            graphic_name,
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "Realtime Simulation Deck" in text
    assert "Live Telemetry" in text
    assert "hvac-sim-data" in text
    assert "Graphic Payload" in text
    assert "Object Context" in text
    assert "AHU-1" in text


def test_graphics_detail_page_renders_elements_and_bindings() -> None:
    project_id = create_project("graphics-detail-project")
    project = main.get_project(project_id)
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
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
    project.points.append(
        main.Point(
            name="AHU-1 SF STATUS",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.STATUS,
            direction=main.PointDirection.INPUT,
        )
    )
    main.save_project(project)

    output_dir = main.OUTPUT_DIR / project_id / "graphics"
    output_dir.mkdir(parents=True, exist_ok=True)
    main.generate_graphics(project, output_dir)
    persisted = main.load_generated_graphics_result(project)
    assert persisted is not None
    graphic_name = persisted["json"][0].stem

    response = run_async(
        main.graphics_detail_page(
            request(f"/project/{project_id}/graphics/{graphic_name}"),
            project_id,
            graphic_name,
        )
    )

    text = response_text(response)
    assert response.status_code == 200
    assert "Graphic Inspect" in text
    assert "Physical Asset Assembly" in text
    assert "Elements And Bindings" in text
    assert "Connected Points" in text
    assert "Point Matrix" in text
    assert "Legend" in text
    assert "station-point-badge" in text
    assert "AHU-1 SAT" in text
    assert "AHU Draw-Through Cabinet" in text
    assert "Explicit Relations" in text
    assert "AHU-1 SF STATUS" in text
    assert f"/output/{project_id}/graphics/graphics_json/{graphic_name}.json" in text


def test_read_only_project_api_endpoints() -> None:
    project_id = create_project()

    summary = run_async(main.api_project_summary(project_id))
    status = run_async(main.api_project_status(project_id))
    equipment = run_async(main.api_equipment_list(project_id))
    points = run_async(main.api_points_list(project_id))
    controllers = run_async(main.api_controllers_list(project_id))

    assert summary["project_id"] == project_id
    assert "score_pct" in status
    assert "checks" in status
    assert summary["equipment_count"] == 0
    assert equipment == []
    assert points == []
    assert controllers == []


def test_project_status_page_renders_development_snapshot() -> None:
    project_id = create_project("status-page-project")
    project = main.get_project(project_id)
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
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )
    main.save_project(project)

    response = run_async(main.project_status_page(request(f"/project/{project_id}/status"), project_id))

    text = response_text(response)
    assert response.status_code == 200
    assert "Development Status" in text
    assert "Next Actions" in text
    assert "Sequence Debt" in text
    assert "Generator Readiness" in text


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


def test_validation_report_markdown_includes_sequence_coverage_summary(tmp_path: Path) -> None:
    project = Project(
        metadata=ProjectMetadata(
            project_id="validation-report-project",
            name="Validation Report Project",
        )
    )
    sequence_path = tmp_path / "ahu-sequence.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )

    ValidationEngine().validate(project)
    report_paths = generate_reports(project, tmp_path / "reports")
    validation_text = report_paths["validation"].read_text(encoding="utf-8")

    assert "## Sequence Coverage Review" in validation_text
    assert "- Missing referenced points: 1" in validation_text
    assert "- Missing control families: Status/proof point" in validation_text
    assert "### AHU-1" in validation_text
    assert "- Missing point refs: AHU-1 SF-STS" in validation_text
    assert "`COMP-007` equipment `AHU-1`" in validation_text


def test_development_status_report_markdown_summarizes_readiness(tmp_path: Path) -> None:
    project = Project(
        metadata=ProjectMetadata(
            project_id="development-status-project",
            name="Development Status Project",
        )
    )
    sequence_path = tmp_path / "ahu-sequence.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.add_controller(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.add_equipment(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.add_point(
        main.Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=main.PointKind.ACTUATOR,
            direction=main.PointDirection.OUTPUT,
        )
    )

    report_paths = generate_reports(project, tmp_path / "reports")
    development_text = report_paths["development_status"].read_text(encoding="utf-8")

    assert "# Development Status" in development_text
    assert "**Readiness Score:**" in development_text
    assert "- **Sequence Coverage:** attention" in development_text
    assert "- Needs attention: 1" in development_text
    assert "- Missing referenced points: 1" in development_text
