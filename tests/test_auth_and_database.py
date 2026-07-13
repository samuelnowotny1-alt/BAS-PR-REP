import asyncio
from pathlib import Path

from sqlalchemy import inspect, select
from starlette.requests import Request

from bas_assistant.auth import hash_password, verify_password
from bas_assistant.database import UserAccount
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
