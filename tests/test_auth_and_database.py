import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import inspect, select
from starlette.requests import Request

from bas_assistant.auth import hash_password, verify_password
from bas_assistant.database import EquipmentRecord, KnowledgeRecord, UploadRecord, UserAccount
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

    assert {"users", "projects", "documents", "uploads", "graphics", "equipment", "points", "controllers", "conversations", "knowledge", "tasks", "logs"}.issubset(table_names)

    with main.container.db.session() as session:
        admin = session.scalar(select(UserAccount).where(UserAccount.username == main.container.settings.bootstrap_admin_username))

    assert admin is not None
    assert admin.role == "admin"


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

    assert len(uploads) == 2
    assert any(record.filename == "equipment.csv" for record in uploads)
    assert any(record.filename == "sequence.txt" for record in uploads)
    assert len(equipment) == 1
    assert knowledge
    assert any(record.source_name == "sequence.txt" and record.status == "indexed" for record in knowledge)
