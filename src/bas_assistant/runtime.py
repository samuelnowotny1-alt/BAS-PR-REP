"""Runtime bootstrap helpers for BAS Assistant."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

from .config import Settings


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


def seed_codex_demo_project(projects_repo, output_dir: Path, logger: logging.Logger) -> None:
    """Seed the Codex Test Project with HVAC sample data on first run when no projects exist."""
    projects = projects_repo.list_projects()
    if projects:
        logger.info("Projects already exist, skipping Codex demo project seeding")
        return
    
    logger.info("No projects found, seeding Codex Test Project with HVAC sample data...")
    
    # Import here to avoid circular imports
    from bas_assistant.models import Project, ProjectMetadata, UnitSystem
    from bas_assistant.importers import CSVImporter, create_sample_csvs
    from bas_assistant.generators import (
        generate_checkout_sheets, generate_reports, generate_graphics, generate_logic
    )
    from bas_assistant.exporters import (
        NiagaraExporter, BACnetExporter, TridiumExporter,
        JCIExporter, SiemensExporter, HoneywellExporter
    )
    from bas_assistant.validation import ValidationEngine
    from bas_assistant.reasoning import analyze_gaps
    
    project_id = "codex-test-project"
    
    # Create project
    metadata = ProjectMetadata(
        project_id=project_id,
        name="Codex Test Project",
        client="Codex Demo Client",
        location="Codex Test Building",
        unit_system=UnitSystem.IP,
        design_phase="Design Development",
        engineer_of_record="Codex Engineer",
        programmer="Codex Programmer",
        commissioning_agent="Codex CxA",
        naming_standard="ASHRAE 135",
    )
    project = Project(metadata=metadata)
    
    # Import sample data
    importer = CSVImporter(project)
    create_sample_csvs(Path(__file__).parent.parent.parent / "examples")
    
    equip_file = Path(__file__).parent.parent.parent / "examples" / "equipment_schedule.csv"
    if equip_file.exists():
        importer.import_equipment_schedule(equip_file, "equip_schedule_codex")
    
    points_file = Path(__file__).parent.parent.parent / "examples" / "point_list.csv"
    if points_file.exists():
        importer.import_point_list(points_file, "point_list_codex")
    
    ctrl_file = Path(__file__).parent.parent.parent / "examples" / "controller_schedule.csv"
    if ctrl_file.exists():
        importer.import_controller_schedule(ctrl_file, "ctrl_schedule_codex")
    
    # Save project
    projects_repo.save(project)
    
    # Generate all outputs
    project_output_dir = output_dir / project_id
    project_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Validation
    engine = ValidationEngine()
    engine.validate(project)
    
    # Gap analysis
    analyze_gaps(project)
    
    # Checkout sheets
    checkout_dir = project_output_dir / "checkout"
    checkout_dir.mkdir(parents=True, exist_ok=True)
    generate_checkout_sheets(project, checkout_dir)
    
    # Reports
    reports_dir = project_output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    generate_reports(project, reports_dir)
    
    # Graphics
    graphics_dir = project_output_dir / "graphics"
    graphics_dir.mkdir(parents=True, exist_ok=True)
    generate_graphics(project, graphics_dir)
    
    # Logic
    logic_dir = project_output_dir / "logic"
    logic_dir.mkdir(parents=True, exist_ok=True)
    generate_logic(project, logic_dir)
    
    # Exports
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
        exporter = exporter_class(project)
        exporter.export(vendor_dir)
    
    logger.info(
        "Codex Test Project seeded successfully with %d equipment, %d points, %d controllers",
        len(project.equipment), len(project.points), len(project.controllers)
    )
