"""BAS Assistant Web UI - FastAPI Application."""

import csv
import json
import shutil
from io import StringIO
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from bas_assistant.models import (
    Project, ProjectMetadata, Equipment, EquipmentType, Point, PointKind,
    PointDirection, PointSource, Controller, Protocol, UnitSystem,
    ControllerNetworkAddress, ControllerIOCapacity
)
from bas_assistant.importers import CSVImporter, create_sample_csvs
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

# Paths
BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"

# Ensure directories exist
STATIC_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
(OUTPUT_DIR / "projects").mkdir(exist_ok=True)

# In-memory project store
projects: dict[str, Project] = {}

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
    # Save to disk
    project_dir = OUTPUT_DIR / "projects" / project.metadata.project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    with open(project_dir / "project.json", "w") as f:
        f.write(project.model_dump_json(indent=2))


def load_projects_from_disk() -> None:
    project_dir = OUTPUT_DIR / "projects"
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
    })


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
    return templates.TemplateResponse(request=request, name="graphics.html", context={
        "project": project,
        "graphics_result": result,
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
    tracker = create_bas_assumptions(project_id)
    return templates.TemplateResponse(request=request, name="assumptions.html", context={
        "project": project,
        "tracker": tracker,
    })


# ============================================================
# API Endpoints
# ============================================================

@app.post("/api/sample-data")
async def api_create_sample_data():
    create_sample_csvs(BASE_DIR / "examples")
    return {"message": "Sample CSVs created in /examples"}


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
    project_id: str,
    category: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    status: str = Form("pending"),
    impacts: str = Form(""),
):
    project = get_project(project_id)
    tracker = create_bas_assumptions(project_id)
    tracker.add_assumption(
        category=AssumptionCategory(category),
        title=title,
        description=description,
        impacts=[i.strip() for i in impacts.split(",") if i.strip()],
    )
    return RedirectResponse(url=f"/project/{project_id}/assumptions", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
