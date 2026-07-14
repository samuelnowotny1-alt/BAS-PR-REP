import asyncio
from alembic import command
from alembic.config import Config
import sys
import types
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import inspect, select
from starlette.requests import Request

from bas_assistant.auth import hash_password, verify_password
from bas_assistant.database import ArtifactObjectLinkRecord, DocumentRecord, EquipmentRecord, KnowledgeRecord, PointRecord, TaskRecord, UploadRecord, UserAccount
from bas_assistant.generators.px_graphics import generate_vav_px
from bas_assistant.services.knowledge import KnowledgeIngestionService
from ui.api import main


def request(path: str = "/", method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "root_path": "",
            "app": main.app,
            "session": {},
        }
    )


def test_password_hash_round_trip() -> None:
    stored = hash_password("sup3r-secret")

    assert stored != "sup3r-secret"
    assert verify_password("sup3r-secret", stored) is True
    assert verify_password("wrong-password", stored) is False


def test_database_bootstrap_creates_expected_tables_and_admin(
    tmp_path: Path,
) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
    )

    table_names = set(inspect(main.container.db.engine).get_table_names())

    assert {"users", "projects", "project_memberships", "documents", "uploads", "graphics", "equipment", "points", "controllers", "conversations", "knowledge", "tasks", "logs", "artifact_object_links"}.issubset(table_names)

    with main.container.db.session() as session:
        admin = session.scalar(select(UserAccount).where(UserAccount.username == main.container.settings.bootstrap_admin_username))

    assert admin is not None
    assert admin.role == "admin"


def test_alembic_upgrade_head_creates_artifact_link_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "alembic.db"
    alembic_cfg = Config("/home/oem/.openclaw/workspace/bas-assistant/alembic.ini")
    alembic_cfg.set_main_option("script_location", "/home/oem/.openclaw/workspace/bas-assistant/migrations")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(alembic_cfg, "head")

    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{database_path}")
    table_names = set(inspect(engine).get_table_names())
    assert "artifact_object_links" in table_names


def test_login_and_logout_flow(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'session.db'}",
    )

    login_request = request("/login", method="POST")
    login_response = asyncio.run(
        main.login_submit(
            login_request,
            username=main.container.settings.bootstrap_admin_username,
            password=main.container.settings.bootstrap_admin_password,
        )
    )
    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/"
    assert login_request.scope["session"]["user"]["username"] == main.container.settings.bootstrap_admin_username

    home_response = asyncio.run(main.index(login_request))
    assert home_response.status_code == 200
    assert main.container.settings.bootstrap_admin_username in home_response.body.decode()

    logout_response = asyncio.run(main.logout(login_request))
    assert logout_response.status_code == 303
    assert logout_response.headers["location"] == "/login"
    assert login_request.scope["session"] == {}


def test_protected_pages_require_authentication(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'protected.db'}",
    )

    home_request = request("/")
    home_response = asyncio.run(main.authentication_middleware(home_request, lambda _request: PlainTextResponse("ok")))
    assert home_response.status_code == 303
    assert home_response.headers["location"] == "/login"

    api_request = request("/api/load-demo", method="POST")
    api_response = asyncio.run(main.authentication_middleware(api_request, lambda _request: PlainTextResponse("ok")))
    assert api_response.status_code == 401


def test_role_permissions_block_viewer_writes_and_allow_engineer(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'roles.db'}",
    )

    async def ok_response(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    viewer_request = request("/api/load-demo", method="POST")
    viewer_request.scope["session"]["user"] = {
        "id": 10,
        "username": "viewer",
        "email": "viewer@example.com",
        "role": "viewer",
    }
    viewer_response = asyncio.run(
        main.authentication_middleware(viewer_request, ok_response)
    )
    assert viewer_response.status_code == 403

    engineer_request = request("/api/load-demo", method="POST")
    engineer_request.scope["session"]["user"] = {
        "id": 11,
        "username": "engineer",
        "email": "engineer@example.com",
        "role": "engineer",
    }
    engineer_response = asyncio.run(
        main.authentication_middleware(engineer_request, ok_response)
    )
    assert engineer_response.status_code == 200


def test_project_scoped_permissions_limit_viewer_access(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'project_scope.db'}",
    )
    asyncio.run(
        main.api_create_project(
            project_id="allowed-project",
            name="Allowed Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )
    asyncio.run(
        main.api_create_project(
            project_id="blocked-project",
            name="Blocked Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    async def ok_response(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    allowed_request = request("/project/allowed-project")
    allowed_request.scope["session"]["user"] = {
        "id": 2,
        "username": "viewer",
        "email": "viewer@example.com",
        "role": "viewer",
        "assigned_project_ids": ["allowed-project"],
    }
    allowed_response = asyncio.run(main.authentication_middleware(allowed_request, ok_response))
    assert allowed_response.status_code == 200

    blocked_request = request("/project/blocked-project")
    blocked_request.scope["session"]["user"] = {
        "id": 2,
        "username": "viewer",
        "email": "viewer@example.com",
        "role": "viewer",
        "assigned_project_ids": ["allowed-project"],
    }
    blocked_response = asyncio.run(main.authentication_middleware(blocked_request, ok_response))
    assert blocked_response.status_code == 403


def test_admin_user_management_creates_user_with_project_assignment(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'admin_users.db'}",
    )
    asyncio.run(
        main.api_create_project(
            project_id="admin-project",
            name="Admin Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    admin_request = request("/admin/users", method="POST")
    admin_request.scope["session"]["user"] = {
        "id": 1,
        "username": "admin",
        "email": "admin@example.com",
        "role": "admin",
        "assigned_project_ids": [],
    }
    response = asyncio.run(
        main.admin_create_user(
            admin_request,
            username="fieldtech",
            email="fieldtech@example.com",
            password="FieldTech123!",
            role="technician",
            project_ids=["admin-project"],
            access_level="viewer",
        )
    )
    assert response.status_code == 303

    users = main.container.auth.list_users()
    created_user = next(user for user in users if user.username == "fieldtech")
    assert created_user.assigned_projects
    assert created_user.assigned_projects[0]["project_id"] == "admin-project"


def test_admin_user_management_updates_role_and_memberships(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'admin_update.db'}",
    )
    for project_id in ("project-a", "project-b"):
        asyncio.run(
            main.api_create_project(
                project_id=project_id,
                name=project_id,
                client="Client",
                location="Site",
                unit_system="IP",
                design_phase="DD",
                engineer="Engineer",
                programmer="Programmer",
                cx_agent="Cx",
                naming_standard="ASHRAE-135",
            )
        )

    created = main.container.auth.create_user(
        username="operator",
        email="operator@example.com",
        password="Operator123!",
        role="viewer",
        project_ids=["project-a"],
        access_level="viewer",
    )
    admin_request = request("/admin/users/1", method="POST")
    admin_request.scope["session"]["user"] = {
        "id": 1,
        "username": "admin",
        "email": "admin@example.com",
        "role": "admin",
        "assigned_project_ids": [],
    }

    response = asyncio.run(
        main.admin_update_user(
            admin_request,
            user_id=created.id,
            role="engineer",
            is_active="false",
            project_ids=["project-b"],
            access_level="editor",
        )
    )

    assert response.status_code == 303
    managed = next(user for user in main.container.auth.list_users() if user.id == created.id)
    assert managed.role == "engineer"
    assert managed.is_active is False
    assert managed.assigned_projects[0]["project_id"] == "project-b"
    assert managed.assigned_projects[0]["access_level"] == "editor"


def test_project_bulk_membership_update_route(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'project_memberships.db'}",
    )
    asyncio.run(
        main.api_create_project(
            project_id="team-project",
            name="Team Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )
    engineer = main.container.auth.create_user(
        username="designeng",
        email="designeng@example.com",
        password="DesignEng123!",
        role="engineer",
    )
    viewer = main.container.auth.create_user(
        username="readonly",
        email="readonly@example.com",
        password="ReadOnly123!",
        role="viewer",
    )

    async def set_form() -> Request:
        req = request("/project/team-project/memberships", method="POST")
        req.scope["session"]["user"] = {
            "id": 1,
            "username": "admin",
            "email": "admin@example.com",
            "role": "admin",
            "assigned_project_ids": [],
        }
        return req

    membership_request = asyncio.run(set_form())

    async def fake_form():
        from starlette.datastructures import FormData
        return FormData(
            {
                f"user_access_{engineer.id}": "editor",
                f"user_access_{viewer.id}": "viewer",
            }
        )

    membership_request.form = fake_form  # type: ignore[method-assign]
    response = asyncio.run(main.project_memberships_update(membership_request, "team-project"))

    assert response.status_code == 303
    updated_users = main.container.auth.list_users()
    eng = next(user for user in updated_users if user.id == engineer.id)
    ro = next(user for user in updated_users if user.id == viewer.id)
    assert eng.assigned_projects[0]["project_id"] == "team-project"
    assert eng.assigned_projects[0]["access_level"] == "editor"
    assert ro.assigned_projects[0]["access_level"] == "viewer"


def test_import_uploads_are_persisted_to_upload_service(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'uploads.db'}",
    )

    project_id = "upload-project"
    asyncio.run(
        main.api_create_project(
            project_id=project_id,
            name="Upload Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    equipment_upload = UploadFile(filename="equipment.csv", file=BytesIO(b"Equipment ID,Equipment Type\nAHU-1,AHU\n"))
    text_upload = UploadFile(filename="sequence.txt", file=BytesIO(b"Supply fan shall enable on occupied command."))

    response = asyncio.run(
        main.import_data(
            request(f"/project/{project_id}/import", method="POST"),
            project_id=project_id,
            equipment_file=equipment_upload,
            points_file=None,
            controllers_file=None,
            supporting_files=[text_upload],
        )
    )

    assert response.status_code == 303
    project = main.get_project(project_id)
    matching_documents = [doc for doc in project.source_documents if doc.name == "equipment.csv"]
    assert matching_documents
    assert any(Path(doc.path or "").exists() for doc in matching_documents)

    with main.container.db.session() as session:
        uploads = list(session.scalars(select(UploadRecord)))
        equipment = list(session.scalars(select(EquipmentRecord)))
        knowledge = list(session.scalars(select(KnowledgeRecord)))
        tasks = list(session.scalars(select(TaskRecord)))

    assert len(uploads) == 2
    assert any(record.filename == "equipment.csv" for record in uploads)
    assert any(record.filename == "sequence.txt" for record in uploads)
    assert len(equipment) == 1
    assert knowledge
    assert any(record.source_name == "sequence.txt" and record.status == "indexed" for record in knowledge)
    assert tasks
    assert any(record.task_type == "equipment_import" and record.status == "completed" for record in tasks)
    assert any(record.task_type == "artifact_ingestion" and record.status == "completed" for record in tasks)


def test_px_upload_parses_into_structured_equipment_and_points(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'px_uploads.db'}",
    )

    project_id = "graphics-project"
    asyncio.run(
        main.api_create_project(
            project_id=project_id,
            name="Graphics Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    px_xml = generate_vav_px("Zone VAV", "VAV-201").to_string().encode("utf-8")
    px_upload = UploadFile(filename="VAV-201.px", file=BytesIO(px_xml))

    response = asyncio.run(
        main.import_data(
            request(f"/project/{project_id}/import", method="POST"),
            project_id=project_id,
            equipment_file=None,
            points_file=None,
            controllers_file=None,
            supporting_files=[px_upload],
        )
    )

    assert response.status_code == 303
    with main.container.db.session() as session:
        equipment = list(session.scalars(select(EquipmentRecord)))
        points = list(session.scalars(select(PointRecord)))
        knowledge = list(session.scalars(select(KnowledgeRecord)))
        links = list(session.scalars(select(ArtifactObjectLinkRecord)))

    assert any(record.equipment_key == "VAV-201" for record in equipment)
    assert points
    assert any(record.source_name == "VAV-201.px" for record in knowledge)
    assert any(record.entity_type == "equipment" and record.entity_key == "VAV-201" for record in links)


def test_niagara_station_zip_parses_manifest_content(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'zip_uploads.db'}",
    )

    project_id = "station-project"
    asyncio.run(
        main.api_create_project(
            project_id=project_id,
            name="Station Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("station_manifest.txt", "Controller JACE-01 serves AHU-1 SAT and VAV-201 ZN-T")
    zip_buffer.seek(0)
    zip_upload = UploadFile(filename="station.zip", file=zip_buffer)

    response = asyncio.run(
        main.import_data(
            request(f"/project/{project_id}/import", method="POST"),
            project_id=project_id,
            equipment_file=None,
            points_file=None,
            controllers_file=None,
            supporting_files=[zip_upload],
        )
    )

    assert response.status_code == 303
    project = main.get_project(project_id)
    assert project.get_equipment("AHU-1") is not None
    assert project.get_equipment("VAV-201") is not None
    assert project.controllers
    assert any(point.name.startswith("AHU-1_") for point in project.points)


def test_niagara_station_tree_zip_parses_slot_paths(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'tree_uploads.db'}",
    )

    project_id = "tree-project"
    asyncio.run(
        main.api_create_project(
            project_id=project_id,
            name="Tree Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr(
            "station_tree.txt",
            "station:|slot:/Drivers/BacnetNetwork/MPC-1/Points/AHU-1_SAT\n"
            "station:|slot:/Config/Equipment/Admin/1/AHU-1\n",
        )
    zip_buffer.seek(0)
    zip_upload = UploadFile(filename="station-tree.zip", file=zip_buffer)

    response = asyncio.run(
        main.import_data(
            request(f"/project/{project_id}/import", method="POST"),
            project_id=project_id,
            equipment_file=None,
            points_file=None,
            controllers_file=None,
            supporting_files=[zip_upload],
        )
    )

    assert response.status_code == 303
    project = main.get_project(project_id)
    controller = project.get_controller("MPC-1")
    point = project.get_point("AHU-1_SAT")
    equipment = project.get_equipment("AHU-1")
    assert controller is not None
    assert point is not None
    assert equipment is not None
    assert equipment.provenance["parser"] == "niagara_station_tree"
    assert point.controller_id == "MPC-1"


def test_reimport_records_artifact_diff_against_previous_document(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'reimport.db'}",
    )

    project_id = "reimport-project"
    asyncio.run(
        main.api_create_project(
            project_id=project_id,
            name="Reimport Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    first_upload = UploadFile(filename="equipment.csv", file=BytesIO(b"Equipment ID,Equipment Type\nAHU-1,AHU\n"))
    second_upload = UploadFile(filename="equipment.csv", file=BytesIO(b"Equipment ID,Equipment Type\nAHU-1,AHU\nAHU-2,AHU\n"))

    asyncio.run(main.import_data(request(f"/project/{project_id}/import", method="POST"), project_id=project_id, equipment_file=first_upload))
    asyncio.run(main.import_data(request(f"/project/{project_id}/import", method="POST"), project_id=project_id, equipment_file=second_upload))

    with main.container.db.session() as session:
        latest_task = session.scalar(
            select(TaskRecord)
            .where(TaskRecord.project_id.is_not(None), TaskRecord.task_type == "equipment_import")
            .order_by(TaskRecord.id.desc())
        )

    assert latest_task is not None
    artifact_diff = latest_task.result_json["result"]["artifact_diff"]
    assert "equipment:AHU-2" in artifact_diff["added"]
    assert "equipment:AHU-1" in artifact_diff["unchanged"]


def test_niagara_xml_manifest_traverses_slot_hierarchy(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'xml_uploads.db'}",
    )

    project_id = "xml-project"
    asyncio.run(
        main.api_create_project(
            project_id=project_id,
            name="XML Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    xml_payload = b"""<station>
    <Drivers>
      <BacnetNetwork>
        <controller name="MPC-2">
          <Points>
            <point name="AHU-2_SAT" />
          </Points>
        </controller>
      </BacnetNetwork>
    </Drivers>
    <Config>
      <Equipment>
        <Area name="Level1">
          <equipment name="AHU-2" />
        </Area>
      </Equipment>
    </Config>
    </station>"""
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("station.xml", xml_payload)
    zip_buffer.seek(0)
    upload = UploadFile(filename="station-xml.zip", file=zip_buffer)

    response = asyncio.run(main.import_data(request(f"/project/{project_id}/import", method="POST"), project_id=project_id, supporting_files=[upload]))

    assert response.status_code == 303
    project = main.get_project(project_id)
    assert project.get_controller("MPC-2") is not None
    assert project.get_equipment("AHU-2") is not None
    assert project.get_point("AHU-2_SAT") is not None


def test_niagara_station_graph_sets_parent_child_relationships(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'graph_uploads.db'}",
    )

    project_id = "graph-project"
    asyncio.run(
        main.api_create_project(
            project_id=project_id,
            name="Graph Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr(
            "station_tree.txt",
            "station:|slot:/Config/Equipment/Plant/AHU-1/VAV-201\n"
            "station:|slot:/Drivers/BacnetNetwork/MPC-1/Points/VAV-201_ZN-T\n",
        )
    zip_buffer.seek(0)
    upload = UploadFile(filename="station-graph.zip", file=zip_buffer)

    response = asyncio.run(main.import_data(request(f"/project/{project_id}/import", method="POST"), project_id=project_id, supporting_files=[upload]))

    assert response.status_code == 303
    project = main.get_project(project_id)
    ahu = project.get_equipment("AHU-1")
    vav = project.get_equipment("VAV-201")
    assert ahu is not None
    assert vav is not None
    assert vav.parent_equipment_id == "AHU-1"
    assert "VAV-201" in ahu.child_equipment_ids
    assert any(rel.type == "contains" and rel.target_equipment_id == "VAV-201" for rel in ahu.relationships)
    with main.container.db.session() as session:
        generated_docs = list(session.scalars(select(DocumentRecord).where(DocumentRecord.document_type == "archive")))
        generated_links = list(session.scalars(select(ArtifactObjectLinkRecord)))
    assert generated_docs
    assert any(link.relationship_type == "source" for link in generated_links)


def test_generated_graphics_are_registered_as_artifacts(tmp_path: Path) -> None:
    main.configure_runtime_paths(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'generated_artifacts.db'}",
    )
    project_id = "generated-project"
    asyncio.run(
        main.api_create_project(
            project_id=project_id,
            name="Generated Project",
            client="Client",
            location="Site",
            unit_system="IP",
            design_phase="DD",
            engineer="Engineer",
            programmer="Programmer",
            cx_agent="Cx",
            naming_standard="ASHRAE-135",
        )
    )
    project = main.get_project(project_id)
    project.add_equipment(main.Equipment(id="AHU-1", type=main.EquipmentType.AHU))
    project.add_point(
        main.Point(
            name="AHU-1_SAT",
            equipment_id="AHU-1",
            kind=main.PointKind.SENSOR,
            direction=main.PointDirection.INPUT,
            units="degF",
        )
    )
    main.save_project(project)

    response = asyncio.run(main.graphics_page(request(f"/project/{project_id}/graphics"), project_id))

    assert response.status_code == 200
    with main.container.db.session() as session:
        docs = list(session.scalars(select(DocumentRecord).where(DocumentRecord.document_type == "generated_graphic_svg")))
        links = list(
            session.scalars(
                select(ArtifactObjectLinkRecord).where(ArtifactObjectLinkRecord.relationship_type == "generated_output")
            )
        )
        task = session.scalar(select(TaskRecord).where(TaskRecord.task_type == "graphics_generation").order_by(TaskRecord.id.desc()))
    assert docs
    assert any(link.entity_type == "equipment" and link.entity_key == "AHU-1" for link in links)
    assert task is not None
    assert task.result_json["result"]["generated_documents"]


def test_pdf_ingestion_extracts_text_with_pypdf_adapter(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "sequence.pdf"
    pdf_path.write_bytes(b"%PDF-test")

    class _FakePage:
        def extract_text(self) -> str:
            return "Supply fan enables on schedule."

    class _FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [_FakePage()]

    fake_module = types.ModuleType("pypdf")
    fake_module.PdfReader = _FakeReader
    monkeypatch.setitem(sys.modules, "pypdf", fake_module)

    service = KnowledgeIngestionService(main.container.db)
    text, status, metadata = service._extract_pdf_text(pdf_path)

    assert "Supply fan enables on schedule." in text
    assert status == "indexed"
    assert metadata["page_count"] == 1
