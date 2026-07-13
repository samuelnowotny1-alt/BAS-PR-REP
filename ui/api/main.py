"""BAS Assistant Web UI - FastAPI Application."""

import csv
import json
import shutil
from io import StringIO
from pathlib import Path
from typing import Optional, List
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

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

# Paths
import os
BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Use environment variables for data directories (Docker-friendly)
DATA_DIR = Path(os.environ.get("BAS_DATA_DIR", BASE_DIR / "data"))
OUTPUT_DIR = Path(os.environ.get("BAS_OUTPUT_DIR", BASE_DIR / "output"))

# Ensure directories exist
STATIC_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "projects").mkdir(parents=True, exist_ok=True)

# In-memory project store
projects: dict[str, Project] = {}
assumption_trackers: dict[str, AssumptionTracker] = {}
station_sync_passwords: dict[str, str] = {}

# FastAPI app
app = FastAPI(title="BAS Assistant", version="0.1.0")

# Static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# Helper functions
def get_project(project_id: str) -> Project:
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    return projects[project_id]


def save_project(project: Project) -> None:
    projects[project.metadata.project_id] = project
    project.update_timestamp()
    # Save to disk
    project_dir = DATA_DIR / "projects" / project.metadata.project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    with open(project_dir / "project.json", "w") as f:
        f.write(project.model_dump_json(indent=2))


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
    project_dir = DATA_DIR / "projects"
    if project_dir.exists():
        for project_file in project_dir.glob("*/project.json"):
            try:
                with open(project_file) as f:
                    data = json.load(f)
                project = Project.model_validate(data)
                projects[project.metadata.project_id] = project
            except Exception as e:
                print(f"Failed to load project {project_file}: {e}")


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


# Load projects on startup
load_projects_from_disk()


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

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"projects": projects})


@app.get("/project/new", response_class=HTMLResponse)
async def new_project_page(request: Request):
    return templates.TemplateResponse(request=request, name="project_new.html")


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
    return templates.TemplateResponse(request=request, name="project_detail.html", context={
        "project": project,
        "graphic_sections_for": equipment_graphic_sections,
        "graphic_section_errors_for": equipment_graphic_section_errors,
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
    })


@app.post("/project/{project_id}/import")
async def import_data(
    project_id: str,
    equipment_file: UploadFile | None = File(None),
    points_file: UploadFile | None = File(None),
    controllers_file: UploadFile | None = File(None),
):
    project = get_project(project_id)
    importer = CSVImporter(project)
    results = {}

    # Save uploaded files temporarily
    import tempfile
    import os

    if equipment_file and getattr(equipment_file, "filename", None):
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as f:
            content = await equipment_file.read()
            f.write(content)
            temp_path = f.name
        result = importer.import_equipment_schedule(Path(temp_path), "equip_upload")
        results["equipment"] = {"success": result.success, "message": result.message, "errors": result.errors, "warnings": result.warnings, "count": result.equipment_count}
        os.unlink(temp_path)

    if points_file and getattr(points_file, "filename", None):
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as f:
            content = await points_file.read()
            f.write(content)
            temp_path = f.name
        result = importer.import_point_list(Path(temp_path), "points_upload")
        results["points"] = {"success": result.success, "message": result.message, "errors": result.errors, "warnings": result.warnings, "count": result.points_count}
        os.unlink(temp_path)

    if controllers_file and getattr(controllers_file, "filename", None):
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as f:
            content = await controllers_file.read()
            f.write(content)
            temp_path = f.name
        result = importer.import_controller_schedule(Path(temp_path), "ctrl_upload")
        results["controllers"] = {"success": result.success, "message": result.message, "errors": result.errors, "warnings": result.warnings, "count": result.controllers_count}
        os.unlink(temp_path)

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
    project = get_project(project_id)
    return {
        "project_id": project.metadata.project_id,
        "name": project.metadata.name,
        "equipment_count": len(project.equipment),
        "points_count": len(project.points),
        "controllers_count": len(project.controllers),
        "validation_status": project.validation_status,
    }


@app.get("/api/project/{project_id}/equipment")
async def api_equipment_list(project_id: str):
    project = get_project(project_id)
    return [
        {
            "id": e.id,
            "type": e.type.value,
            "controller": e.controller_id,
            "points": len(e.point_names),
            "status": e.status,
        }
        for e in project.equipment
    ]


@app.get("/api/project/{project_id}/points")
async def api_points_list(project_id: str):
    project = get_project(project_id)
    return [
        {
            "name": p.name,
            "equipment": p.equipment_id,
            "kind": p.kind.value,
            "units": p.units,
            "controller": p.controller_id,
        }
        for p in project.points
    ]


@app.get("/api/project/{project_id}/controllers")
async def api_controllers_list(project_id: str):
    project = get_project(project_id)
    return [
        {
            "id": c.id,
            "type": c.type,
            "protocols": [p.value for p in c.protocols],
            "equipment": len(c.serves_equipment_ids),
            "points": len(c.owned_point_names),
        }
        for c in project.controllers
    ]


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
    uvicorn.run(app, host="0.0.0.0", port=8000)
