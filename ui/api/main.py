"""BAS Assistant Web UI - FastAPI Application."""

import csv
import json
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path
from typing import Optional, List
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from bas_assistant.auth import get_current_user, require_route_permission
from bas_assistant.core import build_container
from bas_assistant.models import (
    Project, ProjectMetadata, Equipment, EquipmentType, Point, PointKind,
    PointDirection, PointSource, Controller, Protocol, UnitSystem,
    ApprovalReviewDecision, GapReviewDecision, MappingReviewDecision, ReviewAssumptionRecord,
    ControllerNetworkAddress, ControllerIOCapacity, StationConnectionConfig,
    StationSyncProtocol
)
from bas_assistant.models.equipment import EquipmentTemplateRef
from bas_assistant.importers import CSVImporter, create_sample_csvs
from bas_assistant.generators.graphics import GraphicsGenerator
from bas_assistant.validation import ValidationEngine
from bas_assistant.generators import (
    generate_checkout_sheets, generate_reports, generate_graphics, generate_logic
)
from bas_assistant.exporters import (
    NiagaraExporter, BACnetExporter, TridiumExporter,
    JCIExporter, SiemensExporter, HoneywellExporter
)
from bas_assistant.reasoning import (
    analyze_gaps, parse_sequence as parse_sequence_text, TroubleshootingAssistant,
    TrendData, TrendPoint, AlarmEvent, IssueSeverity, IssueCategory,
    ConfidenceScorer, validate_engineering_rules, create_bas_assumptions,
    AssumptionTracker, AssumptionStatus, AssumptionCategory
)
from bas_assistant.station_sync import StationSyncService
from bas_assistant.config import get_settings
from bas_assistant.runtime import build_health_report, configure_logging, ensure_runtime_directories
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


def save_project(project: Project) -> None:
    project.update_timestamp()
    container.projects.save(project)
    projects[project.metadata.project_id] = project


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


def graphics_preview_pages(project: Project) -> list[dict[str, object]]:
    pages = NiagaraExporter(project).preview_pages()
    equipment_pages = [
        page for page in pages
        if str(page.get("slotPath", "")).startswith("/Px/Equipment/")
    ]
    return equipment_pages or pages


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
    if workspace_view is None:
        return {
            "project": project,
            "recent_upload_views": [],
            "import_status_view": None,
        }
    return {
        "project": project,
        "recent_upload_views": _enrich_recent_upload_views(workspace_view["recent_uploads"]),
        "import_status_view": workspace_view["import_status_view"],
    }


def timed_page_context(label: str, builder):
    start_time = time.perf_counter()
    context = builder()
    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("page_context[%s] built in %.2fms", label, duration_ms)
    return context


def _form_text(value: object) -> str:
    return value if isinstance(value, str) else ""


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


def serialize_validation_findings(report, project_id: str | None = None) -> list[dict[str, str]]:
    findings = []
    for finding in report.errors + report.warnings + report.infos:
        remediation, fix_group = validation_remediation_for_rule(finding.rule_id, finding.field or "")
        rule_family = finding.rule_id.split("-", 1)[0].lower()
        findings.append(
            {
                "severity": finding.severity.value,
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
    return RedirectResponse(url=f"/project/{project_id}", status_code=303)


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
    return HTMLResponse(
        f'<div data-redirect="/project/{project_id}" '
        'class="text-green-700 dark:text-green-300">Project created. Redirecting...</div>'
    )


@app.get("/project/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    project = get_project(project_id)
    project_view = timed_page_context(
        f"project_detail:{project_id}",
        lambda: container.project_queries.detail_view(project_id),
    )
    if project_view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(request=request, name="project_detail.html", context={
        "project": project,
        "project_view": project_view,
        "graphic_presets_for": equipment_graphic_presets,
        "current_user": get_current_user(request),
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
async def equipment_list_page(request: Request, project_id: str):
    project = get_project(project_id)
    return templates.TemplateResponse(
        request=request,
        name="object_list.html",
        context={
            "project": project,
            "title": "Equipment",
            "entity_type": "equipment",
            "rows": container.project_queries.equipment_list(project_id),
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
async def points_list_page(request: Request, project_id: str):
    project = get_project(project_id)
    return templates.TemplateResponse(
        request=request,
        name="object_list.html",
        context={
            "project": project,
            "title": "Points",
            "entity_type": "point",
            "rows": container.project_queries.points_list(project_id),
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
async def controllers_list_page(request: Request, project_id: str):
    project = get_project(project_id)
    return templates.TemplateResponse(
        request=request,
        name="object_list.html",
        context={
            "project": project,
            "title": "Controllers",
            "entity_type": "controller",
            "rows": container.project_queries.controllers_list(project_id),
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


@app.get("/project/{project_id}/documents", response_class=HTMLResponse)
async def project_documents_page(request: Request, project_id: str):
    project = get_project(project_id)
    documents_view = timed_page_context(
        f"project_documents:{project_id}",
        lambda: container.project_queries.documents_view(project_id),
    )
    if documents_view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        request=request,
        name="project_documents.html",
        context={
            "project": project,
            "documents_view": documents_view,
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
async def project_knowledge_page(request: Request, project_id: str, q: str = ""):
    project = get_project(project_id)
    knowledge_view = timed_page_context(
        f"project_knowledge:{project_id}",
        lambda: container.project_queries.search_knowledge(project_id, q),
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
async def import_page(request: Request, project_id: str):
    project = get_project(project_id)
    return templates.TemplateResponse(
        request=request,
        name="import.html",
        context=timed_page_context(
            f"import_page:{project_id}",
            lambda: _import_page_context(project, project_id),
        ),
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
            result={
                "import_result": results["equipment"],
                "knowledge_status": knowledge_result.status,
                "chunk_count": knowledge_result.chunk_count,
                "artifact_diff": artifact_diff,
            },
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
            result={
                "import_result": results["points"],
                "knowledge_status": knowledge_result.status,
                "chunk_count": knowledge_result.chunk_count,
                "artifact_diff": artifact_diff,
            },
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
            result={
                "import_result": results["controllers"],
                "knowledge_status": knowledge_result.status,
                "chunk_count": knowledge_result.chunk_count,
                "artifact_diff": artifact_diff,
            },
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
        task_result = {
            "knowledge_status": knowledge_result.status,
            "chunk_count": knowledge_result.chunk_count,
        }
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
            task_result["parser_result"] = results[stored_upload.source_document.name]
        container.tasks.complete_task(task_id, result=task_result)

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
async def validate_page(request: Request, project_id: str):
    project = get_project(project_id)
    engine = ValidationEngine()
    report = engine.validate(project)
    return templates.TemplateResponse(request=request, name="validate.html", context={
        "project": project,
        "validation_report": report,
        "validation_summary": report.summary,
        "validation_findings": serialize_validation_findings(report, project_id),
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
    if request.method == "GET":
        return templates.TemplateResponse(request=request, name="graphics.html", context={
            "project": project,
            "graphics_result": None,
            "niagara_preview_pages": [],
            "graphics_symbol_library": graphics_symbol_library(),
            "readiness": readiness,
        })
    if request.method == "POST" and not readiness["can_generate"]:
        return templates.TemplateResponse(request=request, name="graphics.html", context={
            "project": project,
            "graphics_result": None,
            "niagara_preview_pages": [],
            "graphics_symbol_library": graphics_symbol_library(),
            "readiness": readiness,
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
    niagara_preview = graphics_preview_pages(project)
    return templates.TemplateResponse(request=request, name="graphics.html", context={
        "project": project,
        "graphics_result": result,
        "niagara_preview_pages": niagara_preview,
        "graphics_symbol_library": graphics_symbol_library(),
        "readiness": readiness,
    })


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
            results[vendor] = {
                "success": result.success,
                "message": result.message,
                "files": [str(f) for f in result.files],
                "errors": result.errors,
                "warnings": result.warnings,
            }
    generated_documents = register_generation_outputs(
        project=project,
        generator_name="export_generator",
        outputs=build_export_output_descriptors(project, results),
    )
    container.tasks.complete_task(task_id, result={"generated_documents": generated_documents})

    return templates.TemplateResponse(request=request, name="export_result.html", context={
        "project": project,
        "results": results,
    })


@app.get("/project/{project_id}/station-sync", response_class=HTMLResponse)
async def station_sync_page(request: Request, project_id: str):
    project = get_project(project_id)
    config = get_station_connection(project)
    plan = station_sync_service().build_plan(project, config)
    return templates.TemplateResponse(request=request, name="station_sync.html", context={
        "project": project,
        "station_connection": config,
        "station_plan": plan,
        "probe_result": None,
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
    if password.strip():
        station_sync_passwords[project_id] = password
    save_project(project)
    plan = station_sync_service().build_plan(project, config)
    return templates.TemplateResponse(request=request, name="station_sync.html", context={
        "project": project,
        "station_connection": config,
        "station_plan": plan,
        "probe_result": None,
        "flash_message": "Station sync configuration saved.",
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
    if password.strip():
        station_sync_passwords[project_id] = password
    password_value = station_sync_passwords.get(project_id)
    probe_result = station_sync_service().probe(config, password=password_value)
    config.last_tested_at = probe_result.checked_at
    config.last_test_status = "success" if probe_result.success else "failed"
    config.last_test_message = probe_result.message
    save_project(project)
    plan = station_sync_service().build_plan(project, config)
    return templates.TemplateResponse(request=request, name="station_sync.html", context={
        "project": project,
        "station_connection": config,
        "station_plan": plan,
        "probe_result": probe_result,
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
    from pathlib import Path
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

    project_id = "demo-hvac-project"

    def redirect_response():
        target = f"/project/{project_id}"
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": target})
        return RedirectResponse(url=target, status_code=303)
    
    # Check if already loaded
    if project_id in projects:
        return redirect_response()
    
    # Create project
    metadata = ProjectMetadata(
        project_id=project_id,
        name="Demo HVAC Project",
        client="Demo Client",
        location="Demo Building",
        unit_system=UnitSystem.IP,
        design_phase="Design Development",
        engineer_of_record="Demo Engineer",
        programmer="Demo Programmer",
        commissioning_agent="Demo CxA",
        naming_standard="ASHRAE 135",
    )
    project = Project(metadata=metadata)
    
    # Import sample data
    importer = CSVImporter(project)
    create_sample_csvs(BASE_DIR / "examples")
    
    equip_file = BASE_DIR / "examples" / "equipment_schedule.csv"
    if equip_file.exists():
        importer.import_equipment_schedule(equip_file, "equip_schedule_demo")
    
    points_file = BASE_DIR / "examples" / "point_list.csv"
    if points_file.exists():
        importer.import_point_list(points_file, "point_list_demo")
    
    ctrl_file = BASE_DIR / "examples" / "controller_schedule.csv"
    if ctrl_file.exists():
        importer.import_controller_schedule(ctrl_file, "ctrl_schedule_demo")
    
    # Save project
    save_project(project)
    
    # Generate all outputs
    output_dir = OUTPUT_DIR / project_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Validation
    engine = ValidationEngine()
    engine.validate(project)
    
    # Gap analysis
    analyze_gaps(project)
    
    # Checkout sheets
    checkout_dir = output_dir / "checkout"
    checkout_dir.mkdir(parents=True, exist_ok=True)
    generate_checkout_sheets(project, checkout_dir)
    
    # Reports
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    generate_reports(project, reports_dir)
    
    # Graphics
    graphics_dir = output_dir / "graphics"
    graphics_dir.mkdir(parents=True, exist_ok=True)
    generate_graphics(project, graphics_dir)
    
    # Logic
    logic_dir = output_dir / "logic"
    logic_dir.mkdir(parents=True, exist_ok=True)
    generate_logic(project, logic_dir)
    
    # Exports
    exports_dir = output_dir / "exports"
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
                setattr(project.metadata, field_name, default_values.get(field_name, "TBD"))
                save_project(project)
                return HTMLResponse('<span class="text-sm font-medium text-green-600 dark:text-green-400">Auto-fix applied</span>')

        if gap.affected_object_type == "equipment":
            equipment = project.get_equipment(gap.affected_object_id)
            if equipment is None:
                break
            if gap.title.endswith("has no controller"):
                controller_id = project.controllers[0].id if project.controllers else "UNASSIGNED"
                equipment.controller_id = controller_id
                save_project(project)
                return HTMLResponse('<span class="text-sm font-medium text-green-600 dark:text-green-400">Controller assigned</span>')
            if "served area" in gap.title.lower():
                equipment.served_area = "TBD Served Area"
                save_project(project)
                return HTMLResponse('<span class="text-sm font-medium text-green-600 dark:text-green-400">Served area added</span>')

        return HTMLResponse('<span class="text-sm text-gray-500 dark:text-gray-400">No safe auto-fix available</span>')

    raise HTTPException(status_code=404, detail="Gap not found")


@app.get("/api/project/{project_id}/summary")
async def api_project_summary(project_id: str):
    summary = container.project_queries.summary(project_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return summary


@app.get("/api/project/{project_id}/equipment")
async def api_equipment_list(project_id: str):
    return container.project_queries.equipment_list(project_id)


@app.get("/api/project/{project_id}/points")
async def api_points_list(project_id: str):
    return container.project_queries.points_list(project_id)


@app.get("/api/project/{project_id}/controllers")
async def api_controllers_list(project_id: str):
    return container.project_queries.controllers_list(project_id)


@app.get("/api/project/{project_id}/knowledge/search")
async def api_project_knowledge_search(project_id: str, q: str = ""):
    result = container.project_queries.search_knowledge(project_id, q)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "project_id": result["project_id"],
        "project_name": result["project_name"],
        "query": result["query"],
        "result_count": result["result_count"],
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

    if request.headers.get("HX-Request") == "true":
        return render_assumptions_list(request, project)
    return RedirectResponse(url=f"/project/{project_id}/assumptions", status_code=303)


@app.post("/project/{project_id}/assumptions/{assumption_id}/verify")
async def verify_assumption(request: Request, project_id: str, assumption_id: str):
    project = get_project(project_id)
    tracker, _assumption_set = assumption_set_for_project(project_id)
    tracker.verify_assumption(assumption_id, "UI", "Verified from assumptions page")
    sync_assumptions_to_project(project, tracker)
    return render_assumptions_list(request, project)


@app.post("/project/{project_id}/assumptions/{assumption_id}/invalidate")
async def invalidate_assumption(request: Request, project_id: str, assumption_id: str):
    project = get_project(project_id)
    tracker, _assumption_set = assumption_set_for_project(project_id)
    tracker.invalidate_assumption(assumption_id, "Invalidated from assumptions page")
    sync_assumptions_to_project(project, tracker)
    return render_assumptions_list(request, project)


@app.post("/project/{project_id}/assumptions/load-templates")
async def load_assumption_templates(request: Request, project_id: str):
    project = get_project(project_id)
    assumption_trackers[project_id] = create_bas_assumptions(project_id)
    sync_assumptions_to_project(project, assumption_trackers[project_id])
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
