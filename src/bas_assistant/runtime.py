"""Runtime bootstrap helpers for BAS Assistant."""

from __future__ import annotations

import logging
import logging.config
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .models import Project, ProjectMetadata, SourceDocument, UnitSystem


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


def _upsert_source_document(
    project: Project,
    *,
    document_id: str,
    name: str,
    document_type: str,
    path: Path,
    version: str | None = None,
) -> None:
    """Insert or replace a source document reference deterministically."""
    record = SourceDocument(
        id=document_id,
        name=name,
        type=document_type,
        path=str(path),
        version=version,
        imported_at=datetime.now(),
    )
    existing_index = next(
        (
            index
            for index, document in enumerate(project.source_documents)
            if document.id == document_id or (document.name == name and document.type == document_type)
        ),
        None,
    )
    if existing_index is None:
        project.source_documents.append(record)
        return
    project.source_documents[existing_index] = record


def _write_demo_document(path: Path, content: str) -> Path:
    """Write a generated demo source document and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _render_demo_submittal(project: Project) -> str:
    """Create a synthetic submittal summary for the seeded demo station."""
    lines = [
        f"# {project.metadata.name} Simulated Mechanical Submittal",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Project ID: {project.metadata.project_id}",
        f"Client: {project.metadata.client or 'Demo Client'}",
        f"Location: {project.metadata.location or 'Demo Building'}",
        "",
        "## Package Summary",
        f"- Equipment count: {len(project.equipment)}",
        f"- Point count: {len(project.points)}",
        f"- Controller count: {len(project.controllers)}",
        "",
        "## Equipment Selections",
    ]
    for equipment in project.equipment:
        lines.extend(
            [
                f"### {equipment.id}",
                f"- Type: {equipment.type.value}",
                f"- Subtype: {equipment.subtype or 'Standard'}",
                f"- Controller: {equipment.controller_id or 'Pending'}",
                f"- Design airflow: {equipment.design_cfm or 0} CFM",
                f"- Design tonnage: {equipment.design_tonnage or 0}",
                f"- Design water flow: {equipment.design_gpm or 0} GPM",
                f"- Electrical: {equipment.voltage or 'TBD'}V / {equipment.phase or 'TBD'} ph",
                f"- Served area: {equipment.served_area or 'General occupancy'}",
                f"- Notes: {equipment.notes or 'Coordinate final trim and access clearances with field conditions.'}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_demo_sequence(project: Project) -> str:
    """Create a synthetic sequence-of-operations document."""
    lines = [
        f"# {project.metadata.name} Simulated Sequence of Operations",
        "",
        "## General",
        "The BAS shall command, monitor, alarm, and trend all scheduled points shown in the attached point schedule.",
        "All alarms shall annunciate to the operator workstation and the simulated station alarm buffer.",
        "",
    ]
    for equipment in project.equipment:
        lines.append(f"## {equipment.id}")
        if equipment.type.value == "AHU":
            lines.extend(
                [
                    f"{equipment.id} shall enable on occupied schedule, prove supply fan status, and maintain discharge air temperature.",
                    f"{equipment.id} shall modulate outside air, cooling coil, and heating coil outputs to maintain setpoint.",
                    f"{equipment.id} shall alarm on dirty filter, fan failure, low discharge temperature, and smoke shutdown.",
                    "",
                ]
            )
        elif equipment.type.value == "VAV":
            lines.extend(
                [
                    f"{equipment.id} shall maintain zone temperature by modulating the primary damper and terminal heat as required.",
                    f"{equipment.id} shall reset airflow between minimum and cooling maximum based on zone demand.",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    f"{equipment.id} shall be commanded, monitored, and alarmed from the BAS per the assigned point schedule.",
                    "",
                ]
            )
    return "\n".join(lines)


def _render_demo_manual(project: Project) -> str:
    """Create a synthetic O&M style reference document."""
    lines = [
        f"# {project.metadata.name} Simulated O&M Notes",
        "",
        "## Service Expectations",
        "Replace prefilters on pressure drop alarm or quarterly, whichever occurs first.",
        "Verify coil entering and leaving conditions during seasonal startup.",
        "Trend fan status, discharge temperature, and zone demand during occupied mode commissioning.",
        "",
        "## Controller Integration",
    ]
    for controller in project.controllers:
        lines.extend(
            [
                f"### {controller.id}",
                f"- Vendor: {controller.vendor or 'Generic'}",
                f"- Model: {controller.model or 'TBD'}",
                f"- Panel location: {controller.panel_location or 'Field verify'}",
                f"- Serves: {', '.join(controller.serves_equipment_ids) or 'General equipment'}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_demo_point_schedule(project: Project) -> str:
    """Create a synthetic point schedule source file."""
    header = [
        "Point Name",
        "Equipment ID",
        "Controller ID",
        "Point Kind",
        "Direction",
        "Units",
        "BACnet Object Type",
        "BACnet Instance",
        "Source",
        "Source Reference",
        "Description",
    ]
    lines = [",".join(header)]
    for point in project.points:
        lines.append(
            ",".join(
                [
                    point.name,
                    point.equipment_id or "",
                    point.controller_id or "",
                    point.kind.value,
                    point.direction.value,
                    point.units or "",
                    point.bacnet_object_type or "",
                    str(point.bacnet_instance or ""),
                    point.source.value,
                    point.source_reference or "",
                    (point.description or "").replace(",", ";"),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _attach_demo_source_documents(
    project: Project,
    project_id: str,
    examples_dir: Path,
    *,
    generated_documents_dir: Path | None = None,
) -> None:
    """Attach realistic demo source documents so the seeded project resembles a station package."""
    equipment_path = examples_dir / "equipment_schedule.csv"
    points_path = examples_dir / "point_list.csv"
    controllers_path = examples_dir / "controller_schedule.csv"
    document_dir = generated_documents_dir or (examples_dir / "demo_documents")

    if equipment_path.exists():
        _upsert_source_document(
            project,
            document_id=f"{project_id}_equipment",
            name=equipment_path.name,
            document_type="equipment_schedule",
            path=equipment_path,
        )
    if points_path.exists():
        _upsert_source_document(
            project,
            document_id=f"{project_id}_points",
            name=points_path.name,
            document_type="point_list",
            path=points_path,
        )
    if controllers_path.exists():
        _upsert_source_document(
            project,
            document_id=f"{project_id}_controllers",
            name=controllers_path.name,
            document_type="controller_schedule",
            path=controllers_path,
        )

    generated_documents = [
        (
            f"{project_id}_submittal",
            f"{project_id}_mechanical_submittal.md",
            "submittal",
            _render_demo_submittal(project),
        ),
        (
            f"{project_id}_sequence",
            f"{project_id}_sequence_of_operations.md",
            "sequence",
            _render_demo_sequence(project),
        ),
        (
            f"{project_id}_manual",
            f"{project_id}_om_manual.md",
            "manual",
            _render_demo_manual(project),
        ),
        (
            f"{project_id}_point_schedule",
            f"{project_id}_simulated_point_schedule.csv",
            "point_schedule",
            _render_demo_point_schedule(project),
        ),
    ]
    for document_id, file_name, document_type, content in generated_documents:
        path = _write_demo_document(document_dir / file_name, content)
        _upsert_source_document(
            project,
            document_id=document_id,
            name=file_name,
            document_type=document_type,
            path=path,
            version="simulated-1",
        )

    fake_station_dir = examples_dir / "fake_station"
    fake_station_files = [
        ("controller_runtime", "controller_runtime.csv", "station_runtime"),
        ("point_snapshot", "station_point_snapshot.csv", "station_snapshot"),
        ("trends", "station_trends.csv", "trend_log"),
        ("alarms", "station_alarms.csv", "alarm_log"),
    ]
    for suffix, file_name, document_type in fake_station_files:
        path = fake_station_dir / file_name
        if not path.exists():
            continue
        _upsert_source_document(
            project,
            document_id=f"{project_id}_{suffix}",
            name=file_name,
            document_type=document_type,
            path=path,
            version="simulated-1",
        )


def create_demo_project(
    project_id: str,
    project_name: str,
    examples_dir: Path,
    *,
    generated_documents_dir: Path | None = None,
) -> Project:
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

    _attach_demo_source_documents(
        project,
        project_id,
        examples_dir,
        generated_documents_dir=generated_documents_dir,
    )
    return project


def demo_generated_documents_dir(projects_repo, project_id: str, examples_dir: Path) -> Path:
    """Return the writable directory for generated demo source documents."""
    project_dir = getattr(projects_repo, "project_dir", None)
    if isinstance(project_dir, Path):
        return project_dir / project_id / "source_documents"
    return examples_dir / "demo_documents"


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
    if project_output_dir.exists():
        shutil.rmtree(project_output_dir)
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
    project = create_demo_project(
        project_id,
        project_name,
        examples_dir,
        generated_documents_dir=demo_generated_documents_dir(projects_repo, project_id, examples_dir),
    )
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
