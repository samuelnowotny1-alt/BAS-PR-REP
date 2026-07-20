import asyncio
from pathlib import Path

import pytest

from bas_assistant.config import Settings
from bas_assistant.runtime import build_health_report, ensure_runtime_directories, seed_codex_demo_project
from bas_assistant.services.projects import JsonProjectRepository
from ui.api import main


@pytest.fixture
def runtime_settings(tmp_path: Path) -> Settings:
    return Settings(
        log_dir=tmp_path / "logs",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        static_dir=tmp_path / "static",
        templates_dir=tmp_path / "templates",
    )


def test_runtime_directories_are_created(runtime_settings: Settings) -> None:
    ensure_runtime_directories(runtime_settings)

    assert runtime_settings.log_dir.exists()
    assert runtime_settings.data_dir.exists()
    assert runtime_settings.output_dir.exists()
    assert runtime_settings.static_dir.exists()
    assert runtime_settings.templates_dir.exists()
    assert (runtime_settings.output_dir / "projects").exists()


def test_build_health_report_marks_runtime_ready(runtime_settings: Settings) -> None:
    ensure_runtime_directories(runtime_settings)

    report = build_health_report(runtime_settings, loaded_projects=3)

    assert report["status"] == "ok"
    assert report["projects_loaded"] == 3
    assert report["checks"]["data_dir"]["ready"] is True
    assert report["checks"]["output_dir"]["ready"] is True


def test_health_endpoint_reports_loaded_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path / "output")
    main.configure_runtime_paths(
        data_dir=main.DATA_DIR,
        output_dir=main.OUTPUT_DIR,
        uploads_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'bas_assistant_runtime.db'}",
    )
    main.projects.clear()
    main.projects["alpha"] = object()  # type: ignore[assignment]

    response = asyncio.run(main.health_check())
    payload = response.body.decode()

    assert response.status_code == 200
    assert '"status":"ok"' in payload
    assert '"projects_loaded":1' in payload


def test_timed_page_context_logs_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []

    def fake_info(message: str, *args) -> None:
        messages.append(message % args)

    monkeypatch.setattr(main.logger, "info", fake_info)

    result = main.timed_page_context("dashboard", lambda: {"ok": True})

    assert result == {"ok": True}
    assert messages
    assert messages[0].startswith("page_context[dashboard] built in ")


def test_seed_codex_demo_project_creates_project_and_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    repo = JsonProjectRepository(data_dir)

    seed_codex_demo_project(repo, output_dir, main.logger)

    project = repo.get("codex-test-project")
    assert project is not None
    assert project.metadata.name == "Codex Test Project"
    assert len(project.equipment) > 0
    assert len(project.points) > 0
    assert len(project.controllers) > 0
    source_types = {document.type for document in project.source_documents}
    assert {"equipment_schedule", "point_list", "controller_schedule"} <= source_types
    assert {"submittal", "sequence", "manual", "point_schedule"} <= source_types
    assert {"station_runtime", "station_snapshot", "trend_log", "alarm_log"} <= source_types
    assert all(document.path for document in project.source_documents)
    assert any(Path(document.path).exists() for document in project.source_documents if document.type == "submittal")
    assert (output_dir / "codex-test-project" / "checkout").exists()
    assert (output_dir / "codex-test-project" / "reports").exists()
    assert (output_dir / "codex-test-project" / "graphics").exists()
    assert (output_dir / "codex-test-project" / "logic").exists()
    assert (output_dir / "codex-test-project" / "exports").exists()
