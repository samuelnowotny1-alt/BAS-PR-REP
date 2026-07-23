"""BAS Assistant Web UI - FastAPI Application."""

import csv
import json
import logging
import os
import re
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Optional, List
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pydantic import ValidationError
from sqlalchemy import select

from bas_assistant.auth import get_current_user, require_route_permission
from bas_assistant.core import build_container
from bas_assistant.database import DocumentRecord, ProjectRecord
from bas_assistant.emulation import BasEmulationLab, ReadOnlyPointError, WeatherWriteRequest
from bas_assistant.models import (
    Project, ProjectMetadata, Equipment, EquipmentType, Point, PointKind,
    PointDirection, PointSource, Controller, Protocol, UnitSystem,
    ApprovalReviewDecision, GapReviewDecision, MappingReviewDecision, ReviewAssumptionRecord,
    ControllerNetworkAddress, ControllerIOCapacity, StationConnectionConfig,
    StationSyncProtocol, default_isometric_asset_library
)
from bas_assistant.models.equipment import EquipmentTemplateRef
from bas_assistant.importers import CSVImporter, create_sample_csvs
from bas_assistant.generators import (
    generate_checkout_sheets,
    generate_graphics,
    generate_logic,
    generate_reports,
)
from bas_assistant.generators.graphics import GraphicsGenerator
from bas_assistant.validation import ValidationEngine
from bas_assistant.exporters import (
    BACnetExporter,
    HoneywellExporter,
    JCIExporter,
    NiagaraExporter,
    SiemensExporter,
    TridiumExporter,
)
from bas_assistant.reasoning import (
    analyze_gaps, parse_sequence as parse_sequence_text, TroubleshootingAssistant,
    TrendData, TrendPoint, AlarmEvent, IssueSeverity, IssueCategory,
    ConfidenceScorer, validate_engineering_rules, create_bas_assumptions,
    AssumptionTracker, AssumptionStatus, AssumptionCategory
)
from bas_assistant.station_sync import StationSyncService
from bas_assistant.config import get_settings
from bas_assistant.runtime import (
    build_health_report,
    configure_logging,
    ensure_runtime_directories,
    generate_demo_outputs,
    provision_demo_project,
)
from bas_assistant.services import ArtifactEntityLink
from ui.api.factory import create_application

SETTINGS = get_settings()
configure_logging(SETTINGS)
logger = logging.getLogger(__name__)
ensure_runtime_directories(SETTINGS)

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = Path(os.environ.get("BAS_STATIC_DIR", SETTINGS.static_dir))
TEMPLATES_DIR = Path(os.environ.get("BAS_TEMPLATES_DIR", SETTINGS.templates_dir))
DATA_DIR = Path(os.environ.get("BAS_DATA_DIR", SETTINGS.data_dir))
OUTPUT_DIR = Path(os.environ.get("BAS_OUTPUT_DIR", SETTINGS.output_dir))

# In-memory project store
projects: dict[str, Project] = {}
assumption_trackers: dict[str, AssumptionTracker] = {}
station_sync_passwords: dict[str, str] = {}
emulation_labs: dict[str, tuple[datetime, BasEmulationLab]] = {}


def refresh_projects_cache() -> dict[str, Project]:
    """Refresh the module-level project cache from the repository."""
    projects.clear()
    projects.update(container.projects.list_projects())
    return projects


def sync_container_runtime_hooks() -> None:
    """Attach runtime-dependent callbacks to container services."""
    container.dashboard.health_report_factory = current_health_report


@asynccontextmanager
async def lifespan_factory(_container):
    logger.info(
        "Starting BAS Assistant",
        extra={
            "environment": SETTINGS.environment,
            "data_dir": str(DATA_DIR),
            "output_dir": str(OUTPUT_DIR),
        },
    )
    load_projects_from_disk()
    logger.info("Loaded %s projects into memory", len(projects))
    
    # Seed Codex demo project on first run (when no projects exist)
    try:
        from bas_assistant.runtime import seed_codex_demo_project
        seed_codex_demo_project(container.projects, OUTPUT_DIR, logger)
        seeded_project = container.projects.get("codex-test-project")
        if seeded_project is not None:
            register_persisted_generated_outputs(seeded_project)
        refresh_projects_cache()
    except Exception:
        logger.exception("Failed to seed Codex demo project")
    
    yield
    logger.info("Shutting down BAS Assistant")


# FastAPI app
app, container = create_application(settings=SETTINGS, lifespan_factory=lifespan_factory)

# Static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# Helper functions
def configure_runtime_paths(
    *,
    data_dir: Path | None = None,
    output_dir: Path | None = None,
    uploads_dir: Path | None = None,
    database_url: str | None = None,
) -> None:
    """Reconfigure runtime storage for tests and alternate deployments."""
    global DATA_DIR, OUTPUT_DIR, container

    DATA_DIR = data_dir or DATA_DIR
    OUTPUT_DIR = output_dir or OUTPUT_DIR
    updated_settings = SETTINGS.model_copy(
        update={
            "data_dir": DATA_DIR,
            "output_dir": OUTPUT_DIR,
            "uploads_dir": uploads_dir or SETTINGS.uploads_dir,
            "database_url": database_url or SETTINGS.database_url,
        }
    )
    ensure_runtime_directories(updated_settings)
    container = build_container(updated_settings)
    app.state.container = container
    sync_container_runtime_hooks()
    refresh_projects_cache()


def get_project(project_id: str) -> Project:
    project = container.projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    projects[project_id] = project
    return project


def get_emulation_lab(project_id: str) -> BasEmulationLab:
    project = get_project(project_id)
    cached = emulation_labs.get(project_id)
    updated_at = project.metadata.updated_at
    if cached is None or cached[0] != updated_at:
        cached_lab = BasEmulationLab(project=project)
        emulation_labs[project_id] = (updated_at, cached_lab)
        return cached_lab
    return cached[1]


def build_unique_project_id(base_project_id: str) -> str:
    """Create a unique project ID by appending a numeric suffix when needed."""
    candidate = base_project_id
    counter = 2
    while container.projects.get(candidate) is not None:
        candidate = f"{base_project_id}-{counter}"
        counter += 1
    return candidate


def duplicate_project_snapshot(
    source_project_id: str,
    *,
    new_name: str = "",
    new_project_id: str = "",
) -> Project:
    """Duplicate a project, its structured data, and generated outputs."""
    source_project = get_project(source_project_id)
    duplicate_name = new_name.strip() or f"{source_project.metadata.name} - Copy"
    requested_project_id = new_project_id.strip()
    normalized_project_id = re.sub(r"[^a-z0-9]+", "-", requested_project_id.lower()).strip("-")
    if not normalized_project_id:
        normalized_project_id = f"{source_project.metadata.project_id}-copy"
    duplicate_project_id = build_unique_project_id(normalized_project_id)

    duplicate = source_project.model_copy(deep=True)
    duplicate.metadata.project_id = duplicate_project_id
    duplicate.metadata.name = duplicate_name
    duplicate.source_documents = []
    duplicate.update_timestamp()
    save_project(duplicate)

    source_output_dir = OUTPUT_DIR / source_project_id
    duplicate_output_dir = OUTPUT_DIR / duplicate_project_id
    if source_output_dir.exists():
        shutil.copytree(source_output_dir, duplicate_output_dir, dirs_exist_ok=True)

    register_persisted_generated_outputs(duplicate)
    record_project_ledger_event(
        project_id=duplicate_project_id,
        event_type="project.duplicated",
        summary=f"Project duplicated from {source_project_id}",
        entity_type="project",
        entity_key=duplicate_project_id,
        payload={
            "source_project_id": source_project_id,
            "project_id": duplicate_project_id,
            "name": duplicate_name,
        },
    )
    return duplicate


def save_project(project: Project) -> None:
    project.update_timestamp()
    container.projects.save(project)
    projects[project.metadata.project_id] = project


def record_project_ledger_event(
    *,
    project_id: str | None,
    event_type: str,
    summary: str,
    entity_type: str | None = None,
    entity_key: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    """Persist a project-scoped ledger event."""
    container.ledger.record_event(
        event_type=event_type,
        summary=summary,
        project_id=project_id,
        entity_type=entity_type,
        entity_key=entity_key,
        payload=payload or {},
    )


def station_connection_ledger_payload(config: StationConnectionConfig, *, password_updated: bool = False) -> dict[str, object]:
    """Serialize station connection state for the ledger without sensitive secrets."""
    return {
        "enabled": config.enabled,
        "target": config.target.value if hasattr(config.target, "value") else str(config.target),
        "protocol": config.protocol.value if hasattr(config.protocol, "value") else str(config.protocol),
        "host": config.host or "",
        "port": config.port,
        "use_tls": config.use_tls,
        "verify_tls": config.verify_tls,
        "station_name": config.station_name or "",
        "username": config.username or "",
        "obix_path": config.obix_path,
        "timeout_seconds": config.timeout_seconds,
        "last_test_status": config.last_test_status or "",
        "last_test_message": config.last_test_message or "",
        "password_updated": password_updated,
    }


def assignment_ledger_payload(assignments: list[tuple[int, str]]) -> list[dict[str, object]]:
    """Normalize membership assignments for ledger storage."""
    return [
        {
            "user_id": user_id,
            "access_level": access_level,
        }
        for user_id, access_level in assignments
    ]


def replacement_warning_count(warnings: list[str] | None) -> int:
    """Count re-import replacement warnings emitted by the CSV importers."""
    return sum(1 for warning in (warnings or []) if "replaced existing definition during re-import" in warning.lower())


def record_import_ledger_event(
    *,
    project_id: str,
    event_type: str,
    entity_type: str,
    source_name: str,
    import_result: dict[str, object] | None = None,
    parser_result: dict[str, object] | None = None,
    artifact_diff: dict[str, list[str]] | None = None,
    upload_metadata: dict[str, object] | None = None,
) -> None:
    """Persist a semantic ledger entry for import and parse mutations."""
    import_payload = dict(import_result or {})
    parser_payload = dict(parser_result or {})
    warnings = list(import_payload.get("warnings") or parser_payload.get("warnings") or [])
    diff = artifact_diff or {"added": [], "removed": [], "unchanged": []}
    record_project_ledger_event(
        project_id=project_id,
        event_type=event_type,
        summary=f"{source_name} updated project {entity_type}",
        entity_type=entity_type,
        entity_key=source_name,
        payload={
            "source_name": source_name,
            "imported_count": int(import_payload.get("count", 0) or 0),
            "replacement_count": replacement_warning_count(warnings),
            "warning_count": len(warnings),
            "error_count": len(import_payload.get("errors") or []),
            "is_reimport": bool((upload_metadata or {}).get("is_reimport")),
            "checksum_changed": bool((upload_metadata or {}).get("checksum_changed")),
            "previous_document_id": (upload_metadata or {}).get("previous_document_id"),
            "artifact_diff": diff,
            "links_added": len(diff.get("added", [])),
            "links_removed": len(diff.get("removed", [])),
            "equipment_added": int(parser_payload.get("equipment_added", 0) or 0),
            "points_added": int(parser_payload.get("points_added", 0) or 0),
            "controllers_added": int(parser_payload.get("controllers_added", 0) or 0),
            "knowledge_status": parser_payload.get("knowledge_status") or import_payload.get("knowledge_status"),
        },
    )


def build_tabular_import_links(
    *,
    importer: CSVImporter,
    file_path: Path,
    entity_type: str,
    parser_name: str,
    source_name: str,
) -> list[ArtifactEntityLink]:
    """Create explicit links for every structured object declared in a tabular upload."""
    dataframe = importer._read_tabular_file(file_path)
    if entity_type == "equipment":
        keys = sorted(
            {
                str(row.get("Equipment ID", "")).strip()
                for _, row in dataframe.iterrows()
                if str(row.get("Equipment ID", "")).strip()
            }
        )
    elif entity_type == "point":
        keys = sorted(
            {
                str(row.get("Point Name", "")).strip()
                for _, row in dataframe.iterrows()
                if str(row.get("Point Name", "")).strip()
            }
        )
    elif entity_type == "controller":
        keys = sorted(
            {
                str(row.get("Controller ID", "")).strip()
                for _, row in dataframe.iterrows()
                if str(row.get("Controller ID", "")).strip()
            }
        )
    else:
        keys = []
    return [
        ArtifactEntityLink(
            entity_type=entity_type,
            entity_key=entity_key,
            parser_name=parser_name,
            metadata={"source_name": source_name},
        )
        for entity_key in keys
    ]


def persist_artifact_links(
    *,
    project: Project,
    stored_upload,
    links: list[ArtifactEntityLink],
    parser_name: str,
) -> dict[str, list[str]]:
    """Persist artifact links for a stored upload and return reimport diff results."""
    container.artifact_links.replace_links_for_document(
        project_id=project.metadata.project_id,
        document_id=stored_upload.document_record_id,
        upload_id=stored_upload.upload_record_id,
        parser_name=parser_name,
        links=links,
    )
    return container.artifact_links.diff_against_previous_document(
        document_id=stored_upload.document_record_id,
    )


def build_ingestion_result_envelope(
    *,
    task_type: str,
    source_name: str,
    parser_name: str,
    knowledge_result=None,
    import_result: dict[str, object] | None = None,
    parser_result: dict[str, object] | None = None,
    artifact_diff: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    """Normalize import/parser task results into one UI-friendly envelope."""
    diff = artifact_diff or {"added": [], "removed": [], "unchanged": []}
    parsed_counts = {
        "equipment": int((parser_result or {}).get("equipment_added", 0) or 0),
        "points": int((parser_result or {}).get("points_added", 0) or 0),
        "controllers": int((parser_result or {}).get("controllers_added", 0) or 0),
    }
    imported_count = int((import_result or {}).get("count", 0) or 0)
    warning_count = len((import_result or {}).get("warnings") or []) + len((parser_result or {}).get("warnings") or [])
    error_count = len((import_result or {}).get("errors") or [])
    summary_parts = [
        f"{imported_count} imported" if import_result else None,
        f"{parsed_counts['equipment']} equipment" if parsed_counts["equipment"] else None,
        f"{parsed_counts['points']} points" if parsed_counts["points"] else None,
        f"{parsed_counts['controllers']} controllers" if parsed_counts["controllers"] else None,
        f"{len(diff.get('added', []))} links added",
        f"{len(diff.get('removed', []))} links removed" if diff.get("removed") else None,
    ]
    return {
        "import_result": import_result or {},
        "parser_result": parser_result or {},
        "knowledge_status": getattr(knowledge_result, "status", None),
        "chunk_count": getattr(knowledge_result, "chunk_count", 0),
        "artifact_diff": diff,
        "parser_summary": {
            "task_type": task_type,
            "source_name": source_name,
            "parser_name": parser_name,
            "imported_count": imported_count,
            "object_counts": parsed_counts,
            "warning_count": warning_count,
            "error_count": error_count,
            "added_count": len(diff.get("added", [])),
            "removed_count": len(diff.get("removed", [])),
            "unchanged_count": len(diff.get("unchanged", [])),
            "knowledge_status": getattr(knowledge_result, "status", None),
            "chunk_count": getattr(knowledge_result, "chunk_count", 0),
            "summary_text": ", ".join(part for part in summary_parts if part) or source_name,
        },
    }


def generated_document_links_for_entities(
    *,
    entity_type: str,
    entity_keys: list[str],
    parser_name: str,
    metadata: dict[str, object],
) -> list[ArtifactEntityLink]:
    """Create generated-output links for a group of BAS objects."""
    return [
        ArtifactEntityLink(
            entity_type=entity_type,
            entity_key=entity_key,
            relationship_type="generated_output",
            parser_name=parser_name,
            metadata=dict(metadata),
        )
        for entity_key in entity_keys
        if entity_key
    ]


def register_generated_output(
    *,
    project: Project,
    file_path: Path,
    document_name: str,
    document_type: str,
    parser_name: str,
    links: list[ArtifactEntityLink],
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Register generated output files as documents and attach object links."""
    document_id = container.artifact_links.register_generated_document(
        project_id=project.metadata.project_id,
        file_path=file_path,
        document_name=document_name,
        document_type=document_type,
        metadata=metadata,
    )
    container.artifact_links.replace_links_for_document(
        project_id=project.metadata.project_id,
        document_id=document_id,
        upload_id=None,
        parser_name=parser_name,
        links=links,
    )
    return {
        "name": document_name,
        "document_type": document_type,
        "file_path": str(file_path),
    }


def register_generation_outputs(
    *,
    project: Project,
    generator_name: str,
    outputs: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Persist generated BAS outputs into the artifact lineage store."""
    documents: list[dict[str, object]] = []
    for output in outputs:
        path = output.get("path")
        if not isinstance(path, Path):
            continue
        documents.append(
            register_generated_output(
                project=project,
                file_path=path,
                document_name=str(output.get("name") or path.name),
                document_type=str(output.get("document_type") or "generated_output"),
                parser_name=generator_name,
                links=list(output.get("links") or []),
                metadata=dict(output.get("metadata") or {}),
            )
        )
    return documents


def generated_document_paths(project_id: str) -> set[str]:
    """Return already-registered generated document paths for a project."""
    with container.db.session() as session:
        project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
        if project is None:
            return set()
        rows = list(
            session.scalars(
                select(DocumentRecord.file_path).where(
                    DocumentRecord.project_id == project.id,
                    DocumentRecord.document_type.startswith("generated_"),
                )
            )
        )
    return {str(path) for path in rows if path}


def register_generation_outputs_if_missing(
    *,
    project: Project,
    generator_name: str,
    outputs: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Register generated outputs that are not yet present in the document store."""
    existing_paths = generated_document_paths(project.metadata.project_id)
    pending_outputs = [
        output
        for output in outputs
        if isinstance(output.get("path"), Path)
        and str(output["path"]) not in existing_paths
        and Path(output["path"]).exists()
    ]
    if not pending_outputs:
        return []
    return register_generation_outputs(
        project=project,
        generator_name=generator_name,
        outputs=pending_outputs,
    )


def build_checkout_output_descriptors(project: Project, result: dict[str, object]) -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = []
    markdown_paths = result.get("markdown") or []
    for path in markdown_paths:
        if isinstance(path, Path):
            equipment_id = path.stem.removeprefix("checkout_").upper()
            outputs.append(
                {
                    "path": path,
                    "name": path.name,
                    "document_type": "generated_checkout_markdown",
                    "links": generated_document_links_for_entities(
                        entity_type="equipment",
                        entity_keys=[equipment_id],
                        parser_name="checkout_generator",
                        metadata={"equipment_id": equipment_id},
                    ),
                    "metadata": {"generator": "checkout", "equipment_id": equipment_id},
                }
            )
    excel_path = result.get("excel")
    if isinstance(excel_path, Path):
        outputs.append(
            {
                "path": excel_path,
                "name": excel_path.name,
                "document_type": "generated_checkout_workbook",
                "links": generated_document_links_for_entities(
                    entity_type="equipment",
                    entity_keys=[equipment.id for equipment in project.equipment],
                    parser_name="checkout_generator",
                    metadata={"scope": "project_checkout_bundle"},
                ),
                "metadata": {"generator": "checkout"},
            }
        )
    return outputs


def build_report_output_descriptors(project: Project, result: dict[str, object]) -> list[dict[str, object]]:
    mapping = {
        "equipment_schedule": ("generated_equipment_schedule", "equipment", [equipment.id for equipment in project.equipment]),
        "point_schedule": ("generated_point_schedule", "point", [point.name for point in project.points]),
        "controller_schedule": ("generated_controller_schedule", "controller", [controller.id for controller in project.controllers]),
        "summary": ("generated_project_summary", "equipment", [equipment.id for equipment in project.equipment]),
        "validation": ("generated_validation_report", "point", [point.name for point in project.points]),
    }
    outputs: list[dict[str, object]] = []
    for key, value in result.items():
        if key not in mapping or not isinstance(value, Path):
            continue
        document_type, entity_type, entity_keys = mapping[key]
        outputs.append(
            {
                "path": value,
                "name": value.name,
                "document_type": document_type,
                "links": generated_document_links_for_entities(
                    entity_type=entity_type,
                    entity_keys=entity_keys,
                    parser_name="report_generator",
                    metadata={"report_key": key},
                ),
                "metadata": {"generator": "reports", "report_key": key},
            }
        )
    return outputs


def build_graphics_output_descriptors(project: Project, result: dict[str, object]) -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = []
    for path in result.get("json") or []:
        if isinstance(path, Path):
            equipment_id = path.stem.removeprefix("graphic_").replace("_", "-").upper()
            if project.get_equipment(equipment_id) is None:
                continue
            outputs.append(
                {
                    "path": path,
                    "name": path.name,
                    "document_type": "generated_graphic_json",
                    "links": generated_document_links_for_entities(
                        entity_type="equipment",
                        entity_keys=[equipment_id],
                        parser_name="graphics_generator",
                        metadata={"equipment_id": equipment_id, "format": "json"},
                    ),
                    "metadata": {"generator": "graphics", "equipment_id": equipment_id, "format": "json"},
                }
            )
    for path in result.get("svg") or []:
        if isinstance(path, Path):
            equipment_id = path.stem.removeprefix("graphic_").replace("_", "-").upper()
            if project.get_equipment(equipment_id) is None:
                continue
            outputs.append(
                {
                    "path": path,
                    "name": path.name,
                    "document_type": "generated_graphic_svg",
                    "links": generated_document_links_for_entities(
                        entity_type="equipment",
                        entity_keys=[equipment_id],
                        parser_name="graphics_generator",
                        metadata={"equipment_id": equipment_id, "format": "svg"},
                    ),
                    "metadata": {"generator": "graphics", "equipment_id": equipment_id, "format": "svg"},
                }
            )
    niagara_path = result.get("niagara")
    if isinstance(niagara_path, Path):
        outputs.append(
            {
                "path": niagara_path,
                "name": niagara_path.name,
                "document_type": "generated_graphics_niagara",
                "links": generated_document_links_for_entities(
                    entity_type="equipment",
                    entity_keys=[equipment.id for equipment in project.equipment],
                    parser_name="graphics_generator",
                    metadata={"format": "niagara_json"},
                ),
                "metadata": {"generator": "graphics", "format": "niagara_json"},
            }
        )
    return outputs


def build_logic_output_descriptors(project: Project, result: dict[str, object]) -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = []
    for path in result.get("json") or []:
        if isinstance(path, Path):
            equipment_id = path.stem.removeprefix("logic_").replace("_", "-").upper()
            if project.get_equipment(equipment_id) is None:
                continue
            outputs.append(
                {
                    "path": path,
                    "name": path.name,
                    "document_type": "generated_logic_json",
                    "links": generated_document_links_for_entities(
                        entity_type="equipment",
                        entity_keys=[equipment_id],
                        parser_name="logic_generator",
                        metadata={"equipment_id": equipment_id, "format": "json"},
                    ),
                    "metadata": {"generator": "logic", "equipment_id": equipment_id, "format": "json"},
                }
            )
    for path in result.get("niagara") or []:
        if isinstance(path, Path):
            equipment_id = path.stem.replace("_", "-").upper()
            if project.get_equipment(equipment_id) is None:
                continue
            outputs.append(
                {
                    "path": path,
                    "name": path.name,
                    "document_type": "generated_logic_niagara",
                    "links": generated_document_links_for_entities(
                        entity_type="equipment",
                        entity_keys=[equipment_id],
                        parser_name="logic_generator",
                        metadata={"equipment_id": equipment_id, "format": "niagara"},
                    ),
                    "metadata": {"generator": "logic", "equipment_id": equipment_id, "format": "niagara"},
                }
            )
    return outputs


def build_export_output_descriptors(project: Project, results: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = []
    for vendor, result in results.items():
        for file_path in result.get("files") or []:
            path = Path(file_path)
            suffix = path.suffix.lower().lstrip(".") or "artifact"
            role = path.parent.name if path.parent != path.parent.parent else ""
            outputs.append(
                {
                    "path": path,
                    "name": path.name,
                    "document_type": f"generated_export_{vendor}",
                    "links": generated_document_links_for_entities(
                        entity_type="equipment",
                        entity_keys=[equipment.id for equipment in project.equipment],
                        parser_name=f"{vendor}_exporter",
                        metadata={"vendor": vendor, "format": suffix, "role": role},
                    ),
                    "metadata": {"generator": "export", "vendor": vendor, "format": suffix, "role": role},
                }
            )
    return outputs


def persisted_generated_output_descriptors(project: Project) -> list[dict[str, object]]:
    """Describe generated outputs that should be discoverable for a project."""
    project_id = project.metadata.project_id
    outputs: list[dict[str, object]] = []

    checkout_dir = OUTPUT_DIR / project_id / "checkout"
    checkout_result = {
        "markdown": sorted((checkout_dir / "checkout_md").glob("*.md")) if (checkout_dir / "checkout_md").exists() else [],
        "excel": checkout_dir / "checkout_sheets.xlsx",
    }
    outputs.extend(build_checkout_output_descriptors(project, checkout_result))

    reports_dir = OUTPUT_DIR / project_id / "reports"
    report_result = {
        "summary": reports_dir / "00_Project_Summary.md",
        "equipment_schedule": reports_dir / "01_Equipment_Schedule.xlsx",
        "point_schedule": reports_dir / "02_Point_Schedule.xlsx",
        "controller_schedule": reports_dir / "03_Controller_Schedule.xlsx",
        "validation": reports_dir / "04_Validation_Report.md",
    }
    outputs.extend(build_report_output_descriptors(project, report_result))

    graphics_result = load_generated_graphics_result(project)
    if graphics_result is not None:
        outputs.extend(build_graphics_output_descriptors(project, graphics_result))

    logic_dir = OUTPUT_DIR / project_id / "logic"
    logic_result = {
        "json": sorted((logic_dir / "logic_json").glob("*.json")) if (logic_dir / "logic_json").exists() else [],
        "niagara": sorted((logic_dir / "logic_niagara").glob("*.json")) if (logic_dir / "logic_niagara").exists() else [],
    }
    outputs.extend(build_logic_output_descriptors(project, logic_result))

    export_dir = OUTPUT_DIR / project_id / "exports"
    export_result = {
        vendor: {
            "files": [str(path) for path in sorted((export_dir / vendor).rglob("*")) if path.is_file()],
        }
        for vendor in ("niagara", "bacnet", "tridium", "jci", "siemens", "honeywell")
        if (export_dir / vendor).exists()
    }
    outputs.extend(build_export_output_descriptors(project, export_result))
    return outputs


def register_persisted_generated_outputs(project: Project) -> list[dict[str, object]]:
    """Backfill generated artifact files into the project document library."""
    generator_names = {
        "generated_checkout_markdown": "checkout_generator",
        "generated_checkout_workbook": "checkout_generator",
        "generated_equipment_schedule": "report_generator",
        "generated_point_schedule": "report_generator",
        "generated_controller_schedule": "report_generator",
        "generated_project_summary": "report_generator",
        "generated_validation_report": "report_generator",
        "generated_graphic_json": "graphics_generator",
        "generated_graphic_svg": "graphics_generator",
        "generated_graphics_niagara": "graphics_generator",
        "generated_logic_json": "logic_generator",
        "generated_logic_niagara": "logic_generator",
    }
    generated_documents: list[dict[str, object]] = []
    grouped_outputs: dict[str, list[dict[str, object]]] = {}
    for output in persisted_generated_output_descriptors(project):
        document_type = str(output.get("document_type") or "")
        generator_name = generator_names.get(document_type)
        if generator_name is None and document_type.startswith("generated_export_"):
            generator_name = "export_generator"
        if generator_name is None:
            continue
        grouped_outputs.setdefault(generator_name, []).append(output)

    for generator_name, outputs in grouped_outputs.items():
        generated_documents.extend(
            register_generation_outputs_if_missing(
                project=project,
                generator_name=generator_name,
                outputs=outputs,
            )
        )
    return generated_documents


def _utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _format_generated_output_names(names: list[str], *, limit: int = 3) -> str:
    visible = [name for name in names if name][:limit]
    if not visible:
        return ""
    if len(names) <= limit:
        return ", ".join(visible)
    return f"{', '.join(visible)} +{len(names) - limit} more"


def build_generated_output_review(project: Project) -> dict[str, object]:
    """Summarize generated artifact drift, missing files, and registration gaps."""
    project_id = project.metadata.project_id
    documents_view = container.project_queries.documents_view(project_id, mode="generated") or {"documents": [], "filtered_count": 0}
    generated_url, generated_label = generated_output_review_target(project_id)
    documents = list(documents_view.get("documents") or [])
    expected_outputs = persisted_generated_output_descriptors(project)
    expected_paths = {
        str(path): descriptor
        for descriptor in expected_outputs
        if isinstance((path := descriptor.get("path")), Path)
    }
    registered_paths = {
        str(document.get("file_path") or ""): document
        for document in documents
        if document.get("file_path")
    }
    findings: list[dict[str, object]] = []

    missing_registered_docs = [
        document for document in documents
        if not document.get("file_path") or not Path(str(document.get("file_path"))).exists()
    ]
    if missing_registered_docs:
        missing_names = [str(document.get("name") or "") for document in missing_registered_docs]
        findings.append(
            {
                "severity": "error",
                "title": "Registered generated documents are missing on disk",
                "detail": f"{len(missing_registered_docs)} generated records point to files that no longer exist: {_format_generated_output_names(missing_names)}.",
                "action_url": generated_url,
                "action_label": generated_label,
            }
        )

    unregistered_paths = [path for path in expected_paths if Path(path).exists() and path not in registered_paths]
    if unregistered_paths:
        unregistered_names = [Path(path).name for path in unregistered_paths]
        findings.append(
            {
                "severity": "warning",
                "title": "Generated files exist but are not registered in the library",
                "detail": f"{len(unregistered_paths)} output files are on disk but missing from Document Library: {_format_generated_output_names(unregistered_names)}.",
                "action_url": generated_url,
                "action_label": generated_label,
            }
        )

    project_updated_at = _utc_datetime(project.metadata.updated_at)
    latest_generated_at = max(
        (datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc) for path in expected_paths if Path(path).exists()),
        default=None,
    )
    if project_updated_at and latest_generated_at and project_updated_at > latest_generated_at:
        findings.append(
            {
                "severity": "warning",
                "title": "Generated outputs look stale against the current project data",
                "detail": (
                    f"Project data was updated at {project_updated_at.isoformat()} but the newest generated artifact is from "
                    f"{latest_generated_at.isoformat()}."
                ),
                "action_url": generated_url,
                "action_label": generated_label,
            }
        )

    if not documents and any(Path(path).exists() for path in expected_paths):
        findings.append(
            {
                "severity": "warning",
                "title": "Generated outputs are present but the library view is empty",
                "detail": "Output files exist on disk, but no generated documents are currently visible in the project library.",
                "action_url": generated_url,
                "action_label": generated_label,
            }
        )

    error_count = sum(1 for finding in findings if finding["severity"] == "error")
    warning_count = sum(1 for finding in findings if finding["severity"] == "warning")
    status = "blocked" if error_count else ("caution" if warning_count else "ready")
    return {
        "status": status,
        "count": len(findings),
        "error_count": error_count,
        "warning_count": warning_count,
        "documents_count": int(documents_view.get("filtered_count", 0) or 0),
        "findings": findings,
        "expected_count": len(expected_paths),
        "latest_generated_at": latest_generated_at,
        "project_updated_at": project_updated_at,
        "url": generated_url,
        "action_label": generated_label,
    }


def get_assumption_tracker(project_id: str) -> AssumptionTracker:
    project = get_project(project_id)
    tracker = assumption_trackers.get(project_id)
    if tracker is None:
        tracker = AssumptionTracker(project_id)
        tracker.create_set("design_basis", "Design Basis Assumptions")
        _load_tracker_from_project_review_state(project, tracker)
        assumption_trackers[project_id] = tracker
    return tracker


def _load_tracker_from_project_review_state(project: Project, tracker: AssumptionTracker) -> None:
    tracker.assumption_sets.clear()
    tracker.create_set("design_basis", "Design Basis Assumptions")
    tracker._counter = 0
    assumption_set = tracker.assumption_sets["design_basis"]
    highest_counter = 0
    for record in project.review_state.assumptions:
        assumption = tracker.add_assumption(
            category=AssumptionCategory(record.category),
            title=record.title,
            description=record.description,
            rationale=record.rationale,
            source=record.source,
            related_objects=list(record.related_objects),
            dependencies=list(record.dependencies),
            impacts=list(record.impacts),
            verification_method=record.verification_method,
            set_name="design_basis",
        )
        assumption.assumption_id = record.assumption_id
        assumption.status = AssumptionStatus(record.status)
        assumption.created_at = record.created_at
        assumption.verified_at = record.verified_at
        assumption.verified_by = record.verified_by
        assumption.verification_evidence = record.verification_evidence
        assumption.notes = record.notes
        if assumption_set.assumptions:
            assumption_set.assumptions[-1] = assumption
        suffix = record.assumption_id.rsplit("-", 1)[-1]
        if suffix.isdigit():
            highest_counter = max(highest_counter, int(suffix))
    tracker._counter = highest_counter


def sync_assumptions_to_project(project: Project, tracker: AssumptionTracker) -> None:
    assumption_set = tracker.assumption_sets.get("design_basis")
    assumptions = [] if assumption_set is None else assumption_set.assumptions
    project.review_state.assumptions = [
        ReviewAssumptionRecord(
            assumption_id=assumption.assumption_id,
            category=assumption.category.value,
            title=assumption.title,
            description=assumption.description,
            rationale=assumption.rationale,
            status=assumption.status.value,
            source=assumption.source,
            created_at=assumption.created_at,
            verified_at=assumption.verified_at,
            verified_by=assumption.verified_by,
            related_objects=list(assumption.related_objects),
            dependencies=list(assumption.dependencies),
            impacts=list(assumption.impacts),
            verification_method=assumption.verification_method,
            verification_evidence=assumption.verification_evidence,
            notes=assumption.notes,
        )
        for assumption in assumptions
    ]
    save_project(project)


def record_gap_resolution(
    project: Project,
    *,
    gap_id: str,
    status: str = "resolved",
    resolution_notes: str = "",
    decided_by: str | None = None,
) -> None:
    decisions = [decision for decision in project.review_state.gap_decisions if decision.gap_id != gap_id]
    decisions.append(
        GapReviewDecision(
            gap_id=gap_id,
            status=status,
            resolution_notes=resolution_notes,
            decided_by=decided_by,
        )
    )
    project.review_state.gap_decisions = decisions
    save_project(project)
    record_project_ledger_event(
        project_id=project.metadata.project_id,
        event_type="review.gap_resolved",
        summary=f"Gap {gap_id} marked {status}",
        entity_type="gap",
        entity_key=gap_id,
        payload={
            "gap_id": gap_id,
            "status": status,
            "resolution_notes": resolution_notes,
            "decided_by": decided_by or "",
        },
    )


def record_output_approval(
    project: Project,
    *,
    notes: str = "",
    approved_by: str | None = None,
) -> None:
    approvals = [
        approval
        for approval in project.review_state.approvals
        if approval.approval_key != "outputs-ready"
    ]
    approvals.append(
        ApprovalReviewDecision(
            approval_key="outputs-ready",
            status="approved",
            notes=notes,
            approved_by=approved_by,
        )
    )
    project.review_state.approvals = approvals
    save_project(project)
    record_project_ledger_event(
        project_id=project.metadata.project_id,
        event_type="review.output_approved",
        summary="Review outputs approved",
        entity_type="approval",
        entity_key="outputs-ready",
        payload={
            "approval_key": "outputs-ready",
            "status": "approved",
            "notes": notes,
            "approved_by": approved_by or "",
        },
    )


def upsert_mapping_decision(
    project: Project,
    *,
    mapping_key: str,
    mapped_to: str,
    notes: str = "",
    decided_by: str | None = None,
) -> None:
    decisions = [
        decision
        for decision in project.review_state.mapping_decisions
        if decision.mapping_key != mapping_key
    ]
    decisions.append(
        MappingReviewDecision(
            mapping_key=mapping_key,
            mapped_to=mapped_to,
            status="accepted",
            notes=notes,
            decided_by=decided_by,
        )
    )
    project.review_state.mapping_decisions = decisions
    save_project(project)
    record_project_ledger_event(
        project_id=project.metadata.project_id,
        event_type="review.mapping_saved",
        summary=f"Mapping saved for {mapping_key}",
        entity_type="mapping",
        entity_key=mapping_key,
        payload={
            "mapping_key": mapping_key,
            "mapped_to": mapped_to,
            "notes": notes,
            "decided_by": decided_by or "",
        },
    )


def mapping_candidates_for_project(project: Project) -> list[dict[str, object]]:
    existing_decisions = {decision.mapping_key: decision for decision in project.review_state.mapping_decisions}
    candidates: list[dict[str, object]] = []

    for equipment in project.equipment:
        controller_candidates = sorted(
            {
                controller.id
                for controller in project.controllers
                if equipment.id in controller.serves_equipment_ids
                or any(
                    point_name == owned_point or owned_point.startswith(f"{equipment.id} ")
                    for owned_point in controller.owned_point_names
                    for point_name in ([owned_point] if owned_point else [])
                )
            }
        )
        mapping_key = f"equipment-controller:{equipment.id}"
        decision = existing_decisions.get(mapping_key)
        if (
            decision is not None
            or (not equipment.controller_id and controller_candidates)
            or len(controller_candidates) > 1
            or (
                equipment.controller_id is not None
                and controller_candidates
                and equipment.controller_id not in controller_candidates
            )
        ):
            candidates.append(
                {
                    "mapping_key": mapping_key,
                    "subject_type": "equipment_controller",
                    "subject_label": equipment.id,
                    "current_value": equipment.controller_id,
                    "resolved_value": project.effective_equipment_controller_id(equipment),
                    "candidate_values": controller_candidates,
                    "recommended_value": controller_candidates[0] if len(controller_candidates) == 1 else None,
                    "notes": None if decision is None else decision.notes,
                    "status": None if decision is None else decision.status,
                    "reason": "Controller candidates derived from served-equipment and owned-point declarations.",
                }
            )

    for point in project.points:
        equipment_candidates = sorted(
            {
                equipment.id
                for equipment in project.equipment
                if point.name == equipment.id or point.name.startswith(f"{equipment.id} ")
            }
        )
        controller_candidates = sorted(
            {
                candidate
                for candidate in (
                    project.get_equipment(point.equipment_id).controller_id if project.get_equipment(point.equipment_id) else None,
                    *[
                        controller.id
                        for controller in project.controllers
                        if point.name in controller.owned_point_names
                        or point.equipment_id in controller.serves_equipment_ids
                    ],
                )
                if candidate
            }
        )

        point_equipment_key = f"point-equipment:{point.name}"
        equipment_decision = existing_decisions.get(point_equipment_key)
        if (
            equipment_decision is not None
            or (equipment_candidates and point.equipment_id not in equipment_candidates)
            or len(equipment_candidates) > 1
        ):
            candidates.append(
                {
                    "mapping_key": point_equipment_key,
                    "subject_type": "point_equipment",
                    "subject_label": point.name,
                    "current_value": point.equipment_id,
                    "resolved_value": project.effective_point_equipment_id(point),
                    "candidate_values": equipment_candidates,
                    "recommended_value": equipment_candidates[0] if len(equipment_candidates) == 1 else None,
                    "notes": None if equipment_decision is None else equipment_decision.notes,
                    "status": None if equipment_decision is None else equipment_decision.status,
                    "reason": "Equipment candidates derived from point-name prefixes.",
                }
            )

        point_controller_key = f"point-controller:{point.name}"
        controller_decision = existing_decisions.get(point_controller_key)
        if (
            controller_decision is not None
            or (not point.controller_id and controller_candidates)
            or len(controller_candidates) > 1
            or (
                point.controller_id is not None
                and controller_candidates
                and point.controller_id not in controller_candidates
            )
        ):
            candidates.append(
                {
                    "mapping_key": point_controller_key,
                    "subject_type": "point_controller",
                    "subject_label": point.name,
                    "current_value": point.controller_id,
                    "resolved_value": project.effective_point_controller_id(point),
                    "candidate_values": controller_candidates,
                    "recommended_value": controller_candidates[0] if len(controller_candidates) == 1 else None,
                    "notes": None if controller_decision is None else controller_decision.notes,
                    "status": None if controller_decision is None else controller_decision.status,
                    "reason": "Controller candidates derived from the point's equipment assignment and controller ownership declarations.",
                }
            )

    return sorted(candidates, key=lambda item: (str(item["subject_type"]), str(item["subject_label"])))


def review_release_state(project: Project) -> dict[str, object]:
    gap_report = analyze_gaps(project)
    mapping_candidates = mapping_candidates_for_project(project)
    sequence_workspace = build_sequence_workspace(project)
    assumption_records = list(project.review_state.assumptions)
    unresolved_mappings = [candidate for candidate in mapping_candidates if not candidate.get("resolved_value")]
    sequence_attention = [
        review
        for review in sequence_workspace["reviews"]
        if review["status"] in {"attention", "not_indexed"}
    ]
    blocking_gaps = [
        gap
        for gap in gap_report.gaps
        if gap.severity.value in {"critical", "high"}
        and not any(
            decision.gap_id == gap.gap_id and decision.status == "resolved"
            for decision in project.review_state.gap_decisions
        )
    ]
    pending_assumptions = [
        assumption
        for assumption in assumption_records
        if assumption.status in {"pending", "deferred"}
    ]
    output_approval = next(
        (
            approval
            for approval in project.review_state.approvals
            if approval.approval_key == "outputs-ready" and approval.status == "approved"
        ),
        None,
    )
    release_ready = not blocking_gaps and not unresolved_mappings and not pending_assumptions and not sequence_attention
    checks = [
        {
            "label": "Blocking gaps resolved",
            "status": "ready" if not blocking_gaps else "attention",
            "detail": "No critical/high gaps remain unresolved." if not blocking_gaps else f"{len(blocking_gaps)} blocking gaps still unresolved.",
        },
        {
            "label": "Mappings resolved",
            "status": "ready" if not unresolved_mappings else "attention",
            "detail": "No unresolved relationship mappings remain." if not unresolved_mappings else f"{len(unresolved_mappings)} mapping decisions still need review.",
        },
        {
            "label": "Assumptions closed",
            "status": "ready" if not pending_assumptions else "attention",
            "detail": "All assumptions are verified, accepted, or invalidated." if not pending_assumptions else f"{len(pending_assumptions)} assumptions are still pending or deferred.",
        },
        {
            "label": "Sequence coverage reviewed",
            "status": "ready" if not sequence_attention else "attention",
            "detail": (
                "All sequence-reviewed equipment is covered by structured points and control-family checks."
                if not sequence_attention
                else f"{len(sequence_attention)} equipment items still have sequence coverage debt to resolve."
            ),
        },
        {
            "label": "Output approval",
            "status": "ready" if output_approval else "attention",
            "detail": output_approval.notes if output_approval and output_approval.notes else ("Outputs explicitly approved." if output_approval else "Outputs have not been approved yet."),
        },
    ]
    ready_count = sum(1 for check in checks if check["status"] == "ready")
    score_pct = int(round((ready_count / len(checks)) * 100)) if checks else 0
    return {
        "release_ready": release_ready,
        "score_pct": score_pct,
        "checks": checks,
        "blocking_gaps": blocking_gaps,
        "mapping_candidates": mapping_candidates,
        "unresolved_mappings": unresolved_mappings,
        "assumptions": assumption_records,
        "pending_assumptions": pending_assumptions,
        "sequence_workspace": sequence_workspace,
        "sequence_attention": sequence_attention,
        "output_approval": output_approval,
    }


def build_project_development_status(project: Project) -> dict[str, object]:
    engine = ValidationEngine()
    report = engine.validate(project)
    release = review_release_state(project)
    sequence_workspace = build_sequence_workspace(project)
    sequence_summary = sequence_workspace["summary"]
    readiness = build_generation_readiness(project)
    equipment_with_controller = sum(1 for equipment in project.equipment if project.effective_equipment_controller_id(equipment))
    controllers_with_addresses = sum(1 for controller in project.controllers if controller.network_addresses)
    checks = [
        {
            "label": "Validation",
            "status": "ready" if not report.has_errors else "attention",
            "detail": f"{report.summary['errors']} errors, {report.summary['warnings']} warnings",
        },
        {
            "label": "Sequence Coverage",
            "status": "ready" if not sequence_summary["attention"] and not sequence_summary["not_indexed"] else "attention",
            "detail": f"{sequence_summary['attention']} attention, {sequence_summary['not_indexed']} not indexed",
        },
        {
            "label": "Mappings",
            "status": "ready" if not release["unresolved_mappings"] else "attention",
            "detail": f"{len(release['unresolved_mappings'])} unresolved mapping decisions",
        },
        {
            "label": "Assumptions",
            "status": "ready" if not release["pending_assumptions"] else "attention",
            "detail": f"{len(release['pending_assumptions'])} pending or deferred assumptions",
        },
        {
            "label": "Delivery Outputs",
            "status": "ready" if readiness["can_generate"] else "attention",
            "detail": f"{len(readiness['blockers'])} blockers, {len(readiness['cautions'])} cautions",
        },
    ]
    ready_count = sum(1 for check in checks if check["status"] == "ready")
    score_pct = int(round((ready_count / len(checks)) * 100)) if checks else 0
    status = "ready" if ready_count == len(checks) else ("attention" if ready_count else "blocked")
    return {
        "status": status,
        "score_pct": score_pct,
        "checks": checks,
        "validation_summary": report.summary,
        "release_review": release,
        "generation_readiness": readiness,
        "sequence_summary": sequence_summary,
        "equipment_with_controller": equipment_with_controller,
        "equipment_total": len(project.equipment),
        "controllers_with_addresses": controllers_with_addresses,
        "controllers_total": len(project.controllers),
    }


def build_project_next_actions(project: Project, project_view: dict[str, object]) -> list[dict[str, str]]:
    """Return the highest-signal next actions for the project dashboard."""
    actions: list[dict[str, str]] = []
    development_status = dict(project_view.get("development_status") or {})
    engineering_status = dict(project_view.get("engineering_status") or {})
    import_activity = dict(project_view.get("import_activity") or {})
    validation_summary = dict(development_status.get("validation_summary") or {})
    generation_readiness = dict(development_status.get("generation_readiness") or {})
    sequence_summary = dict(development_status.get("sequence_summary") or {})

    if int(validation_summary.get("errors", 0) or 0) > 0:
        actions.append({
            "title": "Resolve validation errors",
            "detail": f"{validation_summary.get('errors', 0)} blocking validation errors are preventing release-ready outputs.",
            "url": f"/project/{project.metadata.project_id}/validate",
        })
    if int(sequence_summary.get("attention", 0) or 0) > 0 or int(sequence_summary.get("not_indexed", 0) or 0) > 0:
        actions.append({
            "title": "Close sequence coverage gaps",
            "detail": f"{sequence_summary.get('attention', 0)} equipment items need point coverage cleanup and {sequence_summary.get('not_indexed', 0)} are not indexed yet.",
            "url": f"/project/{project.metadata.project_id}/sequence",
        })
    if generation_readiness.get("blockers"):
        actions.append({
            "title": "Unblock generators",
            "detail": f"{len(generation_readiness.get('blockers') or [])} generator blockers remain across checkout, reports, graphics, logic, or export.",
            "url": f"/project/{project.metadata.project_id}/status",
        })
    if int(engineering_status.get("knowledge_indexed", 0) or 0) < int(engineering_status.get("knowledge_total", 0) or 0):
        actions.append({
            "title": "Finish knowledge indexing",
            "detail": f"{engineering_status.get('knowledge_total', 0) - engineering_status.get('knowledge_indexed', 0)} uploaded references are not yet indexed for search.",
            "url": f"/project/{project.metadata.project_id}/knowledge",
        })
    if int(engineering_status.get("artifact_link_count", 0) or 0) == 0:
        actions.append({
            "title": "Establish artifact lineage",
            "detail": "No artifact-to-object links are recorded yet, so provenance and reimport diffs are weak.",
            "url": f"/project/{project.metadata.project_id}/documents",
        })
    if int(import_activity.get("warning_count", 0) or 0) > 0 or int(import_activity.get("error_count", 0) or 0) > 0:
        actions.append({
            "title": "Review import and parser signals",
            "detail": f"{import_activity.get('warning_count', 0)} warnings and {import_activity.get('error_count', 0)} errors were recorded in recent ingestion tasks.",
            "url": f"/project/{project.metadata.project_id}/ingestion",
        })
    return actions[:5]


def build_validation_triage(project: Project) -> dict[str, object]:
    """Summarize validation categories and fix groups into drill-down shortcuts."""
    engine = ValidationEngine()
    report = engine.validate(project)
    findings = serialize_validation_findings(report, project.metadata.project_id)
    categories: dict[tuple[str, str], dict[str, object]] = {}
    fix_groups: dict[tuple[str, str], dict[str, object]] = {}
    for finding in findings:
        entity_type = str(finding["object_type"])
        category_key = (entity_type, str(finding["category"]))
        fix_group_key = (entity_type, str(finding["fix_group"]))
        if category_key not in categories:
            categories[category_key] = {
                "entity_type": entity_type,
                "category": finding["category"],
                "count": 0,
                "url": f"/project/{project.metadata.project_id}/{entity_type if entity_type == 'equipment' else entity_type + 's'}?validation_category={finding['category']}",
            }
        categories[category_key]["count"] += 1
        if fix_group_key not in fix_groups:
            fix_groups[fix_group_key] = {
                "entity_type": entity_type,
                "fix_group": finding["fix_group"],
                "count": 0,
                "url": f"/project/{project.metadata.project_id}/{entity_type if entity_type == 'equipment' else entity_type + 's'}?fix_group={finding['fix_group']}",
            }
        fix_groups[fix_group_key]["count"] += 1
    return {
        "categories": sorted(categories.values(), key=lambda item: (-int(item["count"]), str(item["entity_type"]), str(item["category"]))),
        "fix_groups": sorted(fix_groups.values(), key=lambda item: (-int(item["count"]), str(item["entity_type"]), str(item["fix_group"]))),
    }


def apply_validation_filters_to_rows(
    project: Project,
    *,
    entity_type: str,
    rows: list[dict[str, object]],
    validation_category: str = "",
    fix_group: str = "",
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Filter object-list rows by live validation findings."""
    normalized_category = validation_category.strip().lower()
    normalized_fix_group = fix_group.strip().lower()
    engine = ValidationEngine()
    report = engine.validate(project)
    findings = serialize_validation_findings(report, project.metadata.project_id)
    relevant = [finding for finding in findings if str(finding["object_type"]) == entity_type]
    category_options = sorted({str(finding["category"]) for finding in relevant})
    fix_group_options = sorted({str(finding["fix_group"]) for finding in relevant})
    if not normalized_category and not normalized_fix_group:
        return rows, {
            "validation_category": "",
            "fix_group": "",
            "category_options": category_options,
            "fix_group_options": fix_group_options,
            "active_count": 0,
        }
    matching_ids = {
        str(finding["object_id"])
        for finding in relevant
        if (not normalized_category or str(finding["category"]).lower() == normalized_category)
        and (not normalized_fix_group or str(finding["fix_group"]).lower() == normalized_fix_group)
    }
    row_key = "id" if entity_type != "point" else "name"
    filtered = [row for row in rows if str(row.get(row_key)) in matching_ids]
    return filtered, {
        "validation_category": normalized_category,
        "fix_group": normalized_fix_group,
        "category_options": category_options,
        "fix_group_options": fix_group_options,
        "active_count": (1 if normalized_category else 0) + (1 if normalized_fix_group else 0),
    }


def object_list_redirect_target(project_id: str, entity_type: str, filters: dict[str, str]) -> str:
    plural = entity_type if entity_type == "equipment" else f"{entity_type}s"
    query_items = [(key, value) for key, value in filters.items() if value]
    if not query_items:
        return f"/project/{project_id}/{plural}"
    query = urlencode(query_items)
    return f"/project/{project_id}/{plural}?{query}"


def available_bulk_remediation_actions(entity_type: str, project: Project) -> list[dict[str, str]]:
    actions = [{"value": "fill_missing_provenance", "label": "Fill Missing Provenance"}]
    if entity_type == "equipment":
        if len(project.controllers) == 1:
            actions.append({"value": "assign_default_controller", "label": "Assign Default Controller"})
        actions.append({"value": "fill_missing_served_area", "label": "Fill Missing Served Area"})
    if entity_type == "point":
        if project.controllers:
            actions.append({"value": "assign_default_controller", "label": "Assign Default Controller"})
    return actions


def apply_bulk_remediation(
    *,
    project: Project,
    entity_type: str,
    target_ids: list[str],
    action: str,
) -> tuple[int, str]:
    updated = 0
    action_label = action.replace("_", " ")
    if entity_type == "equipment":
        default_controller = project.controllers[0].id if len(project.controllers) == 1 else None
        for entity_id in target_ids:
            equipment = project.get_equipment(entity_id)
            if equipment is None:
                continue
            if action == "fill_missing_provenance" and not equipment.provenance.get("source_name"):
                equipment.provenance.setdefault("parser", "bulk_remediation")
                equipment.provenance["source_name"] = "bulk_remediation"
                updated += 1
            elif action == "assign_default_controller" and default_controller and not equipment.controller_id:
                equipment.controller_id = default_controller
                updated += 1
            elif action == "fill_missing_served_area" and not equipment.served_area:
                equipment.served_area = "TBD Served Area"
                updated += 1
    elif entity_type == "point":
        default_controller = project.controllers[0].id if len(project.controllers) == 1 else None
        for entity_id in target_ids:
            point = project.get_point(entity_id)
            if point is None:
                continue
            if action == "fill_missing_provenance" and not point.provenance.get("source_name"):
                point.provenance.setdefault("parser", "bulk_remediation")
                point.provenance["source_name"] = "bulk_remediation"
                updated += 1
            elif action == "assign_default_controller" and not point.controller_id:
                equipment = project.get_equipment(point.equipment_id) if point.equipment_id else None
                resolved_controller = equipment.controller_id if equipment and equipment.controller_id else default_controller
                if resolved_controller:
                    point.controller_id = resolved_controller
                    updated += 1
    elif entity_type == "controller":
        for entity_id in target_ids:
            controller = project.get_controller(entity_id)
            if controller is None:
                continue
            if action == "fill_missing_provenance" and not controller.provenance.get("source_name"):
                controller.provenance.setdefault("parser", "bulk_remediation")
                controller.provenance["source_name"] = "bulk_remediation"
                updated += 1
    if updated:
        save_project(project)
    return updated, action_label


def preview_bulk_remediation(
    *,
    project: Project,
    entity_type: str,
    target_ids: list[str],
    action: str,
) -> dict[str, object]:
    action_label = action.replace("_", " ")
    changes: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    if entity_type == "equipment":
        default_controller = project.controllers[0].id if len(project.controllers) == 1 else None
        for entity_id in target_ids:
            equipment = project.get_equipment(entity_id)
            if equipment is None:
                skipped.append({"entity_id": entity_id, "reason": "Object no longer exists"})
                continue
            field_changes: list[dict[str, str]] = []
            if action == "fill_missing_provenance":
                if not equipment.provenance.get("source_name"):
                    field_changes.append({"field": "provenance.source_name", "from": "", "to": "bulk_remediation"})
                    parser_from = str(equipment.provenance.get("parser") or "")
                    if not parser_from:
                        field_changes.append({"field": "provenance.parser", "from": "", "to": "bulk_remediation"})
                else:
                    skipped.append({"entity_id": entity_id, "reason": "Provenance already present"})
                    continue
            elif action == "assign_default_controller":
                if equipment.controller_id:
                    skipped.append({"entity_id": entity_id, "reason": "Controller already assigned"})
                    continue
                if not default_controller:
                    skipped.append({"entity_id": entity_id, "reason": "Project does not have exactly one controller"})
                    continue
                field_changes.append({"field": "controller_id", "from": "", "to": default_controller})
            elif action == "fill_missing_served_area":
                if equipment.served_area:
                    skipped.append({"entity_id": entity_id, "reason": "Served area already present"})
                    continue
                field_changes.append({"field": "served_area", "from": "", "to": "TBD Served Area"})
            if field_changes:
                changes.append({"entity_id": entity_id, "changes": field_changes})
    elif entity_type == "point":
        default_controller = project.controllers[0].id if len(project.controllers) == 1 else None
        for entity_id in target_ids:
            point = project.get_point(entity_id)
            if point is None:
                skipped.append({"entity_id": entity_id, "reason": "Object no longer exists"})
                continue
            field_changes = []
            if action == "fill_missing_provenance":
                if not point.provenance.get("source_name"):
                    field_changes.append({"field": "provenance.source_name", "from": "", "to": "bulk_remediation"})
                    parser_from = str(point.provenance.get("parser") or "")
                    if not parser_from:
                        field_changes.append({"field": "provenance.parser", "from": "", "to": "bulk_remediation"})
                else:
                    skipped.append({"entity_id": entity_id, "reason": "Provenance already present"})
                    continue
            elif action == "assign_default_controller":
                if point.controller_id:
                    skipped.append({"entity_id": entity_id, "reason": "Controller already assigned"})
                    continue
                equipment = project.get_equipment(point.equipment_id) if point.equipment_id else None
                resolved_controller = equipment.controller_id if equipment and equipment.controller_id else default_controller
                if not resolved_controller:
                    skipped.append({"entity_id": entity_id, "reason": "No deterministic controller available"})
                    continue
                field_changes.append({"field": "controller_id", "from": "", "to": resolved_controller})
            if field_changes:
                changes.append({"entity_id": entity_id, "changes": field_changes})
    elif entity_type == "controller":
        for entity_id in target_ids:
            controller = project.get_controller(entity_id)
            if controller is None:
                skipped.append({"entity_id": entity_id, "reason": "Object no longer exists"})
                continue
            if action == "fill_missing_provenance":
                if not controller.provenance.get("source_name"):
                    field_changes = [{"field": "provenance.source_name", "from": "", "to": "bulk_remediation"}]
                    parser_from = str(controller.provenance.get("parser") or "")
                    if not parser_from:
                        field_changes.append({"field": "provenance.parser", "from": "", "to": "bulk_remediation"})
                    changes.append({"entity_id": entity_id, "changes": field_changes})
                else:
                    skipped.append({"entity_id": entity_id, "reason": "Provenance already present"})
    return {
        "action": action,
        "action_label": action_label,
        "targeted_count": len(target_ids),
        "change_count": len(changes),
        "skipped_count": len(skipped),
        "changes": changes[:25],
        "skipped": skipped[:25],
    }


def build_object_list_view(
    *,
    project: Project,
    entity_type: str,
    status: str = "",
    controller_state: str = "",
    addressing_state: str = "",
    provenance_state: str = "",
    equipment_type: str = "",
    point_kind: str = "",
    protocol: str = "",
    validation_category: str = "",
    fix_group: str = "",
    remediation_count: int = 0,
    remediation_action: str = "",
    bulk_preview: dict[str, object] | None = None,
) -> dict[str, object]:
    if entity_type == "equipment":
        list_view = container.project_queries.equipment_list(
            project.metadata.project_id,
            status=status,
            controller_state=controller_state,
            provenance_state=provenance_state,
            equipment_type=equipment_type,
        )
    elif entity_type == "point":
        list_view = container.project_queries.points_list(
            project.metadata.project_id,
            status=status,
            controller_state=controller_state,
            provenance_state=provenance_state,
            point_kind=point_kind,
        )
    else:
        list_view = container.project_queries.controllers_list(
            project.metadata.project_id,
            status=status,
            addressing_state=addressing_state,
            provenance_state=provenance_state,
            protocol=protocol,
        )
    filtered_rows, validation_view = apply_validation_filters_to_rows(
        project,
        entity_type=entity_type,
        rows=list(list_view["rows"]),
        validation_category=validation_category,
        fix_group=fix_group,
    )
    list_view["rows"] = filtered_rows
    list_view["filtered_count"] = len(filtered_rows)
    list_view["validation_filters"] = validation_view
    list_view["bulk_actions"] = available_bulk_remediation_actions(entity_type, project)
    list_view["bulk_result"] = {"count": remediation_count, "action": remediation_action}
    list_view["bulk_preview"] = bulk_preview
    return list_view


def get_station_connection(project: Project) -> StationConnectionConfig:
    if project.station_connection is None:
        project.station_connection = StationConnectionConfig()
    return project.station_connection


def station_sync_service() -> StationSyncService:
    return StationSyncService()


def update_station_connection(
    project: Project,
    *,
    enabled: bool,
    protocol: str,
    host: str,
    port: int,
    use_tls: bool,
    verify_tls: bool,
    station_name: str,
    username: str,
    obix_path: str,
    timeout_seconds: int,
) -> StationConnectionConfig:
    existing = get_station_connection(project)
    project.station_connection = StationConnectionConfig(
        enabled=enabled,
        protocol=StationSyncProtocol(protocol),
        host=host.strip() or None,
        port=port,
        use_tls=use_tls,
        verify_tls=verify_tls,
        station_name=station_name.strip() or None,
        username=username.strip() or None,
        obix_path=obix_path.strip() or "/obix",
        timeout_seconds=timeout_seconds,
        last_tested_at=existing.last_tested_at,
        last_test_status=existing.last_test_status,
        last_test_message=existing.last_test_message,
    )
    return project.station_connection


def equipment_graphic_sections(equipment: Equipment) -> str:
    if equipment.template and equipment.template.parameters:
        return (equipment.template.parameters.get("graphic_sections") or "").strip()
    return ""


def equipment_graphic_parameter(equipment: Equipment, key: str) -> str:
    if equipment.template and equipment.template.parameters:
        return str(equipment.template.parameters.get(key) or "").strip()
    return ""


def equipment_graphic_duct_profile(equipment: Equipment) -> str:
    return equipment_graphic_parameter(equipment, "duct_profile")


def equipment_graphic_manual_source(equipment: Equipment) -> str:
    return equipment_graphic_parameter(equipment, "duct_source")


def equipment_graphic_manufacturer(equipment: Equipment) -> str:
    return equipment_graphic_parameter(equipment, "graphics_manufacturer")


def equipment_graphic_model_family(equipment: Equipment) -> str:
    return equipment_graphic_parameter(equipment, "graphics_model_family")


def equipment_graphic_public_reference(equipment: Equipment) -> str:
    return equipment_graphic_parameter(equipment, "public_reference")


def available_duct_profiles(equipment: Equipment) -> list[dict[str, str]]:
    if equipment.type in {EquipmentType.AHU, EquipmentType.RTU}:
        return [
            {"value": "", "label": "Auto / inferred"},
            {"value": "draw_through_horizontal", "label": "Draw-through horizontal"},
            {"value": "blow_through_horizontal", "label": "Blow-through horizontal"},
            {"value": "horizontal_left", "label": "Horizontal discharge left"},
            {"value": "horizontal_right", "label": "Horizontal discharge right"},
            {"value": "vertical_upflow", "label": "Vertical upflow"},
            {"value": "vertical_downflow", "label": "Vertical downflow"},
        ]
    return [{"value": "", "label": "Auto / inferred"}]


def equipment_graphic_section_errors(equipment: Equipment) -> list[str]:
    sections = equipment_graphic_sections(equipment)
    if not sections or equipment.type != EquipmentType.AHU:
        return []
    _, invalid = GraphicsGenerator.parse_ahu_graphic_sections(sections)
    return invalid


def equipment_graphic_presets(equipment: Equipment) -> dict[str, str]:
    if equipment.type == EquipmentType.AHU:
        return GraphicsGenerator.ahu_section_presets()
    return {}


def normalize_graphic_sections(raw_value: str) -> str:
    valid, _invalid = GraphicsGenerator.parse_ahu_graphic_sections(raw_value)
    return ",".join(valid)


def build_preview_scene_from_record(record: dict[str, object]) -> dict[str, object]:
    """Build a lightweight frontend scene payload from generated graphic asset placements."""
    equipment = record.get("equipment")
    asset_placements = list(record.get("asset_placement_details") or [])
    primary = next((placement for placement in asset_placements if str(placement.get("role") or "") == "primary_equipment"), None)
    sections = [
        placement
        for placement in asset_placements
        if str(placement.get("role") or "").startswith("section:")
    ]
    sections.sort(key=lambda item: float(item.get("x") or 0))
    return {
        "equipmentId": equipment.id if equipment is not None else "",
        "equipmentType": equipment.type.value if equipment is not None else "",
        "graphicName": str(record.get("graphic_name") or ""),
        "ductProfile": str((record.get("summary") or {}).get("duct_profile") or ""),
        "sections": list((record.get("summary") or {}).get("graphic_sections") or []),
        "primaryPlacement": {
            "x": primary.get("x"),
            "y": primary.get("y"),
            "width": primary.get("width"),
            "height": primary.get("height"),
            "metadata": primary.get("metadata") or {},
        } if primary else None,
        "sectionPlacements": [
            {
                "role": str(placement.get("role") or ""),
                "assetLabel": str(placement.get("asset_label") or ""),
                "x": placement.get("x"),
                "y": placement.get("y"),
                "width": placement.get("width"),
                "height": placement.get("height"),
                "relatedPoints": [
                    {
                        "label": str(point.get("display_label") or point.get("point_name") or ""),
                        "bindingType": str(point.get("binding_type") or ""),
                        "units": str(point.get("units") or ""),
                    }
                    for point in list(placement.get("related_points") or [])[:4]
                ],
            }
            for placement in sections
        ],
    }


def graphics_preview_pages(
    project: Project,
    graphics_result: dict[str, object] | None = None,
    *,
    detail_records: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    pages = NiagaraExporter(project).preview_pages()
    if detail_records is None and graphics_result is not None:
        detail_records = build_graphic_detail_records(project, graphics_result)
    scene_by_equipment = {
        str(record.get("equipment").id if record.get("equipment") is not None else ""): build_preview_scene_from_record(record)
        for record in (detail_records or [])
        if record.get("equipment") is not None
    }
    equipment_pages = [
        page for page in pages
        if str(page.get("slotPath", "")).startswith("/Px/Equipment/")
    ]
    enriched = equipment_pages or pages
    for page in enriched:
        equipment_id = str(page.get("slotPath", "")).split("/")[-1]
        scene = scene_by_equipment.get(equipment_id)
        if scene is not None:
            page["scene"] = scene
    return enriched


def _symbol_element_to_svg(element: dict[str, object], width: float, height: float) -> str:
    element_type = str(element.get("type", "rect"))
    stroke = str(element.get("stroke") or "none")
    stroke_width = float(element.get("stroke_width") or 1)
    fill = str(element.get("fill") or "none")

    if element_type == "rect":
        return (
            f'<rect x="{float(element["x"]) * width:.2f}" y="{float(element["y"]) * height:.2f}" '
            f'width="{float(element["width"]) * width:.2f}" height="{float(element["height"]) * height:.2f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" rx="4" />'
        )
    if element_type == "circle":
        return (
            f'<circle cx="{float(element["x"]) * width:.2f}" cy="{float(element["y"]) * height:.2f}" '
            f'r="{float(element["radius"]) * width:.2f}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{stroke_width}" />'
        )
    if element_type == "ellipse":
        return (
            f'<ellipse cx="{float(element["x"]) * width:.2f}" cy="{float(element["y"]) * height:.2f}" '
            f'rx="{(float(element["width"]) * width) / 2:.2f}" ry="{(float(element["height"]) * height) / 2:.2f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" />'
        )
    if element_type == "line":
        return (
            f'<line x1="{float(element["x1"]) * width:.2f}" y1="{float(element["y1"]) * height:.2f}" '
            f'x2="{float(element["x2"]) * width:.2f}" y2="{float(element["y2"]) * height:.2f}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}" stroke-linecap="round" />'
        )
    if element_type == "text":
        label = escape(str(element.get("text", "")).replace("{name}", "NAME"))
        font_size = float(element.get("font_size") or element.get("fontSize") or 12)
        return (
            f'<text x="{float(element["x"]) * width:.2f}" y="{float(element["y"]) * height:.2f}" '
            f'font-size="{font_size}" font-family="{escape(str(element.get("font_family") or element.get("fontFamily") or "Arial"))}" '
            'text-anchor="middle" dominant-baseline="middle" fill="#0f172a" font-weight="600">'
            f"{label}</text>"
        )
    return ""


def graphics_symbol_library() -> list[dict[str, object]]:
    library: list[dict[str, object]] = []
    for symbol_key, template in GraphicsGenerator.SYMBOLS.items():
        width = 240.0
        height = 160.0
        svg_elements = "\n".join(
            part for part in (_symbol_element_to_svg(element, width, height) for element in template["elements"]) if part
        )
        library.append(
            {
                "key": symbol_key,
                "label": symbol_key.replace("_", " ").upper(),
                "element_count": len(template["elements"]),
                "width": template.get("width"),
                "height": template.get("height"),
                "svg": (
                    f'<svg viewBox="0 0 {width:.0f} {height:.0f}" class="h-40 w-full" '
                    'xmlns="http://www.w3.org/2000/svg">'
                    '<rect width="100%" height="100%" rx="18" fill="#f8fafc" />'
                    f"{svg_elements}</svg>"
                ),
            }
        )
    return library


def graphics_isometric_library() -> list[dict[str, object]]:
    library: list[dict[str, object]] = []
    for asset in default_isometric_asset_library():
        library.append(
            {
                "key": asset.asset_id,
                "label": asset.label,
                "category": asset.category,
                "variant": asset.variant or "",
                "description": asset.description,
                "element_count": len(asset.anchor_points),
                "anchor_count": len(asset.anchor_points),
                "binding_target_count": len(asset.binding_targets),
                "width": asset.width,
                "height": asset.height,
                "equipment_types": asset.compatible_equipment_types,
                "tags": asset.tags,
                "svg": asset.preview_svg,
            }
        )
    return library


def active_graphic_detail_records(project: Project, graphics_result: dict[str, object] | None) -> list[dict[str, object]]:
    if graphics_result is None:
        return []
    active_equipment_ids = {equipment.id for equipment in project.equipment}
    return [
        record
        for record in build_graphic_detail_records(project, graphics_result)
        if record.get("equipment") is not None and str(record["equipment"].id) in active_equipment_ids
    ]


def _enrich_recent_upload_views(recent_uploads: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "filename": str(upload["filename"]),
            "category": str(upload["category"]),
            "status": str(upload["status"]),
            "created_at": upload["created_at"],
            "parser_supported": container.parsers.can_parse(Path(str(upload["stored_path"]))),
        }
        for upload in recent_uploads
    ]


def _import_page_context(project: Project, project_id: str) -> dict[str, object]:
    workspace_view = container.project_queries.import_workspace_view(project_id)
    template_downloads = build_import_template_downloads(project_id)
    mapping_review = build_mapping_review_summary(project)
    if workspace_view is None:
        return {
            "project": project,
            "recent_upload_views": [],
            "import_status_view": None,
            "import_review": build_import_review(None, project.metadata.project_id),
            "issue_taxonomy": build_issue_taxonomy(project, None),
            "inline_editors": build_import_editor_views(project),
            "template_downloads": template_downloads,
            "mapping_review": mapping_review,
        }
    return {
        "project": project,
        "recent_upload_views": _enrich_recent_upload_views(workspace_view["recent_uploads"]),
        "import_status_view": workspace_view["import_status_view"],
        "import_review": build_import_review(workspace_view["import_status_view"], project.metadata.project_id),
        "issue_taxonomy": build_issue_taxonomy(project, workspace_view["import_status_view"]),
        "inline_editors": build_import_editor_views(project),
        "template_downloads": template_downloads,
        "mapping_review": mapping_review,
    }


def build_import_review(import_status_view: dict[str, object] | None, project_id: str | None = None) -> dict[str, object]:
    """Build a calmer review summary for ingestion and parser signals."""
    remediation_by_task_type = {
        "equipment_import": "Check required schedule columns and normalize equipment IDs before re-importing.",
        "points_import": "Verify point names, equipment references, point kind, and direction fields.",
        "controllers_import": "Verify controller IDs, served-equipment references, protocols, and network addressing.",
        "artifact_ingestion": "Confirm the file format is supported and that the document contains parser-friendly content.",
    }
    label_by_task_type = {
        "equipment_import": "Equipment imports",
        "points_import": "Point imports",
        "controllers_import": "Controller imports",
        "artifact_ingestion": "Supporting documents",
    }
    empty_review = {
        "status": "clean",
        "headline": "No import or parser issues recorded",
        "detail": "This workspace has not logged any current ingestion blockers. Uploads and parser outcomes will appear here when you start importing files.",
        "task_groups": [],
        "top_messages": [],
        "has_issues": False,
        "is_empty": True,
    }
    if import_status_view is None:
        return empty_review

    tasks = list(import_status_view.get("tasks") or [])
    if not tasks:
        return empty_review

    task_groups: dict[str, dict[str, object]] = {}
    top_messages: list[dict[str, str]] = []
    for task in tasks:
        task_type = str(task.get("task_type") or "artifact_ingestion")
        group = task_groups.setdefault(
            task_type,
            {
                "task_type": task_type,
                "stream": "ingestion",
                "label": label_by_task_type.get(task_type, task_type.replace("_", " ").title()),
                "task_count": 0,
                "warning_count": 0,
                "error_count": 0,
                "latest_status": str(task.get("status") or ""),
                "latest_filename": str((task.get("outcome_summary") or {}).get("filename") or task_type),
                "remediation": remediation_by_task_type.get(task_type, "Review the task details and re-run the import after correcting the source data."),
                "target_url": import_issue_target(project_id, task_type)[0] if project_id else "",
                "target_label": import_issue_target(project_id, task_type)[1] if project_id else "",
            },
        )
        group["task_count"] = int(group["task_count"]) + 1
        group["warning_count"] = int(group["warning_count"]) + len(task.get("warning_messages") or [])
        group["error_count"] = int(group["error_count"]) + len(task.get("error_messages") or [])

        filename = str((task.get("outcome_summary") or {}).get("filename") or task_type)
        for message in list(task.get("error_messages") or [])[:2]:
            top_messages.append(
                {
                    "severity": "error",
                    "task_type": task_type,
                    "label": group["label"],
                    "filename": filename,
                    "message": str(message),
                    "remediation": str(group["remediation"]),
                    "target_url": str(group["target_url"]),
                    "target_label": str(group["target_label"]),
                }
            )
        for message in list(task.get("warning_messages") or [])[:2]:
            top_messages.append(
                {
                    "severity": "warning",
                    "task_type": task_type,
                    "label": group["label"],
                    "filename": filename,
                    "message": str(message),
                    "remediation": str(group["remediation"]),
                    "target_url": str(group["target_url"]),
                    "target_label": str(group["target_label"]),
                }
            )

    warning_count = int(import_status_view.get("warning_count", 0) or 0)
    error_count = int(import_status_view.get("error_count", 0) or 0)
    if error_count > 0:
        status = "blocked"
        headline = "Import and parser blockers need review"
        detail = f"{error_count} error signals and {warning_count} warnings were recorded across recent ingestion tasks."
    elif warning_count > 0:
        status = "attention"
        headline = "Imports completed with warnings"
        detail = f"{warning_count} warning signals were recorded across recent ingestion tasks."
    else:
        status = "clean"
        headline = "Recent imports are clean"
        detail = "The latest ingestion tasks completed without current warning or error signals."

    ordered_groups = sorted(
        task_groups.values(),
        key=lambda item: (-int(item["error_count"]), -int(item["warning_count"]), str(item["label"])),
    )
    ordered_messages = sorted(
        top_messages,
        key=lambda item: (0 if item["severity"] == "error" else 1, item["label"], item["filename"]),
    )[:6]
    return {
        "status": status,
        "headline": headline,
        "detail": detail,
        "task_groups": ordered_groups,
        "top_messages": ordered_messages,
        "has_issues": error_count > 0 or warning_count > 0,
        "is_empty": False,
    }


def import_editor_anchor(project_id: str, entity_type: str) -> str:
    """Return a direct import-editor anchor for a structured entity type."""
    normalized = entity_type.strip().lower()
    if normalized == "point":
        normalized = "points"
    elif normalized == "controller":
        normalized = "controllers"
    return f"/project/{project_id}/ingestion#{normalized}-editor-section"


def import_issue_target(project_id: str, task_type: str) -> tuple[str, str]:
    """Return the best direct fix target for an ingestion task type."""
    normalized = task_type.strip().lower()
    if normalized == "equipment_import":
        return import_editor_anchor(project_id, "equipment"), "Open Equipment Editor"
    if normalized == "points_import":
        return import_editor_anchor(project_id, "points"), "Open Point Editor"
    if normalized == "controllers_import":
        return import_editor_anchor(project_id, "controllers"), "Open Controller Editor"
    if normalized == "artifact_ingestion":
        return f"/project/{project_id}/documents?mode=uploaded", "Open Uploaded Documents"
    return f"/project/{project_id}/ingestion", "Open Import Health"


def generated_output_review_target(project_id: str) -> tuple[str, str]:
    """Return the review target for generated-output consistency checks."""
    return f"/project/{project_id}/documents?mode=generated", "Review Generated Outputs"


def timed_page_context(label: str, builder):
    start_time = time.perf_counter()
    context = builder()
    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("page_context[%s] built in %.2fms", label, duration_ms)
    return context


def _form_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _form_int(value: object) -> str:
    return "" if value is None else str(value)


def _form_float(value: object) -> str:
    return "" if value is None else str(value)


def _split_csv_values(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def build_import_template_downloads(project_id: str) -> list[dict[str, object]]:
    """Describe the importer-aligned template downloads shown on the import page."""
    return [
        {
            "template_type": "equipment",
            "label": "Equipment Schedule",
            "filename": "equipment_schedule.csv",
            "url": f"/project/{project_id}/import/templates/equipment",
            "required_columns": ["Equipment ID", "Equipment Type"],
            "optional_highlights": ["Controller ID", "Graphic Sections", "Status"],
        },
        {
            "template_type": "points",
            "label": "Point List",
            "filename": "point_list.csv",
            "url": f"/project/{project_id}/import/templates/points",
            "required_columns": ["Point Name", "Equipment ID", "Point Kind", "Direction"],
            "optional_highlights": ["Controller ID", "BACnet Object Type", "Units"],
        },
        {
            "template_type": "controllers",
            "label": "Controller Schedule",
            "filename": "controller_schedule.csv",
            "url": f"/project/{project_id}/import/templates/controllers",
            "required_columns": ["Controller ID"],
            "optional_highlights": ["Protocols", "IP Address", "Serves Equipment"],
        },
    ]


def import_template_content(template_type: str) -> tuple[str, str]:
    """Return importer-aligned CSV template content and the exported filename."""
    normalized = template_type.strip().lower()
    filename_map = {
        "equipment": "equipment_schedule.csv",
        "points": "point_list.csv",
        "controllers": "controller_schedule.csv",
    }
    filename = filename_map.get(normalized)
    if filename is None:
        raise HTTPException(status_code=404, detail="Unknown import template")

    with tempfile.TemporaryDirectory(prefix="bas-import-templates-") as temp_dir:
        output_dir = Path(temp_dir)
        create_sample_csvs(output_dir)
        return filename, (output_dir / filename).read_text(encoding="utf-8")


def build_mapping_review_summary(project: Project) -> dict[str, object]:
    """Summarize unresolved mapping work for the import workspace."""
    candidates = mapping_candidates_for_project(project)
    unresolved = [candidate for candidate in candidates if not candidate.get("resolved_value")]
    recommended = [candidate for candidate in unresolved if candidate.get("recommended_value")]
    return {
        "count": len(candidates),
        "unresolved_count": len(unresolved),
        "recommended_count": len(recommended),
        "has_work": bool(candidates),
        "needs_attention": bool(unresolved),
        "url": f"/project/{project.metadata.project_id}/mappings",
    }


INLINE_EDITOR_FIELDS: dict[str, list[dict[str, object]]] = {
    "equipment": [
        {"key": "id", "label": "Equipment ID"},
        {"key": "type", "label": "Type", "options": [item.value for item in EquipmentType]},
        {"key": "subtype", "label": "Subtype"},
        {"key": "building", "label": "Building"},
        {"key": "floor", "label": "Floor"},
        {"key": "controller_id", "label": "Controller"},
        {"key": "status", "label": "Status"},
        {"key": "notes", "label": "Notes"},
    ],
    "points": [
        {"key": "name", "label": "Point Name"},
        {"key": "equipment_id", "label": "Equipment"},
        {"key": "controller_id", "label": "Controller"},
        {"key": "kind", "label": "Kind", "options": [item.value for item in PointKind]},
        {"key": "direction", "label": "Direction", "options": [item.value for item in PointDirection]},
        {"key": "units", "label": "Units"},
        {"key": "bacnet_object_type", "label": "BACnet"},
        {"key": "description", "label": "Description"},
    ],
    "controllers": [
        {"key": "id", "label": "Controller ID"},
        {"key": "type", "label": "Type"},
        {"key": "vendor", "label": "Vendor"},
        {"key": "model", "label": "Model"},
        {"key": "protocols", "label": "Protocols"},
        {"key": "address", "label": "Primary Address"},
        {"key": "serves_equipment_ids", "label": "Serves Equipment"},
        {"key": "owned_point_names", "label": "Owned Points"},
    ],
}


INLINE_EDITOR_TITLES = {
    "equipment": "Equipment Editor",
    "points": "Point Editor",
    "controllers": "Controller Editor",
}


def build_import_editor_views(
    project: Project,
    *,
    messages: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, object]]:
    message_map = messages or {}
    return {
        "equipment": build_import_editor_view(project, "equipment", message_map.get("equipment")),
        "points": build_import_editor_view(project, "points", message_map.get("points")),
        "controllers": build_import_editor_view(project, "controllers", message_map.get("controllers")),
    }


def build_import_editor_view(
    project: Project,
    entity_type: str,
    message: dict[str, str] | None = None,
) -> dict[str, object]:
    if entity_type == "equipment":
        rows = [
            {
                "key": equipment.id,
                "values": {
                    "id": equipment.id,
                    "type": equipment.type.value,
                    "subtype": equipment.subtype or "",
                    "building": equipment.building or "",
                    "floor": equipment.floor or "",
                    "controller_id": equipment.controller_id or "",
                    "status": equipment.status,
                    "notes": equipment.notes or "",
                },
            }
            for equipment in project.equipment
        ]
    elif entity_type == "points":
        rows = [
            {
                "key": point.name,
                "values": {
                    "name": point.name,
                    "equipment_id": point.equipment_id,
                    "controller_id": point.controller_id or "",
                    "kind": point.kind.value,
                    "direction": point.direction.value,
                    "units": point.units or "",
                    "bacnet_object_type": point.bacnet_object_type or "",
                    "description": point.description or "",
                },
            }
            for point in project.points
        ]
    elif entity_type == "controllers":
        rows = [
            {
                "key": controller.id,
                "values": {
                    "id": controller.id,
                    "type": controller.type,
                    "vendor": controller.vendor or "",
                    "model": controller.model or "",
                    "protocols": ", ".join(protocol.value for protocol in controller.protocols),
                    "address": controller.network_addresses[0].address if controller.network_addresses else "",
                    "serves_equipment_ids": ", ".join(controller.serves_equipment_ids),
                    "owned_point_names": ", ".join(controller.owned_point_names),
                },
            }
            for controller in project.controllers
        ]
    else:
        raise HTTPException(status_code=404, detail="Unknown editor type")
    return {
        "entity_type": entity_type,
        "title": INLINE_EDITOR_TITLES[entity_type],
        "section_id": f"{entity_type}-editor-section",
        "save_url": f"/project/{project.metadata.project_id}/import/editor/{entity_type}/save",
        "delete_url_prefix": f"/project/{project.metadata.project_id}/import/editor/{entity_type}",
        "fields": INLINE_EDITOR_FIELDS[entity_type],
        "rows": rows,
        "message": message,
    }


def _editor_key_for_entity(entity_type: str, payload: dict[str, str]) -> str:
    key_field = "name" if entity_type == "points" else "id"
    return payload.get(key_field, "").strip()


def _find_entity_index(project: Project, entity_type: str, entity_key: str) -> int | None:
    if entity_type == "equipment":
        return next((index for index, equipment in enumerate(project.equipment) if equipment.id == entity_key), None)
    if entity_type == "points":
        return next((index for index, point in enumerate(project.points) if point.name == entity_key), None)
    if entity_type == "controllers":
        return next((index for index, controller in enumerate(project.controllers) if controller.id == entity_key), None)
    return None


def _build_equipment_from_form(form_data: dict[str, str]) -> Equipment:
    return Equipment(
        id=form_data.get("id", "").strip(),
        type=EquipmentType(form_data.get("type", "").strip()),
        subtype=form_data.get("subtype", "").strip() or None,
        building=form_data.get("building", "").strip() or None,
        floor=form_data.get("floor", "").strip() or None,
        controller_id=form_data.get("controller_id", "").strip() or None,
        status=form_data.get("status", "").strip() or "design",
        notes=form_data.get("notes", "").strip() or None,
    )


def _build_point_from_form(form_data: dict[str, str]) -> Point:
    return Point(
        name=form_data.get("name", "").strip(),
        equipment_id=form_data.get("equipment_id", "").strip(),
        controller_id=form_data.get("controller_id", "").strip() or None,
        kind=PointKind(form_data.get("kind", "").strip()),
        direction=PointDirection(form_data.get("direction", "").strip()),
        units=form_data.get("units", "").strip() or None,
        bacnet_object_type=form_data.get("bacnet_object_type", "").strip() or None,
        description=form_data.get("description", "").strip() or None,
    )


def _build_controller_from_form(form_data: dict[str, str]) -> Controller:
    protocols = [Protocol(value) for value in _split_csv_values(form_data.get("protocols", ""))]
    address = form_data.get("address", "").strip()
    network_addresses = [
        ControllerNetworkAddress(protocol=protocols[0] if protocols else Protocol.BACNET_IP, address=address)
    ] if address else []
    return Controller(
        id=form_data.get("id", "").strip(),
        type=form_data.get("type", "").strip() or "generic",
        vendor=form_data.get("vendor", "").strip() or None,
        model=form_data.get("model", "").strip() or None,
        protocols=protocols,
        network_addresses=network_addresses,
        serves_equipment_ids=_split_csv_values(form_data.get("serves_equipment_ids", "")),
        owned_point_names=_split_csv_values(form_data.get("owned_point_names", "")),
    )


def _render_import_editor_section(
    request: Request,
    project: Project,
    entity_type: str,
    *,
    message: dict[str, str] | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="partials/import_editor_section.html",
        context={
            "project": project,
            "editor": build_import_editor_view(project, entity_type, message),
        },
    )


def assumption_set_for_project(project_id: str):
    tracker = get_assumption_tracker(project_id)
    assumption_set = tracker.assumption_sets.get("design_basis")
    if assumption_set is None:
        assumption_set = tracker.create_set("design_basis", "Design Basis Assumptions")
    return tracker, assumption_set


def render_assumptions_list(request: Request, project: Project):
    tracker, assumption_set = assumption_set_for_project(project.metadata.project_id)
    return templates.TemplateResponse(
        request=request,
        name="partials/assumptions_list.html",
        context={"project": project, "tracker": tracker, "assumption_set": assumption_set},
    )


def update_equipment_graphic_sections_value(equipment: Equipment, raw_value: str) -> None:
    normalized = normalize_graphic_sections(raw_value)
    if not normalized:
        if equipment.template and equipment.template.parameters:
            equipment.template.parameters.pop("graphic_sections", None)
            if not equipment.template.parameters:
                equipment.template = None
        return

    if equipment.template is None:
        equipment.template = EquipmentTemplateRef(template_name="graphic_layout", parameters={})
    elif not equipment.template.template_name:
        equipment.template.template_name = "graphic_layout"
    equipment.template.parameters["graphic_sections"] = normalized


def update_equipment_graphic_parameter(
    equipment: Equipment,
    key: str,
    raw_value: str | object,
) -> None:
    value = raw_value.strip() if isinstance(raw_value, str) else ""
    if not value:
        if equipment.template and equipment.template.parameters:
            equipment.template.parameters.pop(key, None)
            if not equipment.template.parameters:
                equipment.template = None
        return

    if equipment.template is None:
        equipment.template = EquipmentTemplateRef(template_name="graphic_layout", parameters={})
    elif not equipment.template.template_name:
        equipment.template.template_name = "graphic_layout"
    equipment.template.parameters[key] = value


def validate_equipment_graphic_sections(equipment: Equipment, raw_value: str) -> tuple[str, list[str]]:
    if equipment.type != EquipmentType.AHU:
        return normalize_graphic_sections(raw_value), []
    valid, invalid = GraphicsGenerator.parse_ahu_graphic_sections(raw_value)
    return ",".join(valid), invalid


def load_projects_from_disk() -> None:
    try:
        refresh_projects_cache()
    except Exception:
        logger.exception("Failed to load projects from repository")


def validation_remediation_for_rule(rule_id: str, field: str) -> tuple[str, str]:
    remediation_map = {
        "NAMING-001": ("Normalize equipment IDs to BAS tag format such as `AHU-1` or `VAV-203`.", "naming"),
        "NAMING-002": ("Rename the point so it starts with the resolved equipment ID and ends with a standard point code.", "naming"),
        "NAMING-003": ("Normalize controller IDs to a stable BAS controller tag such as `MPC-1` or `VAV-201`.", "naming"),
        "COMP-001": ("Assign or map the equipment to a real controller before generation.", "controller_assignment"),
        "COMP-002": ("Attach the point to an existing equipment record or resolve the point-equipment mapping.", "equipment_linkage"),
        "COMP-003": ("Assign or map the point to an owning controller so exports and review pages can trace it.", "controller_assignment"),
        "COMP-004": ("Review whether the controller should own points yet; otherwise add the missing point ownership.", "controller_completeness"),
        "COMP-005": ("Add at least one relevant point to the equipment or confirm the equipment record is incomplete.", "equipment_completeness"),
        "COMP-006": ("Add the controller network address that matches its declared network protocol.", "networking"),
        "COMP-007": ("Map every sequence-referenced point into the structured point list for the equipment before generation.", "sequence_coverage"),
        "COMP-008": ("Keep source reference metadata on sequence-derived points so reviewers can trace them back to the sequence text.", "sequence_traceability"),
        "CONS-001": ("Align the point controller with the resolved equipment controller or update the mapping decision.", "controller_assignment"),
        "CONS-002": ("Remove stale served-equipment references or add the missing equipment objects.", "equipment_linkage"),
        "CONS-003": ("Deduplicate point names so each point is unique within the project.", "deduplication"),
        "CONS-004": ("Deduplicate equipment IDs so each equipment object is unique within the project.", "deduplication"),
        "CONS-005": ("Deduplicate controller IDs so each controller object is unique within the project.", "deduplication"),
        "CONS-006": ("Add the missing command, status, setpoint, or alarm points needed to cover the indexed sequence control intent.", "sequence_coverage"),
        "ENG-001": ("Set a valid engineering range where the minimum is less than the maximum.", "engineering_ranges"),
        "ENG-002": ("Use temperature units like `degF` or `degC` for temperature-related points.", "units"),
        "ENG-003": ("Use pressure units like `inWC`, `psi`, or `Pa` for pressure-related points.", "units"),
        "ENG-004": ("Use flow units like `CFM`, `GPM`, or `LPS` for flow-related points.", "units"),
        "PROTO-001": ("Add the BACnet object type for points that live on BACnet controllers.", "protocol_mapping"),
        "PROTO-002": ("Assign a unique BACnet instance within the controller scope.", "protocol_mapping"),
        "PROTO-003": ("Assign a unique Modbus register within the controller scope.", "protocol_mapping"),
        "PROTO-004": ("Define BACnet object type and BACnet instance together for the same point.", "protocol_mapping"),
        "PROTO-005": ("Define Modbus register and Modbus register type together for the same point.", "protocol_mapping"),
        "PROTO-006": ("Make each controller network address use one of the controller's declared protocols.", "networking"),
        "CAP-001": ("Reduce owned points or increase configured controller capacity before export.", "capacity"),
        "CAP-002": ("Correct the configured I/O totals so used points do not exceed total capacity.", "capacity"),
    }
    default_group = "general" if not field else field.replace(".", "_")
    return remediation_map.get(rule_id, ("Review the referenced object and correct the source data or mapping before generation.", default_group))


def validation_object_url(project_id: str, finding) -> str:
    object_type = str(finding.object_type)
    if object_type == "equipment":
        return f"/project/{project_id}/equipment/{finding.object_id}"
    if object_type == "point":
        return f"/project/{project_id}/points/{finding.object_id}"
    if object_type == "controller":
        return f"/project/{project_id}/controllers/{finding.object_id}"
    return f"/project/{project_id}/validate"


def validation_fix_target(project_id: str, finding, fix_group: str) -> tuple[str, str]:
    """Return the most direct fix target for a validation finding."""
    normalized_group = fix_group.strip().lower()
    if normalized_group.startswith("sequence") or normalized_group in {"provenance", "knowledge"}:
        return f"/project/{project_id}/knowledge", "Review Knowledge"
    object_type = str(finding.object_type).strip().lower()
    if object_type == "equipment":
        return import_editor_anchor(project_id, "equipment"), "Edit Equipment Row"
    if object_type == "point":
        return import_editor_anchor(project_id, "points"), "Edit Point Row"
    if object_type == "controller":
        return import_editor_anchor(project_id, "controllers"), "Edit Controller Row"
    return f"/project/{project_id}/issues", "Open Issues Center"


def validation_source_target(project_id: str, finding, fix_group: str) -> tuple[str, str]:
    """Return the best source-review target for a validation finding."""
    normalized_group = fix_group.strip().lower()
    if normalized_group.startswith("sequence") or normalized_group in {"provenance", "knowledge"}:
        return f"/project/{project_id}/documents?mode=uploaded", "Review Source Documents"
    return validation_object_url(project_id, finding), "Open Object Detail"


def serialize_validation_findings(report, project_id: str | None = None) -> list[dict[str, str]]:
    findings = []
    for finding in report.errors + report.warnings + report.infos:
        remediation, fix_group = validation_remediation_for_rule(finding.rule_id, finding.field or "")
        rule_family = finding.rule_id.split("-", 1)[0].lower()
        fix_target_url, fix_target_label = validation_fix_target(project_id, finding, fix_group) if project_id else ("", "")
        source_target_url, source_target_label = validation_source_target(project_id, finding, fix_group) if project_id else ("", "")
        findings.append(
            {
                "severity": finding.severity.value,
                "issue_stream": "validation",
                "issue_stream_label": "Validation",
                "object_type": finding.object_type,
                "object_id": finding.object_id,
                "rule_id": finding.rule_id,
                "category": finding.category.value,
                "field": finding.field or "",
                "message": finding.message,
                "title": f"{finding.rule_id} · {finding.object_id}",
                "remediation": remediation,
                "fix_group": fix_group,
                "rule_family": rule_family,
                "sequence_related": "true" if fix_group.startswith("sequence") else "false",
                "object_url": validation_object_url(project_id, finding) if project_id else "",
                "fix_target_url": fix_target_url,
                "fix_target_label": fix_target_label,
                "source_target_url": source_target_url,
                "source_target_label": source_target_label,
            }
        )
    return findings


def build_generation_readiness(project: Project) -> dict[str, object]:
    engine = ValidationEngine()
    report = engine.validate(project)
    findings = serialize_validation_findings(report, project.metadata.project_id)
    release = review_release_state(project)
    sequence_workspace = build_sequence_workspace(project)
    sequence_summary = sequence_workspace["summary"]
    generated_output_review = build_generated_output_review(project)
    blockers: list[str] = []
    cautions: list[str] = []

    if report.has_errors:
        blockers.append(f"{len(report.errors)} validation errors must be resolved before generation.")
    if release["unresolved_mappings"]:
        blockers.append(f"{len(release['unresolved_mappings'])} relationship mappings still need review.")
    if release["blocking_gaps"]:
        cautions.append(f"{len(release['blocking_gaps'])} blocking gaps are still unresolved.")
    if report.has_warnings:
        cautions.append(f"{len(report.warnings)} validation warnings remain.")
    if release["pending_assumptions"]:
        cautions.append(f"{len(release['pending_assumptions'])} assumptions are still pending or deferred.")
    if sequence_summary["attention"]:
        cautions.append(
            f"{sequence_summary['attention']} sequence-reviewed equipment items still have missing point coverage or control-family gaps."
        )
    if sequence_summary["not_indexed"]:
        cautions.append(
            f"{sequence_summary['not_indexed']} sequence-reviewed equipment items do not have indexed sequence context yet."
        )
    for generated_finding in generated_output_review["findings"]:
        if generated_finding["severity"] == "error":
            blockers.append(str(generated_finding["detail"]))
        else:
            cautions.append(str(generated_finding["detail"]))

    can_generate = not blockers
    status = "blocked" if blockers else ("caution" if cautions else "ready")
    return {
        "status": status,
        "can_generate": can_generate,
        "blockers": blockers,
        "cautions": cautions,
        "validation_summary": report.summary,
        "release_review": release,
        "validation_findings": findings,
        "sequence_summary": sequence_summary,
        "generated_output_review": generated_output_review,
    }


def build_issue_taxonomy(project: Project, import_status_view: dict[str, object] | None = None) -> list[dict[str, object]]:
    """Separate validation, ingestion, and generated-output review into distinct streams."""
    validation_report = ValidationEngine().validate(project)
    generation = build_generation_readiness(project)
    generated_review = dict(generation.get("generated_output_review") or {})
    generated_count = int(generated_review.get("documents_count", 0) or 0)
    import_warning_count = int((import_status_view or {}).get("warning_count", 0) or 0)
    import_error_count = int((import_status_view or {}).get("error_count", 0) or 0)
    generated_signal_count = int(generated_review.get("count", 0) or 0)
    generated_url, generated_label = generated_output_review_target(project.metadata.project_id)
    return [
        {
            "stream": "validation",
            "label": "Validation Issues",
            "description": "Rule-based model checks against equipment, points, controllers, and mappings.",
            "count": len(validation_report.errors) + len(validation_report.warnings) + len(validation_report.infos),
            "error_count": len(validation_report.errors),
            "warning_count": len(validation_report.warnings),
            "url": f"/project/{project.metadata.project_id}/issues",
            "action_label": "Open Issues Center",
        },
        {
            "stream": "ingestion",
            "label": "Import & Parser Signals",
            "description": "Upload, parser, and re-import problems coming from source files or unsupported formats.",
            "count": import_warning_count + import_error_count,
            "error_count": import_error_count,
            "warning_count": import_warning_count,
            "url": f"/project/{project.metadata.project_id}/ingestion",
            "action_label": "Open Import Health",
        },
        {
            "stream": "generated_output",
            "label": "Generated Output Review",
            "description": "Generated artifact drift, missing files, and library registration gaps separate from source-data validation.",
            "count": generated_signal_count,
            "error_count": int(generated_review.get("error_count", 0) or 0),
            "warning_count": int(generated_review.get("warning_count", 0) or 0),
            "secondary_count": generated_count,
            "secondary_label": "generated docs",
            "url": generated_url,
            "action_label": generated_label,
        },
    ]


def build_graphics_summaries(project: Project) -> list[dict[str, object]]:
    generator = GraphicsGenerator(project)
    generator.generate_all()
    engine = ValidationEngine()
    engine.validate(project)
    summaries: list[dict[str, object]] = []
    for graphic in generator.graphics.values():
        equipment_id = graphic.equipment_id or ""
        equipment = project.get_equipment(equipment_id) if equipment_id else None
        sequence_review = (
            engine.sequence_coverage_for_equipment(project, equipment_id)
            if equipment_id
            else {
                "status": "not_indexed",
                "missing_refs": [],
                "missing_families": [],
                "summary": "",
            }
        )
        summaries.append(
            {
                "graphic_id": graphic.graphic_id,
                "equipment_id": equipment_id,
                "graphic_type": graphic.graphic_type.value,
                "sequence_reference": equipment.sequence_ref if equipment and equipment.sequence_ref else "",
                "sequence_review_status": sequence_review.get("status", "not_indexed"),
                "sequence_missing_refs": list(sequence_review.get("missing_refs") or []),
                "sequence_missing_families": list(sequence_review.get("missing_families") or []),
                "sequence_summary": sequence_review.get("summary", ""),
                "graphic_sections": list(graphic.metadata.get("graphic_sections") or []),
            }
        )
    return summaries


def load_generated_graphics_result(project: Project) -> dict[str, object] | None:
    project_id = project.metadata.project_id
    output_dir = OUTPUT_DIR / project_id / "graphics"
    json_dir = output_dir / "graphics_json"
    svg_dir = output_dir / "graphics_svg"
    niagara_path = output_dir / "graphics_niagara.json"
    json_paths = sorted(json_dir.glob("*.json")) if json_dir.exists() else []
    svg_paths = sorted(svg_dir.glob("*.svg")) if svg_dir.exists() else []
    if not json_paths and not svg_paths and not niagara_path.exists():
        return None

    summaries_by_id = {
        str(summary.get("graphic_id") or ""): summary
        for summary in build_graphics_summaries(project)
    }
    ordered_summaries = [
        summaries_by_id.get(
            json_path.stem,
            {
                "graphic_id": json_path.stem,
                "equipment_id": "",
                "graphic_type": "",
                "sequence_reference": "",
                "sequence_review_status": "not_indexed",
                "sequence_missing_refs": [],
                "sequence_missing_families": [],
                "sequence_summary": "",
                "graphic_sections": [],
            },
        )
        for json_path in json_paths
    ]
    return {
        "json": json_paths,
        "svg": svg_paths,
        "niagara": niagara_path,
        "summaries": ordered_summaries,
    }


def build_station_delivery_readiness(
    project: Project,
    *,
    graphics_result: dict[str, object] | None = None,
) -> dict[str, object]:
    release = review_release_state(project)
    readiness = build_generation_readiness(project)
    station_connection = get_station_connection(project)
    station_plan = station_sync_service().build_plan(project, station_connection)
    effective_graphics = graphics_result if graphics_result is not None else load_generated_graphics_result(project)
    graphics_generated = bool(effective_graphics and effective_graphics.get("json"))
    checks = [
        {
            "label": "Validation clean",
            "status": "ready" if not readiness["validation_summary"]["errors"] else "attention",
            "detail": f"{readiness['validation_summary']['errors']} errors · {readiness['validation_summary']['warnings']} warnings",
        },
        {
            "label": "Release review",
            "status": "ready" if release["release_ready"] else "attention",
            "detail": "All release gates are clear." if release["release_ready"] else "Mappings, gaps, assumptions, or sequence debt still need action.",
        },
        {
            "label": "Output approval",
            "status": "ready" if release["output_approval"] else "attention",
            "detail": release["output_approval"].notes if release["output_approval"] and release["output_approval"].notes else ("Outputs approved for release." if release["output_approval"] else "Outputs have not been approved."),
        },
        {
            "label": "Graphics generated",
            "status": "ready" if graphics_generated else "attention",
            "detail": (
                f"{len(effective_graphics['json']) if effective_graphics else 0} graphics ready for review."
                if graphics_generated
                else "Generate graphics to review what will ship to the station."
            ),
        },
        {
            "label": "Station target configured",
            "status": "ready" if station_connection.enabled and bool(station_connection.host) else "attention",
            "detail": (
                f"{station_connection.protocol.value} · {station_connection.host}:{station_connection.port}"
                if station_connection.host
                else "Host and protocol still need configuration."
            ),
        },
        {
            "label": "Station probe",
            "status": "ready" if station_connection.last_test_status == "success" else "attention",
            "detail": station_connection.last_test_message or "No successful connectivity probe has been recorded yet.",
        },
    ]
    ready_count = sum(1 for check in checks if check["status"] == "ready")
    status = "ready" if ready_count == len(checks) else ("attention" if ready_count else "blocked")
    score_pct = int(round((ready_count / len(checks)) * 100)) if checks else 0
    return {
        "status": status,
        "score_pct": score_pct,
        "checks": checks,
        "ready_count": ready_count,
        "graphics_generated": graphics_generated,
        "station_connection": station_connection,
        "station_plan": station_plan,
        "release_review": release,
        "generation_readiness": readiness,
    }


def _normalize_live_point_token(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _format_live_value(value: object, units: str = "") -> str:
    if not isinstance(value, (int, float)):
        return "--"
    if units == "%":
        return f"{round(float(value), 1):g}%"
    if units:
        decimals = 2 if units in {"inWC", "psi"} else 1
        numeric = f"{float(value):.{decimals}f}".rstrip("0").rstrip(".")
        return f"{numeric} {units}"
    return f"{float(value):.1f}"


def _average_live_points(points: list[object], *tokens: str) -> float | None:
    token_set = tuple(_normalize_live_point_token(token) for token in tokens)
    values: list[float] = []
    for point in points:
        point_name = getattr(point, "point_name", "")
        point_value = getattr(point, "present_value", None)
        normalized_name = _normalize_live_point_token(str(point_name))
        if any(token in normalized_name for token in token_set) and isinstance(point_value, (int, float)):
            values.append(float(point_value))
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _live_point_status(key: str, value: float | None, *, station_alarm_count: int = 0) -> str:
    if value is None:
        return "unknown"
    if key == "outdoor_air_temp":
        return "alarm" if value < 25 or value > 100 else ("caution" if value < 35 or value > 95 else "normal")
    if key == "outdoor_air_humidity":
        return "alarm" if value > 75 else ("caution" if value > 65 else "normal")
    if key == "supply_air_temp":
        return "alarm" if value < 50 or value > 68 else ("caution" if value < 53 or value > 62 else "normal")
    if key == "return_air_temp":
        return "alarm" if value > 82 else ("caution" if value > 78 else "normal")
    if key == "mixed_air_temp":
        return "alarm" if value < 35 or value > 85 else ("caution" if value < 42 or value > 78 else "normal")
    if key == "avg_zone_temp":
        return "alarm" if value < 67 or value > 78 else ("caution" if value < 69 or value > 76 else "normal")
    if key == "supply_static":
        return "alarm" if value < 0.4 or value > 2.4 else ("caution" if value < 0.6 or value > 2.0 else "normal")
    if key in {"outside_air_damper", "cooling_valve", "heating_valve"}:
        return "alarm" if value > 95 and station_alarm_count else ("caution" if value > 85 else "normal")
    if key == "wind_mph":
        return "caution" if value > 20 else "normal"
    return "normal"


def build_project_live_conditions(project: Project, *, snapshot: object | None = None) -> dict[str, object]:
    snapshot = snapshot or get_emulation_lab(project.metadata.project_id).snapshot()
    weather = dict(snapshot.weather)
    station = dict(snapshot.station)
    points = [point for device in snapshot.devices for point in getattr(device, "points", [])]

    def analog_value(*tokens: str) -> float | None:
        token_set = tuple(_normalize_live_point_token(token) for token in tokens)
        for point in points:
            normalized_name = _normalize_live_point_token(str(getattr(point, "point_name", "")))
            point_value = getattr(point, "present_value", None)
            if any(token in normalized_name for token in token_set) and isinstance(point_value, (int, float)):
                return float(point_value)
        return None

    def percent_value(*tokens: str) -> str:
        return _format_live_value(analog_value(*tokens), "%")

    supply_air_temp = analog_value("AHU-1 SAT", "AHU-1 DAT", "SUPPLY AIR TEMP")
    return_air_temp = analog_value("AHU-1 RAT", "RETURN AIR TEMP")
    mixed_air_temp = analog_value("AHU-1 MAT", "MIXED AIR TEMP")
    zone_temp = _average_live_points(points, "ZNT", "ZONE TEMP", "SPACE TEMP")
    supply_static = analog_value("DUCT SP", "STATIC PRESSURE", "FILTER DP")
    outdoor_air_temp = weather.get("outdoor_air_temp") if isinstance(weather.get("outdoor_air_temp"), (int, float)) else None
    outdoor_air_humidity = weather.get("outdoor_air_humidity") if isinstance(weather.get("outdoor_air_humidity"), (int, float)) else None
    wind_mph = weather.get("wind_mph") if isinstance(weather.get("wind_mph"), (int, float)) else None
    cooling_valve = analog_value("CLG VALVE", "COOLING VALVE")
    heating_valve = analog_value("HTG VALVE", "HEATING VALVE")
    outside_air_damper = analog_value("OA DAMPER", "OUTSIDE AIR DAMPER")
    station_alarm_count = int(station.get("alarm_count", 0) or 0)

    return {
        "weather": weather,
        "station": station,
        "tick": int(getattr(snapshot, "tick", 0) or 0),
        "generated_at": str(getattr(snapshot, "generated_at", "") or ""),
        "outdoor_air_temp": _format_live_value(outdoor_air_temp, "degF"),
        "outdoor_air_humidity": _format_live_value(outdoor_air_humidity, "%"),
        "wind_mph": _format_live_value(wind_mph, "mph"),
        "conditions": str(weather.get("conditions") or "unknown").replace("_", " ").title(),
        "supply_air_temp": _format_live_value(supply_air_temp, "degF"),
        "return_air_temp": _format_live_value(return_air_temp, "degF"),
        "mixed_air_temp": _format_live_value(mixed_air_temp, "degF"),
        "avg_zone_temp": _format_live_value(zone_temp, "degF"),
        "supply_static": _format_live_value(supply_static, "inWC"),
        "cooling_valve": _format_live_value(cooling_valve, "%"),
        "heating_valve": _format_live_value(heating_valve, "%"),
        "outside_air_damper": _format_live_value(outside_air_damper, "%"),
        "statuses": {
            "outdoor_air_temp": _live_point_status("outdoor_air_temp", outdoor_air_temp, station_alarm_count=station_alarm_count),
            "outdoor_air_humidity": _live_point_status("outdoor_air_humidity", outdoor_air_humidity, station_alarm_count=station_alarm_count),
            "wind_mph": _live_point_status("wind_mph", wind_mph, station_alarm_count=station_alarm_count),
            "supply_air_temp": _live_point_status("supply_air_temp", supply_air_temp, station_alarm_count=station_alarm_count),
            "return_air_temp": _live_point_status("return_air_temp", return_air_temp, station_alarm_count=station_alarm_count),
            "mixed_air_temp": _live_point_status("mixed_air_temp", mixed_air_temp, station_alarm_count=station_alarm_count),
            "avg_zone_temp": _live_point_status("avg_zone_temp", zone_temp, station_alarm_count=station_alarm_count),
            "supply_static": _live_point_status("supply_static", supply_static, station_alarm_count=station_alarm_count),
            "outside_air_damper": _live_point_status("outside_air_damper", outside_air_damper, station_alarm_count=station_alarm_count),
            "cooling_valve": _live_point_status("cooling_valve", cooling_valve, station_alarm_count=station_alarm_count),
            "heating_valve": _live_point_status("heating_valve", heating_valve, station_alarm_count=station_alarm_count),
        },
    }


def build_graphic_detail_records(project: Project, graphics_result: dict[str, object]) -> list[dict[str, object]]:
    engine = ValidationEngine()
    report = engine.validate(project)
    findings = serialize_validation_findings(report, project.metadata.project_id)
    preview_pages = graphics_preview_pages(project)
    asset_library = {asset.asset_id: asset for asset in default_isometric_asset_library()}
    preview_by_equipment = {
        str(page.get("slotPath", "")).split("/")[-1]: page
        for page in preview_pages
        if str(page.get("slotPath", "")).startswith("/Px/Equipment/")
    }
    svg_paths = {path.stem: path for path in graphics_result.get("svg", [])}
    project_output_dir = OUTPUT_DIR / project.metadata.project_id
    point_lookup = {point.name: point for point in project.points}
    records: list[dict[str, object]] = []
    for index, summary in enumerate(graphics_result.get("summaries", [])):
        json_paths = graphics_result.get("json", [])
        if index >= len(json_paths):
            continue
        json_path = json_paths[index]
        graphic_name = json_path.stem
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        elements = list(payload.get("elements") or [])
        bindings = list(payload.get("bindings") or [])
        asset_placements = list((payload.get("metadata") or {}).get("asset_placements") or [])
        asset_point_relations = list((payload.get("metadata") or {}).get("asset_point_relations") or [])
        binding_point_names = sorted(
            {
                str(binding.get("point_name") or "").strip()
                for binding in bindings
                if str(binding.get("point_name") or "").strip()
            }
        )
        equipment_id = str(summary.get("equipment_id") or "")
        equipment = project.get_equipment(equipment_id) if equipment_id else None
        controller_id = project.effective_equipment_controller_id(equipment) if equipment is not None else None
        related_points = sorted(
            {
                *[point.name for point in project.points if point.equipment_id == equipment_id],
                *binding_point_names,
            }
        )
        related_ids = {equipment_id, controller_id or "", *related_points}
        related_findings = [finding for finding in findings if finding["object_id"] in related_ids]
        preview_page = preview_by_equipment.get(equipment_id)
        svg_path = svg_paths.get(graphic_name)
        json_url = f"/output/{project.metadata.project_id}/{json_path.relative_to(project_output_dir).as_posix()}"
        svg_url = (
            f"/output/{project.metadata.project_id}/{svg_path.relative_to(project_output_dir).as_posix()}"
            if svg_path is not None
            else None
        )
        binding_details = []
        for binding in bindings:
            point_name = str(binding.get("point_name") or "")
            point = point_lookup.get(point_name)
            binding_details.append(
                {
                    "point_name": point_name,
                    "display_label": str(binding.get("label") or point_name),
                    "binding_type": str(binding.get("binding_type") or ""),
                    "label": str(binding.get("label") or ""),
                    "format": str(binding.get("format") or ""),
                    "x": binding.get("x"),
                    "y": binding.get("y"),
                    "units": point.units if point is not None else "",
                    "kind": point.kind.value if point is not None else "",
                    "direction": point.direction.value if point is not None else "",
                    "equipment_id": point.equipment_id if point is not None else "",
                    "description": describe_graphic_binding(
                        point_name=point_name,
                        binding_type=str(binding.get("binding_type") or ""),
                        point=point,
                    ),
                }
            )
        element_details = [
            describe_graphic_element(element, equipment_id=equipment_id, sections=list(summary.get("graphic_sections") or []))
            for element in elements
        ]
        asset_placement_details = [
            describe_graphic_asset_placement(
                placement,
                asset_library=asset_library,
                binding_details=binding_details,
                asset_point_relations=asset_point_relations,
                point_lookup=point_lookup,
                equipment_id=equipment_id,
            )
            for placement in asset_placements
        ]
        records.append(
            {
                "graphic_name": graphic_name,
                "json_path": json_path,
                "json_url": json_url,
                "svg_path": svg_path,
                "svg_url": svg_url,
                "summary": summary,
                "equipment": equipment,
                "controller": project.get_controller(controller_id) if controller_id else None,
                "point_names": related_points,
                "binding_point_names": binding_point_names,
                "binding_details": binding_details,
                "element_details": element_details,
                "asset_placement_details": asset_placement_details,
                "asset_placement_count": len(asset_placement_details),
                "asset_point_relation_count": len(asset_point_relations),
                "element_count": len(element_details),
                "binding_count": len(binding_details),
                "layer_names": sorted({detail["layer"] for detail in element_details if detail["layer"]}),
                "navigation_targets": list(payload.get("navigation") or []),
                "payload_title": str(payload.get("name") or graphic_name),
                "payload_excerpt": json.dumps(payload, indent=2)[:3200] if payload else "",
                "validation_findings": related_findings,
                "error_count": sum(1 for finding in related_findings if finding["severity"] == "error"),
                "warning_count": sum(1 for finding in related_findings if finding["severity"] == "warning"),
                "preview_page": preview_page,
            }
    )
    return records


def describe_graphic_asset_placement(
    placement: dict[str, object],
    *,
    asset_library: dict[str, object],
    binding_details: list[dict[str, object]],
    asset_point_relations: list[dict[str, object]],
    point_lookup: dict[str, Point],
    equipment_id: str,
) -> dict[str, object]:
    asset_id = str(placement.get("asset_id") or "")
    asset = asset_library.get(asset_id)
    role = str(placement.get("role") or "assembly")
    placement_metadata = placement.get("metadata")
    if not isinstance(placement_metadata, dict):
        placement_metadata = {}

    explicit_relations = [
        relation
        for relation in asset_point_relations
        if str(relation.get("asset_id") or "") == asset_id
        and str(relation.get("asset_role") or "") == role
        and str(relation.get("equipment_id") or equipment_id) == str(placement.get("equipment_id") or equipment_id)
    ]

    related_points = []
    if explicit_relations:
        for relation in explicit_relations:
            point_name = str(relation.get("point_name") or "")
            point = point_lookup.get(point_name)
            related_points.append(
                {
                    "point_name": point_name,
                    "display_label": str(relation.get("label") or point_name),
                    "binding_type": str(relation.get("binding_type") or ""),
                    "units": point.units if point is not None else str(relation.get("units") or ""),
                    "description": describe_graphic_relation(relation),
                    "component": str(relation.get("component") or ""),
                    "target_key": str(relation.get("target_key") or ""),
                    "anchor_key": str(relation.get("anchor_key") or ""),
                    "visual_hint": str(relation.get("visual_hint") or ""),
                    "relation_kind": str(relation.get("relation_kind") or ""),
                    "relation_x": relation.get("relation_x"),
                    "relation_y": relation.get("relation_y"),
                }
            )
    else:
        related_bindings = [
            binding
            for binding in binding_details
            if binding_matches_asset_role(binding, role, equipment_id=equipment_id)
        ]
        for binding in related_bindings:
            point_name = str(binding.get("point_name") or "")
            point = point_lookup.get(point_name)
            related_points.append(
                {
                    "point_name": point_name,
                    "display_label": str(binding.get("display_label") or point_name),
                    "binding_type": str(binding.get("binding_type") or ""),
                    "units": point.units if point is not None else "",
                    "description": str(binding.get("description") or ""),
                    "component": "",
                    "target_key": "",
                    "anchor_key": "",
                    "visual_hint": "",
                    "relation_kind": "",
                    "relation_x": None,
                    "relation_y": None,
                }
            )

    target_descriptions = []
    if asset is not None:
        for target in asset.binding_targets:
            target_descriptions.append(
                {
                    "label": target.key.replace("_", " ").title(),
                    "description": target.description or target.component.replace("_", " ").title(),
                    "component": target.component,
                }
            )

    return {
        "asset_id": asset_id,
        "asset_label": asset.label if asset is not None else asset_id.replace("_", " ").title(),
        "asset_category": asset.category if asset is not None else "",
        "asset_description": asset.description if asset is not None else "Reusable equipment asset used in this graphic assembly.",
        "role": role,
        "role_label": format_graphic_asset_role(role),
        "role_description": describe_graphic_asset_role(role, metadata=placement_metadata),
        "x": placement.get("x"),
        "y": placement.get("y"),
        "width": placement.get("width"),
        "height": placement.get("height"),
        "equipment_id": str(placement.get("equipment_id") or equipment_id),
        "metadata": placement_metadata,
        "metadata_items": [
            {"label": key.replace("_", " ").title(), "value": ", ".join(value) if isinstance(value, list) else str(value)}
            for key, value in placement_metadata.items()
            if value not in ("", None, [], {})
        ],
        "target_descriptions": target_descriptions,
        "related_points": related_points,
        "relation_count": len(related_points),
    }


def format_graphic_asset_role(role: str) -> str:
    if role.startswith("section:"):
        return f"{role.split(':', 1)[1].replace('_', ' ').title()} Section"
    return role.replace("_", " ").replace(":", " ").title()


def describe_graphic_asset_role(role: str, *, metadata: dict[str, object]) -> str:
    if role == "primary_equipment":
        sections = metadata.get("sections")
        if isinstance(sections, list) and sections:
            section_text = ", ".join(str(section).replace("_", " ") for section in sections)
            return f"This is the main assembled unit shell. It organizes the graphic around these physical sections: {section_text}."
        return "This is the main assembled unit shell that defines the overall physical cabinet and airflow direction."
    if role == "internal_supply_path":
        return "This asset represents the main internal air path through the equipment so the operator can follow how supply air moves section to section."
    if role.startswith("section:"):
        section_name = role.split(":", 1)[1].replace("_", " ")
        return f"This asset is the rendered {section_name} portion of the unit and acts as the physical home for related live points."
    return "This asset is a placed physical assembly inside the generated equipment graphic."


def binding_matches_asset_role(binding: dict[str, object], role: str, *, equipment_id: str) -> bool:
    if equipment_id and str(binding.get("equipment_id") or "") not in {"", equipment_id}:
        return False

    point_name = str(binding.get("point_name") or "").lower()
    description = str(binding.get("description") or "").lower()
    binding_type = str(binding.get("binding_type") or "").lower()
    text = " ".join([point_name, description, binding_type])

    if role == "primary_equipment":
        return True
    if role == "internal_supply_path":
        return any(keyword in text for keyword in ("supply", "sat", "airflow", "cfm", "static"))

    role_key = role.split(":", 1)[1] if ":" in role else role
    keyword_map = {
        "outside_air": ("oat", "outside", "mixed", "return", "damper"),
        "mixed_air": ("mixed", "outside", "return", "damper"),
        "filter": ("filter", "dp"),
        "cooling_coil": ("cool", "chw", "clg", "valve", "lat"),
        "heating_coil": ("heat", "hw", "htg", "valve", "reheat"),
        "supply_fan": ("fan", "vfd", "proof", "speed", "static"),
        "return_fan": ("return fan", "rf", "fan"),
        "relief_fan": ("relief fan", "exhaust", "fan"),
        "discharge": ("discharge", "supply", "sat", "dat", "airflow", "cfm"),
        "terminal_box": ("damper", "reheat", "flow", "discharge", "zone"),
        "branch_takeoff": ("flow", "cfm", "branch"),
        "distribution_trunk": ("static", "supply", "flow", "cfm"),
    }
    keywords = keyword_map.get(role_key, (role_key.replace("_", " "),))
    return any(keyword in text for keyword in keywords)


def describe_graphic_relation(relation: dict[str, object]) -> str:
    component = str(relation.get("component") or "").replace("_", " ")
    relation_kind = str(relation.get("relation_kind") or "").replace("_", " ")
    visual_hint = str(relation.get("visual_hint") or "").replace("_", " ")
    target_description = str(relation.get("target_description") or "")
    target_key = str(relation.get("target_key") or "").replace("_", " ")
    anchor_key = str(relation.get("anchor_key") or "").replace("_", " ")

    parts = []
    if component:
        parts.append(f"Drives the {component} asset state.")
    if relation_kind:
        parts.append(f"Relation type: {relation_kind}.")
    if target_description:
        parts.append(target_description.rstrip(".") + ".")
    elif target_key:
        parts.append(f"Mapped to target {target_key}.")
    if anchor_key:
        parts.append(f"Anchored at {anchor_key}.")
    if visual_hint:
        parts.append(f"Visual response: {visual_hint}.")
    return " ".join(parts) if parts else "Explicitly mapped to this asset."


def describe_graphic_binding(*, point_name: str, binding_type: str, point: Point | None) -> str:
    name = point_name.lower()
    if binding_type == "value":
        if "sat" in name or "supply" in name and "temp" in name:
            return "Shows the live supply-air temperature serving this graphic."
        if "dat" in name or "discharge" in name:
            return "Shows the leaving-air temperature after the unit conditions the air."
        if "rat" in name or "return" in name and "temp" in name:
            return "Shows the return-air temperature coming back from the space."
        if "oat" in name or "outside" in name:
            return "Shows the outside-air condition feeding the sequence."
        if "humidity" in name or "hum" in name:
            return "Shows the live humidity reading used by this graphic."
        if "static" in name or "pressure" in name:
            return "Shows the pressure value the sequence is responding to."
        if "flow" in name or "cfm" in name:
            return "Shows the airflow value moving through this part of the system."
        return "Shows a live sensor value on the graphic."
    if binding_type == "setpoint":
        return "Shows the target value the control sequence is trying to maintain."
    if binding_type == "status":
        return "Shows whether this device or state is currently on, off, open, or closed."
    if binding_type == "alarm":
        return "Shows an alarm-related condition the operator should watch."
    if binding_type == "trend":
        return "Shows a recent trend history for this point."
    if binding_type == "override":
        return "Shows a point that may be manually overridden by an operator."
    if binding_type == "command":
        return "Shows a commandable point the sequence can drive."
    if point is not None:
        if point.kind.value == "sensor":
            return "Shows a live sensor reading used by the control logic."
        if point.kind.value == "setpoint":
            return "Shows a setpoint that guides sequence behavior."
        if point.kind.value == "command":
            return "Shows a command point used to change equipment state."
        if point.kind.value == "status":
            return "Shows the current operating state of the device."
    return "Shows a point connected to this graphic."


def describe_graphic_element(
    element: dict[str, object],
    *,
    equipment_id: str,
    sections: list[str],
) -> dict[str, object]:
    element_type = str(element.get("type") or "")
    layer = str(element.get("layer") or "default")
    x = element.get("x")
    y = element.get("y")
    width = element.get("width")
    height = element.get("height")
    stroke = str(element.get("stroke") or "")
    fill = str(element.get("fill") or "")
    text = str(element.get("text") or "")
    symbol_name = str(element.get("symbol_name") or "")
    role = "graphic element"
    explanation = "Supports the generated BAS graphic layout."

    if element_type == "line":
        is_horizontal = abs(float(height or 0)) <= abs(float(width or 0))
        line_location = float(y or 0)
        line_span = float(width or 0)
        if stroke in {"#1976d2", "#1565c0"}:
            role = "supply air path" if is_horizontal else "supply branch connection"
            explanation = (
                "Shows the supply-side flow path in the program graphic. "
                "This helps the operator see where conditioned air is leaving or moving through the equipment."
            )
        elif stroke in {"#ef6c00", "#e65100"}:
            role = "return or heating path" if is_horizontal else "heating branch connection"
            explanation = (
                "Shows a return-air or heating-water connection in the program graphic. "
                "It gives context for how heat or return flow is routed through the equipment."
            )
        elif stroke in {"#757575", "#333", "#546e7a", "#cbd5e1"}:
            role = "equipment divider or boundary"
            explanation = (
                "Marks a physical section break or equipment boundary so the program can separate coils, fans, filters, or duct sections visually."
            )
        elif stroke in {"#009688", "#00695c"}:
            role = "humidification or auxiliary process path"
            explanation = (
                "Indicates an auxiliary process path, typically used to show humidification or a secondary routed medium in the graphic."
            )
        elif stroke in {"#7b1fa2", "#c2185b", "#c62828"}:
            role = "special process branch"
            explanation = (
                "Highlights a special branch or alternate process stream so the operator can distinguish it from the primary duct path."
            )
        elif layer == "piping":
            role = "process connection line"
            explanation = (
                "Represents a process connection between major equipment sections. "
                "In the program this line is used to show how air, water, or another medium moves through the sequence."
            )

        if is_horizontal and line_location < 0.15:
            explanation += " This one sits near the top of the graphic, so it likely represents an entering or upstream connection."
        elif is_horizontal and line_location > 0.8:
            explanation += " This one sits near the bottom of the graphic, so it likely represents a lower return, drain, or exhaust-side connection."
        elif not is_horizontal:
            explanation += " Because it is vertical, it is likely tying one section of the graphic to another branch or coil connection."
        elif line_span < 0.12:
            explanation += " Its short span suggests it is a local connector rather than the main equipment trunk."
        else:
            explanation += " Its span suggests it is one of the main routed paths in the equipment drawing."
    elif element_type == "rect":
        role = "equipment section block"
        explanation = (
            "Defines a physical equipment section in the program graphic, such as a filter bank, coil section, fan section, or discharge segment."
        )
    elif element_type in {"circle", "ellipse"}:
        role = "rotating device or process symbol"
        explanation = (
            "Represents a symbolic device shape, commonly used for fans, pumps, or rounded process symbols in the graphic."
        )
    elif element_type == "text":
        role = "label"
        explanation = (
            "Provides operator-readable labeling so the graphic can identify equipment, sections, and process references."
        )

    if text:
        explanation += f" The label `{text}` is what the operator sees on the rendered graphic."
    elif symbol_name:
        explanation += f" It is based on the `{symbol_name}` symbol template."
    elif sections and element_type == "rect":
        explanation += f" This graphic is using the configured sections: {', '.join(sections)}."

    display_label = text.strip() if text.strip() else role.replace("_", " ").title()

    return {
        "display_label": display_label,
        "type": element_type,
        "layer": layer,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": text,
        "symbol_name": symbol_name,
        "stroke": stroke,
        "fill": fill,
        "role": role,
        "program_explanation": explanation,
        "equipment_id": equipment_id,
    }


def object_validation_context(project: Project, detail: dict[str, object]) -> dict[str, object]:
    engine = ValidationEngine()
    report = engine.validate(project)
    findings = serialize_validation_findings(report, project.metadata.project_id)
    entity_type = str(detail["entity_type"])
    title = str(detail["title"])
    related_ids = {title}
    linked_points = set(detail.get("linked_points") or [])
    related_entities = list(detail.get("related_entities") or [])

    if entity_type == "equipment":
        related_ids.update(linked_points)
    elif entity_type == "controller":
        related_ids.update(linked_points)
        related_ids.update(
            str(related["entity_key"])
            for related in related_entities
            if related.get("entity_type") == "equipment"
        )
    elif entity_type == "point":
        related_ids.update(str(related["entity_key"]) for related in related_entities)

    relevant = [
        finding
        for finding in findings
        if finding["object_id"] in related_ids
    ]
    direct = [
        finding
        for finding in relevant
        if finding["object_type"] == entity_type and finding["object_id"] == title
    ]
    fix_groups = sorted({finding["fix_group"] for finding in relevant})
    sequence_review = (
        engine.sequence_coverage_for_equipment(project, title)
        if entity_type == "equipment"
        else None
    )
    errors = sum(1 for finding in relevant if finding["severity"] == "error")
    warnings = sum(1 for finding in relevant if finding["severity"] == "warning")
    status = "blocked" if errors else ("attention" if warnings else "ready")
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "result_count": len(relevant),
        "direct_result_count": len(direct),
        "findings": relevant[:12],
        "direct_findings": direct[:8],
        "fix_groups": fix_groups,
        "sequence_review": sequence_review,
        "detail_url": f"/project/{project.metadata.project_id}/validate",
    }


def build_sequence_review(project: Project, equipment_id: str, parsed_sequence=None) -> dict[str, object]:
    engine = ValidationEngine()
    if parsed_sequence is None:
        engine.validate(project)
        return engine.sequence_coverage_for_equipment(project, equipment_id)

    point_refs = {
        str(reference)
        for requirement in parsed_sequence.requirements
        for reference in requirement.points_referenced
        if reference
    }
    requirement_type_values = {
        str(requirement.requirement_type.value)
        for requirement in parsed_sequence.requirements
    }
    return engine.sequence_coverage_for_equipment(
        project,
        equipment_id,
        point_refs=point_refs,
        requirement_type_values=requirement_type_values,
        documents=["Ad hoc sequence parse"],
    )


def build_sequence_workspace(project: Project) -> dict[str, object]:
    engine = ValidationEngine()
    engine.validate(project)
    reviews = []
    for equipment in project.equipment:
        if not equipment.sequence_ref:
            continue
        review = engine.sequence_coverage_for_equipment(project, equipment.id)
        review["equipment_url"] = f"/project/{project.metadata.project_id}/equipment/{equipment.id}"
        review["validation_url"] = f"/project/{project.metadata.project_id}/validate"
        review["sequence_ref"] = equipment.sequence_ref or ""
        review["required_check_count"] = sum(1 for check in review["coverage_checks"] if check["required"])
        review["missing_check_count"] = sum(
            1 for check in review["coverage_checks"] if check["required"] and not check["passed"]
        )
        review["matched_ref_count"] = len(review["matched_refs"])
        review["missing_ref_count"] = len(review["missing_refs"])
        reviews.append(review)

    status_order = {"attention": 0, "not_indexed": 1, "covered": 2}
    reviews.sort(
        key=lambda review: (
            status_order.get(str(review["status"]), 3),
            -int(review["missing_ref_count"]),
            str(review["equipment_id"]),
        )
    )
    summary = {
        "equipment_count": len(reviews),
        "covered": sum(1 for review in reviews if review["status"] == "covered"),
        "attention": sum(1 for review in reviews if review["status"] == "attention"),
        "not_indexed": sum(1 for review in reviews if review["status"] == "not_indexed"),
        "missing_refs": sum(int(review["missing_ref_count"]) for review in reviews),
        "missing_checks": sum(int(review["missing_check_count"]) for review in reviews),
        "required_families": sorted({family for review in reviews for family in review["required_families"]}),
        "missing_families": sorted({family for review in reviews for family in review["missing_families"]}),
    }
    return {
        "summary": summary,
        "reviews": reviews,
    }


def request_expects_json(request: Request) -> bool:
    accept_header = request.headers.get("accept", "")
    return request.url.path.startswith("/api/") or "application/json" in accept_header


def is_protected_path(path: str) -> bool:
    """Return whether a request path requires authentication."""
    public_prefixes = ("/login", "/health", "/healthz", "/api/health", "/static", "/output")
    if path in {"/favicon.ico"} or path.startswith(public_prefixes):
        return False
    return path == "/" or path.startswith("/project") or path.startswith("/api/")


def project_for_request(request: Request) -> Project | None:
    segments = [segment for segment in request.url.path.split("/") if segment]
    if len(segments) >= 2 and segments[0] == "project":
        return projects.get(segments[1])
    return None


def project_id_from_path(path: str) -> str | None:
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 2 and segments[0] == "project":
        return segments[1]
    if len(segments) >= 3 and segments[0] == "api" and segments[1] == "project":
        return segments[2]
    return None


@app.middleware("http")
async def log_request_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = f"{duration:.4f}"
    logger.info(
        "%s %s -> %s in %.4fs",
        request.method,
        request.url.path,
        response.status_code,
        duration,
    )
    return response


@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    if not container.settings.auth_required:
        return await call_next(request)
    if not is_protected_path(request.url.path):
        return await call_next(request)
    if get_current_user(request) is not None:
        current_user = get_current_user(request)
        try:
            require_route_permission(request)
            project_id = project_id_from_path(request.url.path)
            if current_user is not None and project_id is not None:
                can_write = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
                if not container.auth.can_access_project(current_user, project_id, write=can_write):
                    raise HTTPException(status_code=403, detail=f"Access denied for project '{project_id}'")
        except HTTPException as exc:
            if request.url.path.startswith("/api/"):
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "project": project_for_request(request),
                    "error_title": f"HTTP {exc.status_code}",
                    "error_message": str(exc.detail),
                },
                status_code=exc.status_code,
            )
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "Authentication required"})
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning("HTTP error %s on %s: %s", exc.status_code, request.url.path, exc.detail)
    if request_expects_json(request):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "project": project_for_request(request),
            "error_title": f"HTTP {exc.status_code}",
            "error_message": str(exc.detail),
        },
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application error on %s", request.url.path)
    if request_expects_json(request):
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "project": project_for_request(request),
            "error_title": "Unexpected Error",
            "error_message": "The request could not be completed. Review server logs for details.",
        },
        status_code=500,
    )


def current_health_report() -> dict[str, object]:
    runtime_settings = SETTINGS.model_copy(
        update={
            "data_dir": DATA_DIR,
            "output_dir": OUTPUT_DIR,
            "static_dir": STATIC_DIR,
            "templates_dir": TEMPLATES_DIR,
            "uploads_dir": SETTINGS.uploads_dir,
        }
    )
    return build_health_report(runtime_settings, loaded_projects=len(projects))


sync_container_runtime_hooks()


def create_project_from_form(
    project_id: str,
    name: str,
    client: str = "",
    location: str = "",
    unit_system: str = "IP",
    design_phase: str = "",
    engineer: str = "",
    programmer: str = "",
    cx_agent: str = "",
    naming_standard: str = "",
) -> Project:
    """Create, persist, and register a project from web form fields."""
    metadata = ProjectMetadata(
        project_id=project_id,
        name=name,
        client=client or None,
        location=location or None,
        unit_system=UnitSystem(unit_system),
        design_phase=design_phase or None,
        engineer_of_record=engineer or None,
        programmer=programmer or None,
        commissioning_agent=cx_agent or None,
        naming_standard=naming_standard or None,
    )
    project = Project(metadata=metadata)
    save_project(project)
    return project


# ============================================================
# Page Routes
# ============================================================


@app.get("/health")
@app.get("/healthz")
@app.get("/api/health")
async def health_check():
    report = current_health_report()
    status_code = 200 if report["status"] == "ok" else 503
    return JSONResponse(content=report, status_code=status_code)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not container.settings.auth_required:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"current_user": get_current_user(request)},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if not container.settings.auth_required:
        return RedirectResponse(url="/", status_code=303)
    user = container.auth.authenticate(username=username, password=password)
    if user is None:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "current_user": None,
                "error_message": "Invalid username or password.",
                "username": username,
            },
            status_code=401,
        )
    request.session["user"] = user.model_dump(mode="json")
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/" if not container.settings.auth_required else "/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    current_user = get_current_user(request)
    dashboard = timed_page_context("dashboard", lambda: container.dashboard.snapshot(current_user))
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "projects": dashboard.projects,
            "dashboard": dashboard,
            "current_user": current_user,
        },
    )


@app.get("/project/new", response_class=HTMLResponse)
async def new_project_page(request: Request):
    return templates.TemplateResponse(request=request, name="project_new.html", context={"current_user": get_current_user(request)})


@app.post("/project/new")
async def create_project(
    project_id: str = Form(...),
    name: str = Form(...),
    client: str = Form(""),
    location: str = Form(""),
    unit_system: str = Form("IP"),
    design_phase: str = Form(""),
    engineer: str = Form(""),
    programmer: str = Form(""),
    cx_agent: str = Form(""),
    naming_standard: str = Form(""),
):
    create_project_from_form(
        project_id=project_id,
        name=name,
        client=client,
        location=location,
        unit_system=unit_system,
        design_phase=design_phase,
        engineer=engineer,
        programmer=programmer,
        cx_agent=cx_agent,
        naming_standard=naming_standard,
    )
    record_project_ledger_event(
        project_id=project_id,
        event_type="project.created",
        summary=f"Project created: {name}",
        entity_type="project",
        entity_key=project_id,
        payload={
            "project_id": project_id,
            "name": name,
            "client": client,
            "location": location,
            "unit_system": unit_system,
            "design_phase": design_phase,
        },
    )
    return RedirectResponse(url=f"/project/{project_id}", status_code=303)


@app.post("/project/{project_id}/duplicate")
async def duplicate_project_route(
    request: Request,
    project_id: str,
    name: str = Form(""),
    new_project_id: str = Form(""),
):
    duplicate = duplicate_project_snapshot(
        project_id,
        new_name=name,
        new_project_id=new_project_id,
    )
    target = f"/project/{duplicate.metadata.project_id}"
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=200, headers={"HX-Redirect": target})
    return RedirectResponse(url=target, status_code=303)


@app.post("/api/project/new", response_class=HTMLResponse)
async def api_create_project(
    project_id: str = Form(...),
    name: str = Form(...),
    client: str = Form(""),
    location: str = Form(""),
    unit_system: str = Form("IP"),
    design_phase: str = Form(""),
    engineer: str = Form(""),
    programmer: str = Form(""),
    cx_agent: str = Form(""),
    naming_standard: str = Form(""),
):
    create_project_from_form(
        project_id=project_id,
        name=name,
        client=client,
        location=location,
        unit_system=unit_system,
        design_phase=design_phase,
        engineer=engineer,
        programmer=programmer,
        cx_agent=cx_agent,
        naming_standard=naming_standard,
    )
    record_project_ledger_event(
        project_id=project_id,
        event_type="project.created",
        summary=f"Project created: {name}",
        entity_type="project",
        entity_key=project_id,
        payload={
            "project_id": project_id,
            "name": name,
            "client": client,
            "location": location,
            "unit_system": unit_system,
            "design_phase": design_phase,
        },
    )
    return HTMLResponse(
        f'<div data-redirect="/project/{project_id}" '
        'class="text-green-700 dark:text-green-300">Project created. Redirecting...</div>'
    )


@app.get("/project/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    project = get_project(project_id)
    live_validation_report = ValidationEngine().validate(project)
    project_view = timed_page_context(
        f"project_detail:{project_id}",
        lambda: container.project_queries.detail_view(project_id),
    )
    if project_view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project_view["validation_status"] = live_validation_report.summary.get("status", project_view.get("validation_status"))
    project_view["development_status"] = build_project_development_status(project)
    project_view["next_actions"] = build_project_next_actions(project, project_view)
    project_view["validation_triage"] = build_validation_triage(project)
    project_view["live_conditions"] = build_project_live_conditions(project)
    return templates.TemplateResponse(request=request, name="project_detail.html", context={
        "project": project,
        "project_view": project_view,
        "graphic_presets_for": equipment_graphic_presets,
        "graphic_duct_profiles_for": available_duct_profiles,
        "graphic_sections_for": equipment_graphic_sections,
        "graphic_manufacturer_for": equipment_graphic_manufacturer,
        "graphic_model_family_for": equipment_graphic_model_family,
        "graphic_manual_source_for": equipment_graphic_manual_source,
        "graphic_public_reference_for": equipment_graphic_public_reference,
        "graphic_duct_profile_for": equipment_graphic_duct_profile,
        "current_user": get_current_user(request),
    })


@app.get("/project/{project_id}/status", response_class=HTMLResponse)
async def project_status_page(request: Request, project_id: str):
    project = get_project(project_id)
    development_status = build_project_development_status(project)
    project_view = container.project_queries.detail_view(project_id) or {}
    next_actions = build_project_next_actions(
        project,
        {
            "development_status": development_status,
            "engineering_status": project_view.get("engineering_status", {}),
            "import_activity": project_view.get("import_activity", {}),
        },
    )
    return templates.TemplateResponse(request=request, name="project_status.html", context={
        "project": project,
        "development_status": development_status,
        "next_actions": next_actions,
    })


@app.get("/project/{project_id}/equipment/{equipment_id}", response_class=HTMLResponse)
async def equipment_detail_page(request: Request, project_id: str, equipment_id: str):
    project = get_project(project_id)
    detail = container.project_queries.equipment_detail(project_id, equipment_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    detail["validation"] = object_validation_context(project, detail)
    return templates.TemplateResponse(
        request=request,
        name="object_detail.html",
        context={"project": project, "detail": detail, "current_user": get_current_user(request)},
    )


@app.get("/project/{project_id}/equipment", response_class=HTMLResponse)
async def equipment_list_page(
    request: Request,
    project_id: str,
    status: str = "",
    controller_state: str = "",
    provenance_state: str = "",
    equipment_type: str = "",
    validation_category: str = "",
    fix_group: str = "",
    remediation_count: int = 0,
    remediation_action: str = "",
):
    project = get_project(project_id)
    equipment_view = build_object_list_view(
        project=project,
        entity_type="equipment",
        status=status,
        controller_state=controller_state,
        provenance_state=provenance_state,
        equipment_type=equipment_type,
        validation_category=validation_category,
        fix_group=fix_group,
        remediation_count=remediation_count,
        remediation_action=remediation_action,
    )
    return templates.TemplateResponse(
        request=request,
        name="object_list.html",
        context={
            "project": project,
            "title": "Equipment",
            "entity_type": "equipment",
            "rows": equipment_view["rows"],
            "list_view": equipment_view,
        },
    )


@app.get("/project/{project_id}/points/{point_name}", response_class=HTMLResponse)
async def point_detail_page(request: Request, project_id: str, point_name: str):
    project = get_project(project_id)
    detail = container.project_queries.point_detail(project_id, point_name)
    if detail is None:
        raise HTTPException(status_code=404, detail="Point not found")
    detail["validation"] = object_validation_context(project, detail)
    return templates.TemplateResponse(
        request=request,
        name="object_detail.html",
        context={"project": project, "detail": detail, "current_user": get_current_user(request)},
    )


@app.get("/project/{project_id}/points", response_class=HTMLResponse)
async def points_list_page(
    request: Request,
    project_id: str,
    status: str = "",
    controller_state: str = "",
    provenance_state: str = "",
    point_kind: str = "",
    validation_category: str = "",
    fix_group: str = "",
    remediation_count: int = 0,
    remediation_action: str = "",
):
    project = get_project(project_id)
    points_view = build_object_list_view(
        project=project,
        entity_type="point",
        status=status,
        controller_state=controller_state,
        provenance_state=provenance_state,
        point_kind=point_kind,
        validation_category=validation_category,
        fix_group=fix_group,
        remediation_count=remediation_count,
        remediation_action=remediation_action,
    )
    return templates.TemplateResponse(
        request=request,
        name="object_list.html",
        context={
            "project": project,
            "title": "Points",
            "entity_type": "point",
            "rows": points_view["rows"],
            "list_view": points_view,
        },
    )


@app.get("/project/{project_id}/controllers/{controller_id}", response_class=HTMLResponse)
async def controller_detail_page(request: Request, project_id: str, controller_id: str):
    project = get_project(project_id)
    detail = container.project_queries.controller_detail(project_id, controller_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Controller not found")
    detail["validation"] = object_validation_context(project, detail)
    return templates.TemplateResponse(
        request=request,
        name="object_detail.html",
        context={"project": project, "detail": detail, "current_user": get_current_user(request)},
    )


@app.get("/project/{project_id}/controllers", response_class=HTMLResponse)
async def controllers_list_page(
    request: Request,
    project_id: str,
    status: str = "",
    addressing_state: str = "",
    provenance_state: str = "",
    protocol: str = "",
    validation_category: str = "",
    fix_group: str = "",
    remediation_count: int = 0,
    remediation_action: str = "",
):
    project = get_project(project_id)
    controllers_view = build_object_list_view(
        project=project,
        entity_type="controller",
        status=status,
        addressing_state=addressing_state,
        provenance_state=provenance_state,
        protocol=protocol,
        validation_category=validation_category,
        fix_group=fix_group,
        remediation_count=remediation_count,
        remediation_action=remediation_action,
    )
    return templates.TemplateResponse(
        request=request,
        name="object_list.html",
        context={
            "project": project,
            "title": "Controllers",
            "entity_type": "controller",
            "rows": controllers_view["rows"],
            "list_view": controllers_view,
        },
    )


@app.post("/project/{project_id}/{entity_plural}/bulk-remediate")
async def bulk_remediate_object_list(
    project_id: str,
    entity_plural: str,
    action: str = Form(...),
    status: str = Form(""),
    controller_state: str = Form(""),
    addressing_state: str = Form(""),
    provenance_state: str = Form(""),
    equipment_type: str = Form(""),
    point_kind: str = Form(""),
    protocol: str = Form(""),
    validation_category: str = Form(""),
    fix_group: str = Form(""),
):
    project = get_project(project_id)
    plural_map = {"equipment": "equipment", "points": "point", "controllers": "controller"}
    entity_type = plural_map.get(entity_plural)
    if entity_type is None:
        raise HTTPException(status_code=404, detail="Unsupported entity type")

    list_view = build_object_list_view(
        project=project,
        entity_type=entity_type,
        status=status,
        controller_state=controller_state,
        addressing_state=addressing_state,
        provenance_state=provenance_state,
        equipment_type=equipment_type,
        point_kind=point_kind,
        protocol=protocol,
        validation_category=validation_category,
        fix_group=fix_group,
    )
    target_rows = list(list_view["rows"])
    row_key = "id" if entity_type != "point" else "name"
    target_ids = [str(row.get(row_key)) for row in target_rows if row.get(row_key)]
    preview = preview_bulk_remediation(
        project=project,
        entity_type=entity_type,
        target_ids=target_ids,
        action=action,
    )
    updated_count, action_label = apply_bulk_remediation(
        project=project,
        entity_type=entity_type,
        target_ids=target_ids,
        action=action,
    )
    if updated_count:
        container.ledger.record_event(
            event_type="bulk_remediation.applied",
            summary=f"{action_label.replace('_', ' ').title()} updated {updated_count} {entity_plural}",
            project_id=project_id,
            entity_type=entity_type,
            entity_key="*",
            payload={
                "action": action,
                "action_label": action_label,
                "entity_plural": entity_plural,
                "targeted_count": int(preview.get("targeted_count", 0) or 0),
                "change_count": int(preview.get("change_count", 0) or 0),
                "skipped_count": int(preview.get("skipped_count", 0) or 0),
                "changes": list(preview.get("changes") or []),
                "skipped": list(preview.get("skipped") or []),
                "filters": {
                    "status": status,
                    "controller_state": controller_state,
                    "addressing_state": addressing_state,
                    "provenance_state": provenance_state,
                    "equipment_type": equipment_type,
                    "point_kind": point_kind,
                    "protocol": protocol,
                    "validation_category": validation_category,
                    "fix_group": fix_group,
                },
            },
        )
    redirect_filters = {
        "status": status,
        "controller_state": controller_state,
        "addressing_state": addressing_state,
        "provenance_state": provenance_state,
        "equipment_type": equipment_type,
        "point_kind": point_kind,
        "protocol": protocol,
        "validation_category": validation_category,
        "fix_group": fix_group,
        "remediation_count": str(updated_count) if updated_count else "",
        "remediation_action": action_label if updated_count else "",
    }
    return RedirectResponse(
        url=object_list_redirect_target(project_id, entity_type, redirect_filters),
        status_code=303,
    )


@app.post("/project/{project_id}/{entity_plural}/bulk-remediate/preview")
async def preview_bulk_remediate_object_list(
    request: Request,
    project_id: str,
    entity_plural: str,
    action: str = Form(...),
    status: str = Form(""),
    controller_state: str = Form(""),
    addressing_state: str = Form(""),
    provenance_state: str = Form(""),
    equipment_type: str = Form(""),
    point_kind: str = Form(""),
    protocol: str = Form(""),
    validation_category: str = Form(""),
    fix_group: str = Form(""),
):
    project = get_project(project_id)
    plural_map = {"equipment": "equipment", "points": "point", "controllers": "controller"}
    entity_type = plural_map.get(entity_plural)
    if entity_type is None:
        raise HTTPException(status_code=404, detail="Unsupported entity type")

    list_view = build_object_list_view(
        project=project,
        entity_type=entity_type,
        status=status,
        controller_state=controller_state,
        addressing_state=addressing_state,
        provenance_state=provenance_state,
        equipment_type=equipment_type,
        point_kind=point_kind,
        protocol=protocol,
        validation_category=validation_category,
        fix_group=fix_group,
    )
    row_key = "id" if entity_type != "point" else "name"
    target_ids = [str(row.get(row_key)) for row in list_view["rows"] if row.get(row_key)]
    preview = preview_bulk_remediation(
        project=project,
        entity_type=entity_type,
        target_ids=target_ids,
        action=action,
    )
    list_view["bulk_preview"] = preview
    return templates.TemplateResponse(
        request=request,
        name="object_list.html",
        context={
            "project": project,
            "title": "Equipment" if entity_type == "equipment" else ("Points" if entity_type == "point" else "Controllers"),
            "entity_type": entity_type,
            "rows": list_view["rows"],
            "list_view": list_view,
            "current_user": get_current_user(request),
        },
    )


@app.get("/project/{project_id}/activity", response_class=HTMLResponse)
async def project_activity_page(request: Request, project_id: str):
    project = get_project(project_id)
    activity_view = container.project_queries.activity_view(project_id)
    if activity_view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        request=request,
        name="project_activity.html",
        context={
            "project": project,
            "activity_view": activity_view,
            "current_user": get_current_user(request),
        },
    )


@app.get("/activity/ledger", response_class=HTMLResponse)
async def system_ledger_page(
    request: Request,
    project_id: str = "",
    event_type: str = "",
    entity_type: str = "",
    severity: str = "",
    saved_view: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    ledger_view = container.project_queries.system_ledger_view(
        project_id=project_id,
        event_type=event_type,
        entity_type=entity_type,
        severity=severity,
        saved_view=saved_view,
        date_from=date_from,
        date_to=date_to,
        page=page,
    )
    return templates.TemplateResponse(
        request=request,
        name="system_ledger.html",
        context={
            "ledger_view": ledger_view,
            "current_user": get_current_user(request),
        },
    )


@app.get("/activity/ledger/export.json")
async def system_ledger_export_json(
    project_id: str = "",
    event_type: str = "",
    entity_type: str = "",
    severity: str = "",
    saved_view: str = "",
    date_from: str = "",
    date_to: str = "",
):
    rows = container.project_queries.system_ledger_export_rows(
        project_id=project_id,
        event_type=event_type,
        entity_type=entity_type,
        severity=severity,
        saved_view=saved_view,
        date_from=date_from,
        date_to=date_to,
    )
    return JSONResponse(
        content={
            "filters": {
                "project_id": project_id,
                "event_type": event_type,
                "entity_type": entity_type,
                "severity": severity,
                "saved_view": saved_view,
                "date_from": date_from,
                "date_to": date_to,
            },
            "row_count": len(rows),
            "rows": rows,
        },
        headers={"Content-Disposition": 'attachment; filename="system-ledger.json"'},
    )


@app.get("/activity/ledger/export.csv")
async def system_ledger_export_csv(
    project_id: str = "",
    event_type: str = "",
    entity_type: str = "",
    severity: str = "",
    saved_view: str = "",
    date_from: str = "",
    date_to: str = "",
):
    rows = container.project_queries.system_ledger_export_rows(
        project_id=project_id,
        event_type=event_type,
        entity_type=entity_type,
        severity=severity,
        saved_view=saved_view,
        date_from=date_from,
        date_to=date_to,
    )
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "created_at",
            "project_id",
            "project_name",
            "event_type",
            "event_family",
            "severity",
            "entity_type",
            "entity_key",
            "summary",
            "targeted_count",
            "change_count",
            "imported_count",
            "replacement_count",
            "warning_count",
            "error_count",
            "payload_json",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                **row,
                "payload_json": json.dumps(row.get("payload_json") or {}, sort_keys=True),
            }
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="system-ledger.csv"'},
    )


@app.get("/project/{project_id}/documents", response_class=HTMLResponse)
async def project_documents_page(
    request: Request,
    project_id: str,
    document_type: str = "",
    mode: str = "",
    linked_entity_type: str = "",
):
    project = get_project(project_id)
    generated_output_review = build_generated_output_review(project)
    documents_view = timed_page_context(
        f"project_documents:{project_id}",
        lambda: container.project_queries.documents_view(
            project_id,
            document_type=document_type,
            mode=mode,
            linked_entity_type=linked_entity_type,
        ),
    )
    if documents_view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        request=request,
        name="project_documents.html",
        context={
            "project": project,
            "documents_view": documents_view,
            "generated_output_review": generated_output_review,
            "current_user": get_current_user(request),
        },
    )


@app.get("/project/{project_id}/documents/{document_id}", response_class=HTMLResponse)
async def project_document_detail_page(request: Request, project_id: str, document_id: int):
    project = get_project(project_id)
    detail = container.project_queries.document_detail(project_id, document_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return templates.TemplateResponse(
        request=request,
        name="document_detail.html",
        context={
            "project": project,
            "detail": detail,
            "current_user": get_current_user(request),
        },
    )


@app.get("/project/{project_id}/documents/{document_id}/download")
async def project_document_download(project_id: str, document_id: int):
    document = container.project_queries.document_download(project_id, document_id)
    if document is None:
        if container.project_queries.summary(project_id) is None:
            raise HTTPException(status_code=404, detail="Project not found")
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.get("file_path"):
        raise HTTPException(status_code=404, detail="Document not found")
    file_path = Path(str(document["file_path"]))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document file missing")
    return FileResponse(path=file_path, filename=str(document["name"]))


@app.get("/project/{project_id}/knowledge", response_class=HTMLResponse)
async def project_knowledge_page(
    request: Request,
    project_id: str,
    q: str = "",
    source_type: str = "",
    linked_entity_type: str = "",
    status: str = "",
):
    project = get_project(project_id)
    knowledge_view = timed_page_context(
        f"project_knowledge:{project_id}",
        lambda: container.project_queries.search_knowledge(
            project_id,
            q,
            source_type=source_type,
            linked_entity_type=linked_entity_type,
            status=status,
        ),
    )
    if knowledge_view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        request=request,
        name="project_knowledge.html",
        context={
            "project": project,
            "knowledge_view": knowledge_view,
            "current_user": get_current_user(request),
        },
    )


@app.get("/project/{project_id}/memberships", response_class=HTMLResponse)
async def project_memberships_page(request: Request, project_id: str):
    project = get_project(project_id)
    current_user = get_current_user(request)
    if current_user is None or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    memberships_view = container.project_queries.memberships_view(project_id)
    if memberships_view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        request=request,
        name="project_memberships.html",
        context={
            "project": project,
            "memberships_view": memberships_view,
            "current_user": current_user,
        },
    )


@app.post("/project/{project_id}/equipment/{equipment_id}/graphics-config")
async def update_equipment_graphics_config(
    project_id: str,
    equipment_id: str,
    graphic_sections: str = Form(""),
    graphics_manufacturer: str = Form(""),
    graphics_model_family: str = Form(""),
    duct_profile: str = Form(""),
    duct_source: str = Form(""),
    public_reference: str = Form(""),
):
    project = get_project(project_id)
    equipment = project.get_equipment(equipment_id)
    if equipment is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    normalized, invalid = validate_equipment_graphic_sections(equipment, graphic_sections)
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid graphic sections: {', '.join(invalid)}",
        )
    update_equipment_graphic_sections_value(equipment, normalized)
    update_equipment_graphic_parameter(equipment, "graphics_manufacturer", graphics_manufacturer)
    update_equipment_graphic_parameter(equipment, "graphics_model_family", graphics_model_family)
    update_equipment_graphic_parameter(equipment, "duct_profile", duct_profile)
    update_equipment_graphic_parameter(equipment, "duct_source", duct_source)
    update_equipment_graphic_parameter(equipment, "public_reference", public_reference)
    save_project(project)
    return RedirectResponse(url=f"/project/{project_id}", status_code=303)


@app.post("/project/{project_id}/equipment/{equipment_id}/graphics-preset")
async def apply_equipment_graphics_preset(
    project_id: str,
    equipment_id: str,
    preset_value: str = Form(...),
):
    project = get_project(project_id)
    equipment = project.get_equipment(equipment_id)
    if equipment is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    normalized, invalid = validate_equipment_graphic_sections(equipment, preset_value)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid preset sections: {', '.join(invalid)}")
    update_equipment_graphic_sections_value(equipment, normalized)
    save_project(project)
    return RedirectResponse(url=f"/project/{project_id}", status_code=303)


@app.get("/project/{project_id}/import", response_class=HTMLResponse)
@app.get("/project/{project_id}/ingestion", response_class=HTMLResponse)
async def import_page(request: Request, project_id: str):
    project = get_project(project_id)
    context = timed_page_context(
        f"import_page:{project_id}",
        lambda: _import_page_context(project, project_id),
    )
    context["ingestion_mode"] = request.url.path.endswith("/ingestion")
    return templates.TemplateResponse(
        request=request,
        name="import.html",
        context=context,
    )


@app.get("/project/{project_id}/import/editor/{entity_type}", response_class=HTMLResponse)
async def import_editor_section(request: Request, project_id: str, entity_type: str):
    project = get_project(project_id)
    return _render_import_editor_section(request, project, entity_type)


@app.get("/project/{project_id}/import/templates/{template_type}")
async def download_import_template(project_id: str, template_type: str):
    get_project(project_id)
    filename, content = import_template_content(template_type)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/project/{project_id}/import/editor/{entity_type}/save", response_class=HTMLResponse)
async def save_import_editor_row(request: Request, project_id: str, entity_type: str):
    project = get_project(project_id)
    form = await request.form()
    form_data = {str(key): str(value) for key, value in form.items()}
    original_key = form_data.get("original_key", "").strip()

    try:
        if entity_type == "equipment":
            updated_entity = _build_equipment_from_form(form_data)
        elif entity_type == "points":
            updated_entity = _build_point_from_form(form_data)
        elif entity_type == "controllers":
            updated_entity = _build_controller_from_form(form_data)
        else:
            raise HTTPException(status_code=404, detail="Unknown editor type")
    except (ValidationError, ValueError) as exc:
        return _render_import_editor_section(
            request,
            project,
            entity_type,
            message={"level": "error", "text": str(exc)},
        )

    new_key = _editor_key_for_entity(entity_type, form_data)
    if not new_key:
        return _render_import_editor_section(
            request,
            project,
            entity_type,
            message={"level": "error", "text": "The primary ID field is required."},
        )

    existing_index = _find_entity_index(project, entity_type, original_key) if original_key else None
    conflicting_index = _find_entity_index(project, entity_type, new_key)
    if conflicting_index is not None and conflicting_index != existing_index:
        return _render_import_editor_section(
            request,
            project,
            entity_type,
            message={"level": "error", "text": f"{new_key} already exists in this project."},
        )

    if entity_type == "equipment":
        if existing_index is None:
            project.equipment.append(updated_entity)
        else:
            project.equipment[existing_index] = updated_entity
    elif entity_type == "points":
        if existing_index is None:
            project.points.append(updated_entity)
        else:
            project.points[existing_index] = updated_entity
    else:
        if existing_index is None:
            project.controllers.append(updated_entity)
        else:
            project.controllers[existing_index] = updated_entity

    ValidationEngine().validate(project)
    save_project(project)
    return _render_import_editor_section(
        request,
        project,
        entity_type,
        message={"level": "success", "text": "Row saved and project validation refreshed."},
    )


@app.post("/project/{project_id}/import/editor/{entity_type}/{entity_key}/delete", response_class=HTMLResponse)
async def delete_import_editor_row(request: Request, project_id: str, entity_type: str, entity_key: str):
    project = get_project(project_id)
    existing_index = _find_entity_index(project, entity_type, entity_key)
    if existing_index is None:
        return _render_import_editor_section(
            request,
            project,
            entity_type,
            message={"level": "error", "text": f"{entity_key} was not found."},
        )

    if entity_type == "equipment":
        del project.equipment[existing_index]
    elif entity_type == "points":
        del project.points[existing_index]
    elif entity_type == "controllers":
        del project.controllers[existing_index]
    else:
        raise HTTPException(status_code=404, detail="Unknown editor type")

    ValidationEngine().validate(project)
    save_project(project)
    return _render_import_editor_section(
        request,
        project,
        entity_type,
        message={"level": "success", "text": "Row deleted and project validation refreshed."},
    )


@app.post("/project/{project_id}/import")
async def import_data(
    request: Request,
    project_id: str,
    equipment_file: UploadFile | None = File(None),
    points_file: UploadFile | None = File(None),
    controllers_file: UploadFile | None = File(None),
    supporting_files: list[UploadFile] | None = File(None),
):
    project = get_project(project_id)
    importer = CSVImporter(project)
    results = {}
    current_user = None

    if equipment_file and getattr(equipment_file, "filename", None):
        task_id = container.tasks.create_task(
            project_id=project_id,
            task_type="equipment_import",
            payload={"filename": equipment_file.filename},
            created_by_user_id=current_user.id if current_user is not None else None,
        )
        stored_upload = await container.uploads.save_project_upload(
            project=project,
            upload=equipment_file,
            category="equipment",
            document_type="equipment_schedule",
        )
        result = importer.import_equipment_schedule(stored_upload.path, "equip_upload")
        artifact_diff = persist_artifact_links(
            project=project,
            stored_upload=stored_upload,
            links=build_tabular_import_links(
                importer=importer,
                file_path=stored_upload.path,
                entity_type="equipment",
                parser_name="csv_equipment_import",
                source_name=stored_upload.source_document.name,
            ),
            parser_name="csv_equipment_import",
        )
        container.tasks.mark_status(task_id, status="ingested", detail={"stored_path": str(stored_upload.path)})
        results["equipment"] = {"success": result.success, "message": result.message, "errors": result.errors, "warnings": result.warnings, "count": result.equipment_count}
        knowledge_result = container.knowledge.ingest_document(
            project=project,
            file_path=stored_upload.path,
            source_name=stored_upload.source_document.name,
            source_type=stored_upload.document_type,
            metadata={**stored_upload.metadata, "category": stored_upload.category},
        )
        container.tasks.complete_task(
            task_id,
            result=build_ingestion_result_envelope(
                task_type="equipment_import",
                source_name=stored_upload.source_document.name,
                parser_name="csv_equipment_import",
                knowledge_result=knowledge_result,
                import_result=results["equipment"],
                artifact_diff=artifact_diff,
            ),
        )
        record_import_ledger_event(
            project_id=project_id,
            event_type="import.tabular_applied",
            entity_type="equipment",
            source_name=stored_upload.source_document.name,
            import_result=results["equipment"],
            artifact_diff=artifact_diff,
            upload_metadata=stored_upload.metadata,
        )

    if points_file and getattr(points_file, "filename", None):
        task_id = container.tasks.create_task(
            project_id=project_id,
            task_type="points_import",
            payload={"filename": points_file.filename},
            created_by_user_id=current_user.id if current_user is not None else None,
        )
        stored_upload = await container.uploads.save_project_upload(
            project=project,
            upload=points_file,
            category="points",
            document_type="point_list",
        )
        result = importer.import_point_list(stored_upload.path, "points_upload")
        artifact_diff = persist_artifact_links(
            project=project,
            stored_upload=stored_upload,
            links=build_tabular_import_links(
                importer=importer,
                file_path=stored_upload.path,
                entity_type="point",
                parser_name="csv_points_import",
                source_name=stored_upload.source_document.name,
            ),
            parser_name="csv_points_import",
        )
        container.tasks.mark_status(task_id, status="ingested", detail={"stored_path": str(stored_upload.path)})
        results["points"] = {"success": result.success, "message": result.message, "errors": result.errors, "warnings": result.warnings, "count": result.points_count}
        knowledge_result = container.knowledge.ingest_document(
            project=project,
            file_path=stored_upload.path,
            source_name=stored_upload.source_document.name,
            source_type=stored_upload.document_type,
            metadata={**stored_upload.metadata, "category": stored_upload.category},
        )
        container.tasks.complete_task(
            task_id,
            result=build_ingestion_result_envelope(
                task_type="points_import",
                source_name=stored_upload.source_document.name,
                parser_name="csv_points_import",
                knowledge_result=knowledge_result,
                import_result=results["points"],
                artifact_diff=artifact_diff,
            ),
        )
        record_import_ledger_event(
            project_id=project_id,
            event_type="import.tabular_applied",
            entity_type="point",
            source_name=stored_upload.source_document.name,
            import_result=results["points"],
            artifact_diff=artifact_diff,
            upload_metadata=stored_upload.metadata,
        )

    if controllers_file and getattr(controllers_file, "filename", None):
        task_id = container.tasks.create_task(
            project_id=project_id,
            task_type="controllers_import",
            payload={"filename": controllers_file.filename},
            created_by_user_id=current_user.id if current_user is not None else None,
        )
        stored_upload = await container.uploads.save_project_upload(
            project=project,
            upload=controllers_file,
            category="controllers",
            document_type="controller_schedule",
        )
        result = importer.import_controller_schedule(stored_upload.path, "ctrl_upload")
        artifact_diff = persist_artifact_links(
            project=project,
            stored_upload=stored_upload,
            links=build_tabular_import_links(
                importer=importer,
                file_path=stored_upload.path,
                entity_type="controller",
                parser_name="csv_controllers_import",
                source_name=stored_upload.source_document.name,
            ),
            parser_name="csv_controllers_import",
        )
        container.tasks.mark_status(task_id, status="ingested", detail={"stored_path": str(stored_upload.path)})
        results["controllers"] = {"success": result.success, "message": result.message, "errors": result.errors, "warnings": result.warnings, "count": result.controllers_count}
        knowledge_result = container.knowledge.ingest_document(
            project=project,
            file_path=stored_upload.path,
            source_name=stored_upload.source_document.name,
            source_type=stored_upload.document_type,
            metadata={**stored_upload.metadata, "category": stored_upload.category},
        )
        container.tasks.complete_task(
            task_id,
            result=build_ingestion_result_envelope(
                task_type="controllers_import",
                source_name=stored_upload.source_document.name,
                parser_name="csv_controllers_import",
                knowledge_result=knowledge_result,
                import_result=results["controllers"],
                artifact_diff=artifact_diff,
            ),
        )
        record_import_ledger_event(
            project_id=project_id,
            event_type="import.tabular_applied",
            entity_type="controller",
            source_name=stored_upload.source_document.name,
            import_result=results["controllers"],
            artifact_diff=artifact_diff,
            upload_metadata=stored_upload.metadata,
        )

    normalized_supporting_files = supporting_files if isinstance(supporting_files, list) else []
    for supporting_file in normalized_supporting_files:
        if not getattr(supporting_file, "filename", None):
            continue
        task_id = container.tasks.create_task(
            project_id=project_id,
            task_type="artifact_ingestion",
            payload={"filename": supporting_file.filename},
            created_by_user_id=current_user.id if current_user is not None else None,
        )
        stored_upload = await container.uploads.save_project_upload(
            project=project,
            upload=supporting_file,
        )
        container.tasks.mark_status(task_id, status="stored", detail={"stored_path": str(stored_upload.path)})
        knowledge_result = container.knowledge.ingest_document(
            project=project,
            file_path=stored_upload.path,
            source_name=stored_upload.source_document.name,
            source_type=stored_upload.document_type,
            metadata={**stored_upload.metadata, "category": stored_upload.category},
        )
        task_result = build_ingestion_result_envelope(
            task_type="artifact_ingestion",
            source_name=stored_upload.source_document.name,
            parser_name="knowledge_ingestion",
            knowledge_result=knowledge_result,
        )
        if container.parsers.can_parse(stored_upload.path):
            container.tasks.mark_status(task_id, status="parsing", detail={"parser": "niagara"})
            parser_result = container.parsers.parse(project=project, file_path=stored_upload.path)
            artifact_diff = persist_artifact_links(
                project=project,
                stored_upload=stored_upload,
                links=parser_result.links,
                parser_name=parser_result.parser_name,
            )
            results[stored_upload.source_document.name] = {
                "success": parser_result.parsed,
                "equipment_added": parser_result.equipment_added,
                "points_added": parser_result.points_added,
                "controllers_added": parser_result.controllers_added,
                "warnings": parser_result.warnings,
                "details": parser_result.details,
                "artifact_diff": artifact_diff,
            }
            task_result = build_ingestion_result_envelope(
                task_type="artifact_ingestion",
                source_name=stored_upload.source_document.name,
                parser_name=parser_result.parser_name,
                knowledge_result=knowledge_result,
                parser_result=results[stored_upload.source_document.name],
                artifact_diff=artifact_diff,
            )
        container.tasks.complete_task(task_id, result=task_result)
        record_import_ledger_event(
            project_id=project_id,
            event_type="artifact.ingested",
            entity_type="artifact",
            source_name=stored_upload.source_document.name,
            parser_result=results.get(stored_upload.source_document.name),
            artifact_diff=results.get(stored_upload.source_document.name, {}).get("artifact_diff") if isinstance(results.get(stored_upload.source_document.name), dict) else None,
            upload_metadata=stored_upload.metadata,
        )

    save_project(project)
    if request.headers.get("HX-Request") == "true":
        workspace_view = timed_page_context(
            f"import_result:{project_id}",
            lambda: container.project_queries.import_workspace_view(project_id),
        )
        return templates.TemplateResponse(
            request=request,
            name="partials/import_result.html",
            context={
                "project": project,
                "project_id": project_id,
                "results": results,
                "import_status_view": None if workspace_view is None else workspace_view["import_status_view"],
                "recent_upload_views": [] if workspace_view is None else _enrich_recent_upload_views(workspace_view["recent_uploads"]),
            },
        )
    return RedirectResponse(url=f"/project/{project_id}?imported=1", status_code=303)


@app.get("/project/{project_id}/validate", response_class=HTMLResponse)
@app.post("/project/{project_id}/validate", response_class=HTMLResponse)
@app.get("/project/{project_id}/issues", response_class=HTMLResponse)
async def validate_page(request: Request, project_id: str):
    project = get_project(project_id)
    engine = ValidationEngine()
    report = engine.validate(project)
    issues_mode = request.url.path.endswith("/issues")
    import_status_view = container.project_queries.import_status_view(project_id)
    return templates.TemplateResponse(request=request, name="validate.html", context={
        "project": project,
        "validation_report": report,
        "validation_summary": report.summary,
        "validation_findings": serialize_validation_findings(report, project_id),
        "validation_triage": build_validation_triage(project),
        "import_review": build_import_review(import_status_view, project_id),
        "issue_taxonomy": build_issue_taxonomy(project, import_status_view),
        "issues_mode": issues_mode,
    })


@app.get("/project/{project_id}/validate/report.json")
async def validation_report_export(project_id: str):
    project = get_project(project_id)
    engine = ValidationEngine()
    report = engine.validate(project)
    return JSONResponse(
        content=report.model_dump(mode="json"),
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}-validation-report.json"'
        },
    )


@app.get("/project/{project_id}/validate/report.csv")
async def validation_report_csv_export(project_id: str):
    project = get_project(project_id)
    engine = ValidationEngine()
    report = engine.validate(project)
    findings = serialize_validation_findings(report, project_id)

    buffer = StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["severity", "object_type", "object_id", "rule_id", "category", "field", "message"],
    )
    writer.writeheader()
    writer.writerows(findings)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}-validation-report.csv"'
        },
    )


@app.get("/project/{project_id}/gaps", response_class=HTMLResponse)
@app.post("/project/{project_id}/gaps", response_class=HTMLResponse)
async def gaps_page(request: Request, project_id: str):
    project = get_project(project_id)
    report = analyze_gaps(project)
    return templates.TemplateResponse(request=request, name="gaps.html", context={
        "project": project,
        "gap_report": report,
    })


@app.get("/project/{project_id}/mappings", response_class=HTMLResponse)
async def mappings_page(request: Request, project_id: str):
    project = get_project(project_id)
    return templates.TemplateResponse(
        request=request,
        name="mappings.html",
        context={
            "project": project,
            "mapping_candidates": mapping_candidates_for_project(project),
        },
    )


@app.get("/project/{project_id}/review", response_class=HTMLResponse)
async def review_release_page(request: Request, project_id: str):
    project = get_project(project_id)
    return templates.TemplateResponse(
        request=request,
        name="review_release.html",
        context={
            "project": project,
            "review_state": review_release_state(project),
        },
    )


@app.post("/project/{project_id}/review/release")
async def approve_release_readiness(
    project_id: str,
    notes: str = Form(""),
):
    project = get_project(project_id)
    state = review_release_state(project)
    if not state["release_ready"]:
        return RedirectResponse(url=f"/project/{project_id}/review?ready=0", status_code=303)
    record_output_approval(project, notes=notes or "Release review approved.", approved_by="UI")
    return RedirectResponse(url=f"/project/{project_id}/review?ready=1", status_code=303)


@app.post("/project/{project_id}/mappings")
async def save_mapping_decision(
    project_id: str,
    mapping_key: str = Form(...),
    mapped_to: str = Form(...),
    notes: str = Form(""),
):
    project = get_project(project_id)
    upsert_mapping_decision(
        project,
        mapping_key=mapping_key,
        mapped_to=mapped_to,
        notes=notes,
        decided_by="UI",
    )
    return RedirectResponse(url=f"/project/{project_id}/mappings", status_code=303)


@app.post("/project/{project_id}/gaps/{gap_id}/resolve")
async def resolve_gap(
    request: Request,
    project_id: str,
    gap_id: str,
    resolution_notes: str = Form(""),
):
    project = get_project(project_id)
    record_gap_resolution(project, gap_id=gap_id, resolution_notes=resolution_notes, decided_by="UI")
    if request.headers.get("HX-Request") == "true":
        report = analyze_gaps(project)
        return templates.TemplateResponse(
            request=request,
            name="gaps.html",
            context={"project": project, "gap_report": report},
        )
    return RedirectResponse(url=f"/project/{project_id}/gaps", status_code=303)


@app.get("/project/{project_id}/checkout", response_class=HTMLResponse)
@app.post("/project/{project_id}/checkout/generate", response_class=HTMLResponse)
async def checkout_page(request: Request, project_id: str):
    project = get_project(project_id)
    readiness = build_generation_readiness(project)
    if request.method == "GET":
        return templates.TemplateResponse(request=request, name="checkout.html", context={
            "project": project,
            "checkout_result": None,
            "readiness": readiness,
        })
    if request.method == "POST" and not readiness["can_generate"]:
        return templates.TemplateResponse(request=request, name="checkout.html", context={
            "project": project,
            "checkout_result": None,
            "readiness": readiness,
        })
    output_dir = OUTPUT_DIR / project_id / "checkout"
    output_dir.mkdir(parents=True, exist_ok=True)
    task_id = container.tasks.create_task(project_id=project_id, task_type="checkout_generation", payload={"path": str(output_dir)})
    result = generate_checkout_sheets(project, output_dir)
    generated_documents = register_generation_outputs(
        project=project,
        generator_name="checkout_generator",
        outputs=build_checkout_output_descriptors(project, result),
    )
    container.tasks.complete_task(task_id, result={"generated_documents": generated_documents})
    return templates.TemplateResponse(request=request, name="checkout.html", context={
        "project": project,
        "checkout_result": result,
        "readiness": readiness,
    })


@app.get("/project/{project_id}/reports", response_class=HTMLResponse)
@app.post("/project/{project_id}/reports/generate", response_class=HTMLResponse)
async def reports_page(request: Request, project_id: str):
    project = get_project(project_id)
    readiness = build_generation_readiness(project)
    if request.method == "GET":
        return templates.TemplateResponse(request=request, name="reports.html", context={
            "project": project,
            "report_paths": None,
            "readiness": readiness,
        })
    if request.method == "POST" and not readiness["can_generate"]:
        return templates.TemplateResponse(request=request, name="reports.html", context={
            "project": project,
            "report_paths": None,
            "readiness": readiness,
        })
    output_dir = OUTPUT_DIR / project_id / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    task_id = container.tasks.create_task(project_id=project_id, task_type="report_generation", payload={"path": str(output_dir)})
    paths = generate_reports(project, output_dir)
    generated_documents = register_generation_outputs(
        project=project,
        generator_name="report_generator",
        outputs=build_report_output_descriptors(project, paths),
    )
    container.tasks.complete_task(task_id, result={"generated_documents": generated_documents})
    return templates.TemplateResponse(request=request, name="reports.html", context={
        "project": project,
        "report_paths": paths,
        "readiness": readiness,
    })


@app.get("/project/{project_id}/graphics", response_class=HTMLResponse)
@app.post("/project/{project_id}/graphics/generate", response_class=HTMLResponse)
async def graphics_page(request: Request, project_id: str):
    project = get_project(project_id)
    readiness = build_generation_readiness(project)
    persisted_graphics = load_generated_graphics_result(project)
    persisted_active_records = active_graphic_detail_records(project, persisted_graphics)
    persisted_preview_pages = (
        graphics_preview_pages(project, persisted_graphics, detail_records=persisted_active_records)
        if persisted_graphics
        else []
    )
    station_delivery = build_station_delivery_readiness(project, graphics_result=persisted_graphics)
    if request.method == "GET":
        return templates.TemplateResponse(request=request, name="graphics.html", context={
            "project": project,
            "graphics_result": persisted_graphics,
            "graphic_detail_records": persisted_active_records,
            "niagara_preview_pages": persisted_preview_pages,
            "readiness": readiness,
            "station_delivery": station_delivery,
        })
    if request.method == "POST" and not readiness["can_generate"]:
        return templates.TemplateResponse(request=request, name="graphics.html", context={
            "project": project,
            "graphics_result": persisted_graphics,
            "graphic_detail_records": persisted_active_records,
            "niagara_preview_pages": persisted_preview_pages,
            "readiness": readiness,
            "station_delivery": station_delivery,
        })
    output_dir = OUTPUT_DIR / project_id / "graphics"
    output_dir.mkdir(parents=True, exist_ok=True)
    task_id = container.tasks.create_task(project_id=project_id, task_type="graphics_generation", payload={"path": str(output_dir)})
    result = generate_graphics(project, output_dir)
    generated_documents = register_generation_outputs(
        project=project,
        generator_name="graphics_generator",
        outputs=build_graphics_output_descriptors(project, result),
    )
    container.tasks.complete_task(task_id, result={"generated_documents": generated_documents})
    detail_records = active_graphic_detail_records(project, result)
    niagara_preview = graphics_preview_pages(project, result, detail_records=detail_records)
    station_delivery = build_station_delivery_readiness(project, graphics_result=result)
    return templates.TemplateResponse(request=request, name="graphics.html", context={
        "project": project,
        "graphics_result": result,
        "graphic_detail_records": detail_records,
        "niagara_preview_pages": niagara_preview,
        "readiness": readiness,
        "station_delivery": station_delivery,
    })


@app.get("/project/{project_id}/graphics/library", response_class=HTMLResponse)
async def graphics_library_page(request: Request, project_id: str):
    project = get_project(project_id)
    show_legacy_symbols = request.query_params.get("legacy", "").lower() in {"1", "true", "yes", "on"}
    legacy_symbols = graphics_symbol_library()
    return templates.TemplateResponse(
        request=request,
        name="graphics_library.html",
        context={
            "project": project,
            "graphics_symbol_library": graphics_isometric_library(),
            "legacy_symbol_library": legacy_symbols if show_legacy_symbols else [],
            "legacy_symbol_count": len(legacy_symbols),
            "show_legacy_symbols": show_legacy_symbols,
        },
    )


@app.get("/project/{project_id}/graphics/{graphic_name}/fullscreen", response_class=HTMLResponse)
async def graphics_fullscreen_page(request: Request, project_id: str, graphic_name: str):
    project = get_project(project_id)
    graphics_result = load_generated_graphics_result(project)
    if graphics_result is None:
        raise HTTPException(status_code=404, detail="No generated graphics found")
    detail_records = build_graphic_detail_records(project, graphics_result)
    detail = next((record for record in detail_records if record["graphic_name"] == graphic_name), None)
    if detail is None:
        raise HTTPException(status_code=404, detail="Graphic not found")
    station_delivery = build_station_delivery_readiness(project, graphics_result=graphics_result)
    return templates.TemplateResponse(
        request=request,
        name="graphics_fullscreen.html",
        context={
            "project": project,
            "graphic_detail": detail,
            "station_delivery": station_delivery,
        },
    )


@app.get("/project/{project_id}/graphics/{graphic_name}", response_class=HTMLResponse)
async def graphics_detail_page(request: Request, project_id: str, graphic_name: str):
    project = get_project(project_id)
    graphics_result = load_generated_graphics_result(project)
    if graphics_result is None:
        raise HTTPException(status_code=404, detail="No generated graphics found")
    detail_records = build_graphic_detail_records(project, graphics_result)
    detail = next((record for record in detail_records if record["graphic_name"] == graphic_name), None)
    if detail is None:
        raise HTTPException(status_code=404, detail="Graphic not found")
    station_delivery = build_station_delivery_readiness(project, graphics_result=graphics_result)
    return templates.TemplateResponse(
        request=request,
        name="graphics_detail.html",
        context={
            "project": project,
            "graphic_detail": detail,
            "station_delivery": station_delivery,
        },
    )


@app.get("/project/{project_id}/logic", response_class=HTMLResponse)
@app.post("/project/{project_id}/logic/generate", response_class=HTMLResponse)
async def logic_page(request: Request, project_id: str):
    project = get_project(project_id)
    readiness = build_generation_readiness(project)
    if request.method == "GET":
        return templates.TemplateResponse(request=request, name="logic.html", context={
            "project": project,
            "logic_result": None,
            "readiness": readiness,
        })
    if request.method == "POST" and not readiness["can_generate"]:
        return templates.TemplateResponse(request=request, name="logic.html", context={
            "project": project,
            "logic_result": None,
            "readiness": readiness,
        })
    output_dir = OUTPUT_DIR / project_id / "logic"
    output_dir.mkdir(parents=True, exist_ok=True)
    task_id = container.tasks.create_task(project_id=project_id, task_type="logic_generation", payload={"path": str(output_dir)})
    result = generate_logic(project, output_dir)
    generated_documents = register_generation_outputs(
        project=project,
        generator_name="logic_generator",
        outputs=build_logic_output_descriptors(project, result),
    )
    container.tasks.complete_task(task_id, result={"generated_documents": generated_documents})
    return templates.TemplateResponse(request=request, name="logic.html", context={
        "project": project,
        "logic_result": result,
        "readiness": readiness,
    })


@app.get("/project/{project_id}/export", response_class=HTMLResponse)
async def export_page(request: Request, project_id: str):
    project = get_project(project_id)
    readiness = build_generation_readiness(project)
    return templates.TemplateResponse(request=request, name="export.html", context={
        "project": project,
        "readiness": readiness,
    })


@app.post("/project/{project_id}/export")
async def export_project(
    request: Request,
    project_id: str,
    vendors: List[str] = Form(...),
):
    project = get_project(project_id)
    readiness = build_generation_readiness(project)
    if not readiness["can_generate"]:
        return templates.TemplateResponse(request=request, name="export.html", context={
            "project": project,
            "readiness": readiness,
        })
    output_dir = OUTPUT_DIR / project_id / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)

    vendor_map = {
        "niagara": NiagaraExporter,
        "bacnet": BACnetExporter,
        "tridium": TridiumExporter,
        "jci": JCIExporter,
        "siemens": SiemensExporter,
        "honeywell": HoneywellExporter,
    }

    results = {}
    task_id = container.tasks.create_task(project_id=project_id, task_type="export_generation", payload={"vendors": vendors})
    for vendor in vendors:
        if vendor in vendor_map:
            exporter = vendor_map[vendor](project)
            result = exporter.export(output_dir / vendor)
            files = [str(f) for f in result.files]
            file_entries = []
            project_output_root = OUTPUT_DIR / project_id
            for file_path in result.files:
                path = Path(file_path)
                url = None
                try:
                    relative_path = path.relative_to(project_output_root)
                    url = f"/output/{project_id}/{relative_path.as_posix()}"
                except ValueError:
                    url = None
                file_entries.append({
                    "path": str(path),
                    "name": path.name,
                    "url": url,
                })
            results[vendor] = {
                "success": result.success,
                "message": result.message,
                "files": files,
                "file_entries": file_entries,
                "errors": result.errors,
                "warnings": result.warnings,
            }
    generated_documents = register_generation_outputs(
        project=project,
        generator_name="export_generator",
        outputs=build_export_output_descriptors(project, results),
    )
    container.tasks.complete_task(task_id, result={"generated_documents": generated_documents})
    record_project_ledger_event(
        project_id=project_id,
        event_type="export.generated",
        summary=f"Export generated for {len(vendors)} vendor targets",
        entity_type="export",
        entity_key=",".join(vendors),
        payload={
            "vendors": list(vendors),
            "result_count": len(results),
            "success_count": sum(1 for result in results.values() if result.get("success")),
            "warning_count": sum(len(result.get("warnings") or []) for result in results.values()),
            "error_count": sum(len(result.get("errors") or []) for result in results.values()),
        },
    )

    return templates.TemplateResponse(request=request, name="export_result.html", context={
        "project": project,
        "results": results,
    })


@app.get("/project/{project_id}/station-sync", response_class=HTMLResponse)
async def station_sync_page(request: Request, project_id: str):
    project = get_project(project_id)
    config = get_station_connection(project)
    plan = station_sync_service().build_plan(project, config)
    station_delivery = build_station_delivery_readiness(project)
    return templates.TemplateResponse(request=request, name="station_sync.html", context={
        "project": project,
        "station_connection": config,
        "station_plan": plan,
        "probe_result": None,
        "station_delivery": station_delivery,
    })


@app.post("/project/{project_id}/station-sync/save", response_class=HTMLResponse)
async def save_station_sync_config(
    request: Request,
    project_id: str,
    enabled: str | None = Form(None),
    protocol: str = Form(...),
    host: str = Form(""),
    port: int = Form(443),
    use_tls: str | None = Form(None),
    verify_tls: str | None = Form(None),
    station_name: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    obix_path: str = Form("/obix"),
    timeout_seconds: int = Form(10),
):
    project = get_project(project_id)
    config = update_station_connection(
        project,
        enabled=enabled == "on",
        protocol=protocol,
        host=host,
        port=port,
        use_tls=use_tls == "on",
        verify_tls=verify_tls == "on",
        station_name=station_name,
        username=username,
        obix_path=obix_path,
        timeout_seconds=timeout_seconds,
    )
    password_updated = False
    if password.strip():
        station_sync_passwords[project_id] = password
        password_updated = True
    save_project(project)
    record_project_ledger_event(
        project_id=project_id,
        event_type="station_sync.config_saved",
        summary="Station sync configuration saved",
        entity_type="station_sync",
        entity_key=config.station_name or config.host or project_id,
        payload=station_connection_ledger_payload(config, password_updated=password_updated),
    )
    plan = station_sync_service().build_plan(project, config)
    station_delivery = build_station_delivery_readiness(project)
    return templates.TemplateResponse(request=request, name="station_sync.html", context={
        "project": project,
        "station_connection": config,
        "station_plan": plan,
        "probe_result": None,
        "flash_message": "Station sync configuration saved.",
        "station_delivery": station_delivery,
    })


@app.post("/project/{project_id}/station-sync/probe", response_class=HTMLResponse)
async def probe_station_sync(
    request: Request,
    project_id: str,
    enabled: str | None = Form(None),
    protocol: str = Form(...),
    host: str = Form(""),
    port: int = Form(443),
    use_tls: str | None = Form(None),
    verify_tls: str | None = Form(None),
    station_name: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    obix_path: str = Form("/obix"),
    timeout_seconds: int = Form(10),
):
    project = get_project(project_id)
    config = update_station_connection(
        project,
        enabled=enabled == "on",
        protocol=protocol,
        host=host,
        port=port,
        use_tls=use_tls == "on",
        verify_tls=verify_tls == "on",
        station_name=station_name,
        username=username,
        obix_path=obix_path,
        timeout_seconds=timeout_seconds,
    )
    password_updated = False
    if password.strip():
        station_sync_passwords[project_id] = password
        password_updated = True
    password_value = station_sync_passwords.get(project_id)
    probe_result = station_sync_service().probe(config, password=password_value)
    config.last_tested_at = probe_result.checked_at
    config.last_test_status = "success" if probe_result.success else "failed"
    config.last_test_message = probe_result.message
    save_project(project)
    record_project_ledger_event(
        project_id=project_id,
        event_type="station_sync.probe_ran",
        summary=f"Station sync probe {'succeeded' if probe_result.success else 'failed'}",
        entity_type="station_sync",
        entity_key=config.station_name or config.host or project_id,
        payload={
            **station_connection_ledger_payload(config, password_updated=password_updated),
            "probe_success": probe_result.success,
            "probe_endpoint": probe_result.endpoint,
            "probe_status_code": probe_result.status_code,
            "probe_message": probe_result.message,
            "checked_at": probe_result.checked_at.isoformat(),
        },
    )
    plan = station_sync_service().build_plan(project, config)
    station_delivery = build_station_delivery_readiness(project)
    return templates.TemplateResponse(request=request, name="station_sync.html", context={
        "project": project,
        "station_connection": config,
        "station_plan": plan,
        "probe_result": probe_result,
        "station_delivery": station_delivery,
    })


@app.get("/project/{project_id}/sequence", response_class=HTMLResponse)
async def sequence_page(request: Request, project_id: str):
    project = get_project(project_id)
    sequence_workspace = build_sequence_workspace(project)
    return templates.TemplateResponse(request=request, name="sequence.html", context={
        "project": project,
        "sequence_workspace": sequence_workspace,
        "sequence_reviews": sequence_workspace["reviews"],
    })


@app.post("/project/{project_id}/sequence/parse")
async def parse_sequence(
    request: Request,
    project_id: str,
    equipment_id: str = Form(...),
    sequence_text: str = Form(...),
):
    project = get_project(project_id)
    parsed = parse_sequence_text(sequence_text, equipment_id)
    sequence_review = build_sequence_review(project, equipment_id, parsed)
    return templates.TemplateResponse(request=request, name="sequence_result.html", context={
        "project": project,
        "parsed_sequence": parsed,
        "sequence_review": sequence_review,
    })


@app.get("/project/{project_id}/troubleshoot", response_class=HTMLResponse)
async def troubleshoot_page(request: Request, project_id: str):
    project = get_project(project_id)
    return templates.TemplateResponse(request=request, name="troubleshoot.html", context={
        "project": project,
    })


@app.post("/project/{project_id}/troubleshoot/analyze")
async def troubleshoot_analyze(
    request: Request,
    project_id: str,
    equipment_id: str = Form(...),
    analysis_type: str = Form("full"),
    trends_file: UploadFile | None = File(None),
    alarms_file: UploadFile | None = File(None),
):
    project = get_project(project_id)
    
    # Parse uploaded files
    trends = {}
    if trends_file and getattr(trends_file, "filename", None):
        # Parse CSV
        pass
    
    alarms = []
    if alarms_file and getattr(alarms_file, "filename", None):
        # Parse CSV
        pass

    assistant = TroubleshootingAssistant(project)
    report = assistant.analyze_equipment(equipment_id, trends, alarms)
    
    return templates.TemplateResponse(request=request, name="troubleshoot_result.html", context={
        "project": project,
        "troubleshoot_report": report,
    })


@app.get("/project/{project_id}/assumptions", response_class=HTMLResponse)
async def assumptions_page(request: Request, project_id: str):
    project = get_project(project_id)
    tracker, assumption_set = assumption_set_for_project(project_id)
    return templates.TemplateResponse(request=request, name="assumptions.html", context={
        "project": project,
        "tracker": tracker,
        "assumption_set": assumption_set,
    })


# ============================================================
# API Endpoints
# ============================================================

@app.post("/api/sample-data")
async def api_create_sample_data():
    create_sample_csvs(BASE_DIR / "examples")
    return {"message": "Sample CSVs created in /examples"}


@app.post("/api/load-demo")
async def api_load_demo(request: Request):
    """Load the demo HVAC project with all pre-generated outputs."""
    project_id = "demo-hvac-project"

    def redirect_response():
        target = f"/project/{project_id}"
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": target})
        return RedirectResponse(url=target, status_code=303)

    existing_project = container.projects.get(project_id)
    if existing_project is not None:
        generate_demo_outputs(existing_project, OUTPUT_DIR)
        register_persisted_generated_outputs(existing_project)
        refresh_projects_cache()
        return redirect_response()
    project = provision_demo_project(
        container.projects,
        OUTPUT_DIR,
        logger,
        project_id=project_id,
        project_name="Demo HVAC Project",
        examples_dir=BASE_DIR / "examples",
    )
    generated_documents = register_persisted_generated_outputs(project)
    projects[project_id] = project

    record_project_ledger_event(
        project_id=project_id,
        event_type="project.demo_loaded",
        summary="Demo project loaded with generated outputs",
        entity_type="project",
        entity_key=project_id,
        payload={
            "project_id": project_id,
            "equipment_count": len(project.equipment),
            "point_count": len(project.points),
            "controller_count": len(project.controllers),
            "generated_outputs": ["checkout", "reports", "graphics", "logic", "exports"],
            "generated_documents": len(generated_documents),
        },
    )
    
    return redirect_response()


@app.post("/api/gap/{gap_id}/fix")
async def fix_gap(gap_id: str):
    for project in projects.values():
        report = analyze_gaps(project)
        gap = next((item for item in report.gaps if item.gap_id == gap_id), None)
        if gap is None:
            continue

        if gap.affected_object_type == "project":
            field_name = gap.metadata.get("field")
            if field_name and hasattr(project.metadata, field_name):
                default_values = {
                    "client": "TBD Client",
                    "location": "TBD Location",
                    "engineer_of_record": "TBD Engineer",
                    "programmer": "TBD Programmer",
                    "commissioning_agent": "TBD CxA",
                    "design_phase": "CD",
                }
                previous_value = getattr(project.metadata, field_name, None)
                setattr(project.metadata, field_name, default_values.get(field_name, "TBD"))
                save_project(project)
                record_project_ledger_event(
                    project_id=project.metadata.project_id,
                    event_type="gap.auto_fixed",
                    summary=f"Auto-fix applied for gap {gap_id}",
                    entity_type="gap",
                    entity_key=gap_id,
                    payload={
                        "gap_id": gap_id,
                        "affected_object_type": gap.affected_object_type,
                        "affected_object_id": gap.affected_object_id,
                        "field": field_name,
                        "from": "" if previous_value is None else str(previous_value),
                        "to": str(getattr(project.metadata, field_name)),
                    },
                )
                return HTMLResponse('<span class="text-sm font-medium text-green-600 dark:text-green-400">Auto-fix applied</span>')

        if gap.affected_object_type == "equipment":
            equipment = project.get_equipment(gap.affected_object_id)
            if equipment is None:
                break
            if gap.title.endswith("has no controller"):
                previous_value = equipment.controller_id or ""
                controller_id = project.controllers[0].id if project.controllers else "UNASSIGNED"
                equipment.controller_id = controller_id
                save_project(project)
                record_project_ledger_event(
                    project_id=project.metadata.project_id,
                    event_type="gap.auto_fixed",
                    summary=f"Auto-fix applied for gap {gap_id}",
                    entity_type="gap",
                    entity_key=gap_id,
                    payload={
                        "gap_id": gap_id,
                        "affected_object_type": gap.affected_object_type,
                        "affected_object_id": gap.affected_object_id,
                        "field": "controller_id",
                        "from": previous_value,
                        "to": controller_id,
                    },
                )
                return HTMLResponse('<span class="text-sm font-medium text-green-600 dark:text-green-400">Controller assigned</span>')
            if "served area" in gap.title.lower():
                previous_value = equipment.served_area or ""
                equipment.served_area = "TBD Served Area"
                save_project(project)
                record_project_ledger_event(
                    project_id=project.metadata.project_id,
                    event_type="gap.auto_fixed",
                    summary=f"Auto-fix applied for gap {gap_id}",
                    entity_type="gap",
                    entity_key=gap_id,
                    payload={
                        "gap_id": gap_id,
                        "affected_object_type": gap.affected_object_type,
                        "affected_object_id": gap.affected_object_id,
                        "field": "served_area",
                        "from": previous_value,
                        "to": "TBD Served Area",
                    },
                )
                return HTMLResponse('<span class="text-sm font-medium text-green-600 dark:text-green-400">Served area added</span>')

        return HTMLResponse('<span class="text-sm text-gray-500 dark:text-gray-400">No safe auto-fix available</span>')

    raise HTTPException(status_code=404, detail="Gap not found")


@app.get("/api/project/{project_id}/summary")
async def api_project_summary(project_id: str):
    summary = container.project_queries.summary(project_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return summary


@app.get("/api/project/{project_id}/status")
async def api_project_status(project_id: str):
    project = get_project(project_id)
    return build_project_development_status(project)


@app.get("/api/project/{project_id}/equipment")
async def api_equipment_list(project_id: str):
    return container.project_queries.equipment_list(project_id)["rows"]


@app.get("/api/project/{project_id}/points")
async def api_points_list(project_id: str):
    return container.project_queries.points_list(project_id)["rows"]


@app.get("/api/project/{project_id}/controllers")
async def api_controllers_list(project_id: str):
    return container.project_queries.controllers_list(project_id)["rows"]


@app.get("/api/project/{project_id}/emulation/snapshot")
async def api_emulation_snapshot(project_id: str):
    return get_emulation_lab(project_id).snapshot().model_dump(mode="json")


@app.post("/api/project/{project_id}/emulation/step")
async def api_emulation_step(project_id: str, steps: int = 1):
    return get_emulation_lab(project_id).step(steps=max(1, min(steps, 120))).model_dump(mode="json")


@app.post("/api/project/{project_id}/emulation/scenario")
async def api_emulation_scenario(project_id: str, payload: dict[str, object]):
    scenario = str(payload.get("scenario", "")).strip()
    if not scenario:
        raise HTTPException(status_code=400, detail="Payload must include 'scenario'.")
    try:
        return get_emulation_lab(project_id).set_scenario(scenario).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {scenario}") from exc


@app.post("/api/project/{project_id}/emulation/weather")
async def api_emulation_weather(project_id: str, payload: dict[str, object]):
    try:
        request = WeatherWriteRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc
    return get_emulation_lab(project_id).set_weather(request).model_dump(mode="json")


@app.post("/api/project/{project_id}/emulation/controllers/{controller_id}")
async def api_emulation_controller_state(project_id: str, controller_id: str, payload: dict[str, object]):
    state = str(payload.get("state", "")).strip()
    if not state:
        raise HTTPException(status_code=400, detail="Payload must include 'state'.")
    try:
        return get_emulation_lab(project_id).set_controller_state(controller_id, state).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown controller {controller_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid controller state {exc}") from exc


@app.post("/api/project/{project_id}/emulation/reset")
async def api_emulation_reset(project_id: str):
    return get_emulation_lab(project_id).reset().model_dump(mode="json")


@app.post("/api/project/{project_id}/emulation/overrides/clear")
async def api_emulation_clear_overrides(project_id: str):
    return get_emulation_lab(project_id).clear_overrides().model_dump(mode="json")


@app.post("/api/project/{project_id}/emulation/points/{point_name:path}")
async def api_emulation_write_point(project_id: str, point_name: str, payload: dict[str, object]):
    if "value" not in payload:
        raise HTTPException(status_code=400, detail="Payload must include 'value'.")
    try:
        point = get_emulation_lab(project_id).write_point(point_name, payload["value"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown point {point_name}") from exc
    except ReadOnlyPointError as exc:
        raise HTTPException(status_code=400, detail=f"Point {exc} is read-only in the emulator") from exc
    return point.model_dump(mode="json")


@app.post("/api/project/{project_id}/live-conditions")
async def api_project_live_conditions(project_id: str):
    project = get_project(project_id)
    snapshot = get_emulation_lab(project_id).step(1)
    return build_project_live_conditions(project, snapshot=snapshot)


@app.get("/api/project/{project_id}/knowledge/search")
async def api_project_knowledge_search(project_id: str, q: str = ""):
    result = container.project_queries.search_knowledge(project_id, q)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "project_id": result["project_id"],
        "project_name": result["project_name"],
        "query": result["query"],
        "query_terms": result.get("query_terms", []),
        "result_count": result["result_count"],
        "source_hits": result.get("source_hits", []),
        "results": result["results"],
    }


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    current_user = get_current_user(request)
    if current_user is None or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return templates.TemplateResponse(
        request=request,
        name="admin_users.html",
        context={
            "current_user": current_user,
            "managed_users": container.auth.list_users(),
            "available_projects": container.project_queries.list_project_cards(),
        },
    )


@app.post("/admin/users")
async def admin_create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    project_ids: list[str] | None = Form(None),
    access_level: str = Form("viewer"),
):
    current_user = get_current_user(request)
    if current_user is None or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        container.auth.create_user(
            username=username.strip(),
            email=email.strip(),
            password=password,
            role=role,
            project_ids=project_ids or [],
            access_level=access_level,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="admin_users.html",
            context={
                "current_user": current_user,
                "managed_users": container.auth.list_users(),
                "available_projects": container.project_queries.list_project_cards(),
                "error_message": str(exc),
            },
            status_code=400,
        )
    record_project_ledger_event(
        project_id=project_ids[0] if project_ids else None,
        event_type="admin.user_created",
        summary=f"User created: {username.strip()}",
        entity_type="user",
        entity_key=username.strip(),
        payload={
            "username": username.strip(),
            "email": email.strip(),
            "role": role,
            "project_ids": list(project_ids or []),
            "access_level": access_level,
            "performed_by": current_user.username,
        },
    )
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/admin/users/{user_id}")
async def admin_update_user(
    request: Request,
    user_id: int,
    role: str = Form(...),
    is_active: str = Form("false"),
    project_ids: list[str] | None = Form(None),
    access_level: str = Form("viewer"),
):
    current_user = get_current_user(request)
    if current_user is None or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        container.auth.update_user(
            user_id=user_id,
            role=role,
            is_active=is_active.lower() == "true",
            project_ids=project_ids or [],
            access_level=access_level,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="admin_users.html",
            context={
                "current_user": current_user,
                "managed_users": container.auth.list_users(),
                "available_projects": container.project_queries.list_project_cards(),
                "error_message": str(exc),
            },
            status_code=400,
        )
    managed_user = next((user for user in container.auth.list_users() if int(user.id) == user_id), None)
    record_project_ledger_event(
        project_id=project_ids[0] if project_ids else None,
        event_type="admin.user_updated",
        summary=f"User updated: {managed_user.username if managed_user else user_id}",
        entity_type="user",
        entity_key=str(user_id),
        payload={
            "user_id": user_id,
            "username": managed_user.username if managed_user else "",
            "role": role,
            "is_active": is_active.lower() == "true",
            "project_ids": list(project_ids or []),
            "access_level": access_level,
            "performed_by": current_user.username,
        },
    )
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/project/{project_id}/memberships")
async def project_memberships_update(
    request: Request,
    project_id: str,
):
    current_user = get_current_user(request)
    if current_user is None or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    form = await request.form()
    assignments: list[tuple[int, str]] = []
    for key, value in form.multi_items():
        if not key.startswith("user_access_"):
            continue
        if not value:
            continue
        user_id = int(key.removeprefix("user_access_"))
        assignments.append((user_id, str(value)))
    container.auth.set_project_memberships(project_id=project_id, assignments=assignments)
    record_project_ledger_event(
        project_id=project_id,
        event_type="admin.project_memberships_updated",
        summary=f"Project memberships updated for {project_id}",
        entity_type="membership",
        entity_key=project_id,
        payload={
            "project_id": project_id,
            "assignments": assignment_ledger_payload(assignments),
            "assignment_count": len(assignments),
            "performed_by": current_user.username,
        },
    )
    return RedirectResponse(url=f"/project/{project_id}/memberships", status_code=303)


@app.post("/project/{project_id}/assumptions/add")
async def add_assumption(
    request: Request,
    project_id: str,
    category: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    status: str = Form("pending"),
    rationale: str = Form(""),
    verification_method: str = Form(""),
    impacts: str = Form(""),
):
    project = get_project(project_id)
    tracker, _assumption_set = assumption_set_for_project(project_id)
    assumption = tracker.add_assumption(
        category=AssumptionCategory(category),
        title=title,
        description=description,
        rationale=_form_text(rationale),
        verification_method=_form_text(verification_method),
        impacts=[i.strip() for i in _form_text(impacts).split(",") if i.strip()],
        set_name="design_basis",
    )
    status_enum = AssumptionStatus(status)
    if status_enum == AssumptionStatus.VERIFIED:
        assumption.verify("UI", "Marked verified from assumptions page")
    elif status_enum == AssumptionStatus.INVALIDATED:
        assumption.invalidate("Marked invalidated from assumptions page")
    elif status_enum == AssumptionStatus.DEFERRED:
        assumption.defer("Deferred from assumptions page")
    elif status_enum == AssumptionStatus.ACCEPTED:
        assumption.accept()
    sync_assumptions_to_project(project, tracker)
    record_project_ledger_event(
        project_id=project_id,
        event_type="assumption.added",
        summary=f"Assumption added: {assumption.title}",
        entity_type="assumption",
        entity_key=assumption.assumption_id,
        payload={
            "assumption_id": assumption.assumption_id,
            "title": assumption.title,
            "category": assumption.category.value,
            "status": assumption.status.value,
            "description": assumption.description,
            "rationale": assumption.rationale,
            "verification_method": assumption.verification_method,
            "impacts": list(assumption.impacts),
        },
    )

    if request.headers.get("HX-Request") == "true":
        return render_assumptions_list(request, project)
    return RedirectResponse(url=f"/project/{project_id}/assumptions", status_code=303)


@app.post("/project/{project_id}/assumptions/{assumption_id}/verify")
async def verify_assumption(request: Request, project_id: str, assumption_id: str):
    project = get_project(project_id)
    tracker, _assumption_set = assumption_set_for_project(project_id)
    tracker.verify_assumption(assumption_id, "UI", "Verified from assumptions page")
    assumption = tracker.get_assumption(assumption_id)
    sync_assumptions_to_project(project, tracker)
    if assumption is not None:
        record_project_ledger_event(
            project_id=project_id,
            event_type="assumption.verified",
            summary=f"Assumption verified: {assumption.title}",
            entity_type="assumption",
            entity_key=assumption_id,
            payload={
                "assumption_id": assumption_id,
                "title": assumption.title,
                "status": assumption.status.value,
                "verified_by": assumption.verified_by or "",
                "verification_evidence": assumption.verification_evidence or "",
            },
        )
    return render_assumptions_list(request, project)


@app.post("/project/{project_id}/assumptions/{assumption_id}/invalidate")
async def invalidate_assumption(request: Request, project_id: str, assumption_id: str):
    project = get_project(project_id)
    tracker, _assumption_set = assumption_set_for_project(project_id)
    tracker.invalidate_assumption(assumption_id, "Invalidated from assumptions page")
    assumption = tracker.get_assumption(assumption_id)
    sync_assumptions_to_project(project, tracker)
    if assumption is not None:
        record_project_ledger_event(
            project_id=project_id,
            event_type="assumption.invalidated",
            summary=f"Assumption invalidated: {assumption.title}",
            entity_type="assumption",
            entity_key=assumption_id,
            payload={
                "assumption_id": assumption_id,
                "title": assumption.title,
                "status": assumption.status.value,
                "notes": assumption.notes or "",
            },
        )
    return render_assumptions_list(request, project)


@app.post("/project/{project_id}/assumptions/load-templates")
async def load_assumption_templates(request: Request, project_id: str):
    project = get_project(project_id)
    assumption_trackers[project_id] = create_bas_assumptions(project_id)
    sync_assumptions_to_project(project, assumption_trackers[project_id])
    tracker = assumption_trackers[project_id]
    design_basis = tracker.assumption_sets.get("design_basis")
    template_count = len(design_basis.assumptions) if design_basis is not None else 0
    record_project_ledger_event(
        project_id=project_id,
        event_type="assumption.templates_loaded",
        summary=f"Loaded {template_count} assumption templates",
        entity_type="assumption",
        entity_key="design_basis",
        payload={
            "set_name": "design_basis",
            "template_count": template_count,
        },
    )
    return render_assumptions_list(request, project)


@app.post("/project/{project_id}/review/approve")
async def approve_review_outputs(
    project_id: str,
    notes: str = Form(""),
):
    project = get_project(project_id)
    record_output_approval(project, notes=notes, approved_by="UI")
    return RedirectResponse(url=f"/project/{project_id}", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SETTINGS.host, port=SETTINGS.port)
