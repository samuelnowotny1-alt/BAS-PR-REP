"""Runtime bootstrap helpers for BAS Assistant."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

from .config import Settings
from .models import Project, ProjectMetadata, UnitSystem


def ensure_runtime_directories(settings: Settings) -> None:
    """Create required runtime directories if they do not already exist."""
    settings.static_dir.mkdir(parents=True, exist_ok=True)
    settings.templates_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    (settings.output_dir / "projects").mkdir(parents=True, exist_ok=True)


def configure_logging(settings: Settings) -> None:
    """Configure application logging for console and file output."""
    ensure_runtime_directories(settings)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": settings.log_level,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "standard",
                    "level": settings.log_level,
                    "filename": str(settings.log_file),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 5,
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
            },
        }
    )


def is_path_writable(path: Path) -> bool:
    """Return whether the application can write to a directory."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_file = path / ".write_test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        return True
    except OSError:
        return False


def build_health_report(settings: Settings, *, loaded_projects: int) -> dict[str, Any]:
    """Create a production-friendly health payload."""
    data_dir_ready = settings.data_dir.exists() and is_path_writable(settings.data_dir)
    output_dir_ready = settings.output_dir.exists() and is_path_writable(settings.output_dir)
    overall_status = "ok" if data_dir_ready and output_dir_ready else "degraded"
    return {
        "status": overall_status,
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "projects_loaded": loaded_projects,
        "checks": {
            "data_dir": {
                "path": str(settings.data_dir),
                "ready": data_dir_ready,
            },
            "output_dir": {
                "path": str(settings.output_dir),
                "ready": output_dir_ready,
            },
            "uploads_dir": {
                "path": str(settings.uploads_dir),
                "ready": settings.uploads_dir.exists() and is_path_writable(settings.uploads_dir),
            },
            "log_dir": {
                "path": str(settings.log_dir),
                "ready": settings.log_dir.exists(),
            },
        },
    }


def _demo_project_metadata(project_id: str, project_name: str) -> ProjectMetadata:
    """Build consistent metadata for generated demo projects."""
    return ProjectMetadata(
        project_id=project_id,
        name=project_name,
        client="Demo Client",
        location="Demo Building",
        unit_system=UnitSystem.IP,
        design_phase="Design Development",
        engineer_of_record="Demo Engineer",
        programmer="Demo Programmer",
        commissioning_agent="Demo CxA",
        naming_standard="ASHRAE 135",
    )


def create_demo_project(project_id: str, project_name: str, examples_dir: Path) -> Project:
    """Create a demo project populated from the example CSV files."""
    from bas_assistant.importers import CSVImporter, create_sample_csvs

    create_sample_csvs(examples_dir)
    project = Project(metadata=_demo_project_metadata(project_id, project_name))
    importer = CSVImporter(project)

    equipment_path = examples_dir / "equipment_schedule.csv"
    if equipment_path.exists():
        importer.import_equipment_schedule(equipment_path, f"{project_id}_equipment")

    points_path = examples_dir / "point_list.csv"
    if points_path.exists():
        importer.import_point_list(points_path, f"{project_id}_points")

    controllers_path = examples_dir / "controller_schedule.csv"
    if controllers_path.exists():
        importer.import_controller_schedule(controllers_path, f"{project_id}_controllers")

    return project


def generate_demo_outputs(project: Project, output_dir: Path) -> None:
    """Generate the standard output bundle for a demo project."""
    from bas_assistant.exporters import (
        BACnetExporter,
        HoneywellExporter,
        JCIExporter,
        NiagaraExporter,
        SiemensExporter,
        TridiumExporter,
    )
    from bas_assistant.generators import (
        generate_checkout_sheets,
        generate_graphics,
        generate_logic,
        generate_reports,
    )
    from bas_assistant.reasoning import analyze_gaps
    from bas_assistant.validation import ValidationEngine

    project_output_dir = output_dir / project.metadata.project_id
    project_output_dir.mkdir(parents=True, exist_ok=True)

    engine = ValidationEngine()
    engine.validate(project)
    analyze_gaps(project)

    checkout_dir = project_output_dir / "checkout"
    checkout_dir.mkdir(parents=True, exist_ok=True)
    generate_checkout_sheets(project, checkout_dir)

    reports_dir = project_output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    generate_reports(project, reports_dir)

    graphics_dir = project_output_dir / "graphics"
    graphics_dir.mkdir(parents=True, exist_ok=True)
    generate_graphics(project, graphics_dir)

    logic_dir = project_output_dir / "logic"
    logic_dir.mkdir(parents=True, exist_ok=True)
    generate_logic(project, logic_dir)

    exports_dir = project_output_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    vendor_map = {
        "niagara": NiagaraExporter,
        "bacnet": BACnetExporter,
        "tridium": TridiumExporter,
        "jci": JCIExporter,
        "siemens": SiemensExporter,
        "honeywell": HoneywellExporter,
    }
    for vendor_name, exporter_class in vendor_map.items():
        vendor_dir = exports_dir / vendor_name
        vendor_dir.mkdir(parents=True, exist_ok=True)
        exporter_class(project).export(vendor_dir)


def provision_demo_project(
    projects_repo,
    output_dir: Path,
    logger: logging.Logger,
    *,
    project_id: str,
    project_name: str,
    examples_dir: Path,
) -> Project:
    """Create, save, and generate artifacts for a demo project."""
    logger.info("Provisioning demo project '%s'", project_id)
    project = create_demo_project(project_id, project_name, examples_dir)
    projects_repo.save(project)
    generate_demo_outputs(project, output_dir)
    logger.info(
        "Demo project '%s' ready with %d equipment, %d points, %d controllers",
        project_id,
        len(project.equipment),
        len(project.points),
        len(project.controllers),
    )
    return project


def seed_codex_demo_project(projects_repo, output_dir: Path, logger: logging.Logger) -> None:
    """Seed the Codex Test Project with HVAC sample data on first run when no projects exist."""
    projects = projects_repo.list_projects()
    if projects:
        logger.info("Projects already exist, skipping Codex demo project seeding")
        return

    logger.info("No projects found, seeding Codex Test Project with HVAC sample data...")
    examples_dir = Path(__file__).parent.parent.parent / "examples"
    provision_demo_project(
        projects_repo,
        output_dir,
        logger,
        project_id="codex-test-project",
        project_name="Codex Test Project",
        examples_dir=examples_dir,
    )
