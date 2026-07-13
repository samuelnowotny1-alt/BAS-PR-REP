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


def get_assumption_tracker(project_id: str) -> AssumptionTracker:
    tracker = assumption_trackers.get(project_id)
    if tracker is None:
        tracker = create_bas_assumptions(project_id)
        assumption_trackers[project_id] = tracker
    return tracker


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


def serialize_validation_findings(report) -> list[dict[str, str]]:
    findings = []
    for finding in report.errors + report.warnings + report.infos:
        findings.append(
            {
                "severity": finding.severity.value,
                "object_type": finding.object_type,
                "object_id": finding.object_id,
                "rule_id": finding.rule_id,
                "category": finding.category.value,
                "field": finding.field or "",
                "message": finding.message,
            }
        )
    return findings


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
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    current_user = get_current_user(request)
    dashboard = container.dashboard.snapshot(current_user)
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
    project_view = container.project_queries.detail_view(project_id)
    if project_view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(request=request, name="project_detail.html", context={
        "project": project,
        "project_view": project_view,
        "graphic_presets_for": equipment_graphic_presets,
    })


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
    return templates.TemplateResponse(request=request, name="import.html", context={
        "project": project,
        "recent_uploads": container.uploads.list_recent_uploads(project_id=project_id, limit=8),
    })


@app.post("/project/{project_id}/import")
async def import_data(
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
            results[stored_upload.source_document.name] = {
                "success": parser_result.parsed,
                "equipment_added": parser_result.equipment_added,
                "points_added": parser_result.points_added,
                "warnings": parser_result.warnings,
                "details": parser_result.details,
            }
            task_result["parser_result"] = results[stored_upload.source_document.name]
        container.tasks.complete_task(task_id, result=task_result)

    save_project(project)
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
        "validation_findings": serialize_validation_findings(report),
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
    findings = serialize_validation_findings(report)

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


@app.get("/project/{project_id}/checkout", response_class=HTMLResponse)
@app.post("/project/{project_id}/checkout/generate", response_class=HTMLResponse)
async def checkout_page(request: Request, project_id: str):
    project = get_project(project_id)
    output_dir = OUTPUT_DIR / project_id / "checkout"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = generate_checkout_sheets(project, output_dir)
    return templates.TemplateResponse(request=request, name="checkout.html", context={
        "project": project,
        "checkout_result": result,
    })


@app.get("/project/{project_id}/reports", response_class=HTMLResponse)
@app.post("/project/{project_id}/reports/generate", response_class=HTMLResponse)
async def reports_page(request: Request, project_id: str):
    project = get_project(project_id)
    output_dir = OUTPUT_DIR / project_id / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = generate_reports(project, output_dir)
    return templates.TemplateResponse(request=request, name="reports.html", context={
        "project": project,
        "report_paths": paths,
    })


@app.get("/project/{project_id}/graphics", response_class=HTMLResponse)
@app.post("/project/{project_id}/graphics/generate", response_class=HTMLResponse)
async def graphics_page(request: Request, project_id: str):
    project = get_project(project_id)
    output_dir = OUTPUT_DIR / project_id / "graphics"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = generate_graphics(project, output_dir)
    niagara_preview = graphics_preview_pages(project)
    return templates.TemplateResponse(request=request, name="graphics.html", context={
        "project": project,
        "graphics_result": result,
        "niagara_preview_pages": niagara_preview,
        "graphics_symbol_library": graphics_symbol_library(),
    })


@app.get("/project/{project_id}/logic", response_class=HTMLResponse)
@app.post("/project/{project_id}/logic/generate", response_class=HTMLResponse)
async def logic_page(request: Request, project_id: str):
    project = get_project(project_id)
    output_dir = OUTPUT_DIR / project_id / "logic"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = generate_logic(project, output_dir)
    return templates.TemplateResponse(request=request, name="logic.html", context={
        "project": project,
        "logic_result": result,
    })


@app.get("/project/{project_id}/export", response_class=HTMLResponse)
async def export_page(request: Request, project_id: str):
    project = get_project(project_id)
    return templates.TemplateResponse(request=request, name="export.html", context={
        "project": project,
    })


@app.post("/project/{project_id}/export")
async def export_project(
    request: Request,
    project_id: str,
    vendors: List[str] = Form(...),
):
    project = get_project(project_id)
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
    return templates.TemplateResponse(request=request, name="sequence.html", context={
        "project": project,
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
    return templates.TemplateResponse(request=request, name="sequence_result.html", context={
        "project": project,
        "parsed_sequence": parsed,
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
        rationale=rationale,
        verification_method=verification_method,
        impacts=[i.strip() for i in impacts.split(",") if i.strip()],
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

    if request.headers.get("HX-Request") == "true":
        return render_assumptions_list(request, project)
    return RedirectResponse(url=f"/project/{project_id}/assumptions", status_code=303)


@app.post("/project/{project_id}/assumptions/{assumption_id}/verify")
async def verify_assumption(request: Request, project_id: str, assumption_id: str):
    project = get_project(project_id)
    tracker, _assumption_set = assumption_set_for_project(project_id)
    tracker.verify_assumption(assumption_id, "UI", "Verified from assumptions page")
    return render_assumptions_list(request, project)


@app.post("/project/{project_id}/assumptions/{assumption_id}/invalidate")
async def invalidate_assumption(request: Request, project_id: str, assumption_id: str):
    project = get_project(project_id)
    tracker, _assumption_set = assumption_set_for_project(project_id)
    tracker.invalidate_assumption(assumption_id, "Invalidated from assumptions page")
    return render_assumptions_list(request, project)


@app.post("/project/{project_id}/assumptions/load-templates")
async def load_assumption_templates(request: Request, project_id: str):
    project = get_project(project_id)
    assumption_trackers[project_id] = create_bas_assumptions(project_id)
    return render_assumptions_list(request, project)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SETTINGS.host, port=SETTINGS.port)
