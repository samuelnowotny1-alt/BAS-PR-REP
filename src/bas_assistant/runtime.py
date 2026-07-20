"""Runtime bootstrap helpers for BAS Assistant."""

from __future__ import annotations

import csv
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


def _write_demo_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> Path:
    """Write a deterministic CSV document for demo project seeding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _codex_station_seed_rows() -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, str]]]:
    """Build the focused AHU/VAV station dataset for the Codex demo project."""
    equipment_rows = [
        {
            "Equipment ID": "AHU-1",
            "Equipment Type": "AHU",
            "Subtype": "VAV",
            "Building": "Main",
            "Floor": "1",
            "Room": "Mechanical",
            "Served Area": "Floor 1 Office Wing",
            "Controller ID": "MPC-1",
            "Parent Equipment": "",
            "Child Equipment": "VAV-101,VAV-102,VAV-103,VAV-104",
            "Design CFM": "25000",
            "Design Tonnage": "60",
            "Design GPM": "120",
            "Design kW": "40",
            "Voltage": "460",
            "Phase": "3",
            "Status": "design",
            "Graphic Sections": "outside_air,mixed_air,filter,cooling_coil,heating_coil,supply_fan,return_fan,discharge",
            "Notes": "Primary office air handler used for live graphics preview and emulator testing.",
            "Tags": "ahu,airside,station-demo",
        },
        {
            "Equipment ID": "VAV-101",
            "Equipment Type": "VAV",
            "Subtype": "Single Duct Reheat",
            "Building": "Main",
            "Floor": "1",
            "Room": "Zone 101",
            "Served Area": "Office 101",
            "Controller ID": "VAV-101",
            "Parent Equipment": "AHU-1",
            "Child Equipment": "",
            "Design CFM": "1200",
            "Design Tonnage": "",
            "Design GPM": "4",
            "Design kW": "1.5",
            "Voltage": "120",
            "Phase": "1",
            "Status": "design",
            "Graphic Sections": "",
            "Notes": "Perimeter office VAV with reheat.",
            "Tags": "vav,zone,station-demo",
        },
        {
            "Equipment ID": "VAV-102",
            "Equipment Type": "VAV",
            "Subtype": "Single Duct Reheat",
            "Building": "Main",
            "Floor": "1",
            "Room": "Zone 102",
            "Served Area": "Office 102",
            "Controller ID": "VAV-102",
            "Parent Equipment": "AHU-1",
            "Child Equipment": "",
            "Design CFM": "1000",
            "Design Tonnage": "",
            "Design GPM": "3",
            "Design kW": "1.2",
            "Voltage": "120",
            "Phase": "1",
            "Status": "design",
            "Graphic Sections": "",
            "Notes": "Interior office VAV with reheat.",
            "Tags": "vav,zone,station-demo",
        },
        {
            "Equipment ID": "VAV-103",
            "Equipment Type": "VAV",
            "Subtype": "Single Duct Reheat",
            "Building": "Main",
            "Floor": "1",
            "Room": "Zone 103",
            "Served Area": "Conference 103",
            "Controller ID": "VAV-103",
            "Parent Equipment": "AHU-1",
            "Child Equipment": "",
            "Design CFM": "1500",
            "Design Tonnage": "",
            "Design GPM": "5",
            "Design kW": "1.8",
            "Voltage": "120",
            "Phase": "1",
            "Status": "design",
            "Graphic Sections": "",
            "Notes": "Conference VAV with reheat.",
            "Tags": "vav,conference,station-demo",
        },
        {
            "Equipment ID": "VAV-104",
            "Equipment Type": "VAV",
            "Subtype": "Fan Powered",
            "Building": "Main",
            "Floor": "1",
            "Room": "Zone 104",
            "Served Area": "Perimeter 104",
            "Controller ID": "VAV-104",
            "Parent Equipment": "AHU-1",
            "Child Equipment": "",
            "Design CFM": "800",
            "Design Tonnage": "",
            "Design GPM": "3",
            "Design kW": "1.0",
            "Voltage": "120",
            "Phase": "1",
            "Status": "design",
            "Graphic Sections": "",
            "Notes": "Fan-powered perimeter VAV for override testing.",
            "Tags": "vav,perimeter,station-demo",
        },
    ]

    point_templates: dict[str, list[tuple[str, str, str, str, str, float | None, float | None, str]]] = {
        "AHU-1": [
            ("SAT", "sensor", "input", "degF", "AI", 45.0, 95.0, "Supply air temperature"),
            ("DAT SP", "setpoint", "input", "degF", "AV", 50.0, 65.0, "Discharge air temperature setpoint"),
            ("MAT", "sensor", "input", "degF", "AI", 45.0, 95.0, "Mixed air temperature"),
            ("RAT", "sensor", "input", "degF", "AI", 65.0, 85.0, "Return air temperature"),
            ("OAT", "sensor", "input", "degF", "AI", -10.0, 110.0, "Outdoor air temperature"),
            ("OA HUM", "sensor", "input", "%RH", "AI", 10.0, 100.0, "Outdoor air humidity"),
            ("SF CMD", "actuator", "output", "%", "AO", 0.0, 100.0, "Supply fan speed command"),
            ("SF STATUS", "status", "input", "", "BI", None, None, "Supply fan proof"),
            ("SF VFD SPD", "sensor", "input", "%", "AI", 0.0, 100.0, "Supply fan VFD speed"),
            ("OA DAMPER", "actuator", "output", "%", "AO", 0.0, 100.0, "Outside air damper command"),
            ("RA DAMPER", "actuator", "output", "%", "AO", 0.0, 100.0, "Return air damper command"),
            ("EA DAMPER", "actuator", "output", "%", "AO", 0.0, 100.0, "Exhaust air damper command"),
            ("CLG VALVE", "actuator", "output", "%", "AO", 0.0, 100.0, "Cooling valve command"),
            ("HTG VALVE", "actuator", "output", "%", "AO", 0.0, 100.0, "Heating valve command"),
            ("DUCT SP", "sensor", "input", "inWC", "AI", 0.0, 5.0, "Supply duct static pressure"),
            ("FILTER DP", "sensor", "input", "inWC", "AI", 0.0, 3.0, "Filter differential pressure"),
            ("FREEZE STAT", "alarm", "input", "", "BI", None, None, "Freeze protection status"),
            ("DUCT SMOKE", "alarm", "input", "", "BI", None, None, "Duct smoke status"),
            ("SAF ALM", "alarm", "input", "", "BI", None, None, "Supply airflow alarm"),
        ],
        "VAV": [
            ("FLOW", "sensor", "input", "CFM", "AI", 0.0, 2000.0, "Measured airflow"),
            ("FLOW SP", "setpoint", "input", "CFM", "AV", 200.0, 1800.0, "Airflow setpoint"),
            ("DAMPER", "actuator", "output", "%", "AO", 0.0, 100.0, "Damper command"),
            ("ZT", "sensor", "input", "degF", "AI", 60.0, 85.0, "Zone temperature"),
            ("ZT SP", "setpoint", "input", "degF", "AV", 68.0, 75.0, "Zone temperature setpoint"),
            ("REHEAT CMD", "actuator", "output", "%", "AO", 0.0, 100.0, "Reheat command"),
            ("OCC", "status", "input", "", "BI", None, None, "Occupancy status"),
        ],
    }

    point_rows: list[dict[str, Any]] = []
    point_instance = 1
    for equipment_row in equipment_rows:
        equipment_id = equipment_row["Equipment ID"]
        equipment_type = equipment_row["Equipment Type"]
        point_specs = point_templates["AHU-1"] if equipment_id == "AHU-1" else point_templates[equipment_type]
        point_names: list[str] = []
        for suffix, kind, direction, units, object_type, range_min, range_max, description in point_specs:
            point_name = f"{equipment_id} {suffix}"
            point_names.append(point_name)
            point_rows.append(
                {
                    "Point Name": point_name,
                    "Equipment ID": equipment_id,
                    "Point Kind": kind,
                    "Direction": direction,
                    "Units": units,
                    "Unit System": "IP",
                    "Range Min": range_min if range_min is not None else "",
                    "Range Max": range_max if range_max is not None else "",
                    "Controller ID": equipment_row["Controller ID"],
                    "BACnet Object Type": object_type,
                    "BACnet Instance": point_instance,
                    "Modbus Register": "",
                    "Modbus Type": "",
                    "Source": "point_list",
                    "Source Reference": point_name,
                    "Description": description,
                    "Tags": f"{equipment_type.lower()},station-demo",
                }
            )
            point_instance += 1
        equipment_row["Points"] = ",".join(point_names)

    controller_rows = [
        {
            "Controller ID": "MPC-1",
            "Name": "Main Airside Controller 1",
            "Vendor": "Johnson Controls",
            "Model": "MPC-8000",
            "Firmware": "12.3",
            "Type": "MPC",
            "Protocols": "BACnet/IP",
            "IP Address": "192.168.10.11",
            "MS/TP MAC": "",
            "Network Number": "2001",
            "Panel Location": "Mechanical Room Panel MP-1",
            "Electrical Panel": "MP-1",
            "Circuit": "14",
            "Serves Equipment": "AHU-1",
            "Owned Points": ",".join(row["Point Name"] for row in point_rows if row["Controller ID"] == "MPC-1"),
            "Universal Inputs": "48",
            "Digital Inputs": "24",
            "Analog Outputs": "12",
            "Digital Outputs": "12",
            "Total Points": "96",
            "Status": "design",
            "Notes": "Primary airside controller for the live station demo.",
        },
    ]
    for index in range(101, 105):
        controller_id = f"VAV-{index}"
        controller_rows.append(
            {
                "Controller ID": controller_id,
                "Name": f"{controller_id} Terminal Controller",
                "Vendor": "Johnson Controls",
                "Model": "VAV-3000",
                "Firmware": "5.2",
                "Type": "VAV",
                "Protocols": "BACnet/MSTP",
                "IP Address": "",
                "MS/TP MAC": str(index - 90),
                "Network Number": "2001",
                "Panel Location": f"Zone {index} Ceiling",
                "Electrical Panel": "LP-1",
                "Circuit": str((index - 100) * 2 + 6),
                "Serves Equipment": controller_id,
                "Owned Points": ",".join(row["Point Name"] for row in point_rows if row["Controller ID"] == controller_id),
                "Universal Inputs": "4",
                "Digital Inputs": "2",
                "Analog Outputs": "2",
                "Digital Outputs": "2",
                "Total Points": "10",
                "Status": "design",
                "Notes": "Terminal controller on the AHU-1 branch trunk.",
            }
        )
    return equipment_rows, point_rows, controller_rows


def _write_codex_station_seed_files(seed_dir: Path) -> tuple[Path, Path, Path]:
    """Write the focused station CSV schedules used to seed the Codex demo."""
    equipment_rows, point_rows, controller_rows = _codex_station_seed_rows()
    equipment_fields = [
        "Equipment ID",
        "Equipment Type",
        "Subtype",
        "Building",
        "Floor",
        "Room",
        "Served Area",
        "Controller ID",
        "Parent Equipment",
        "Child Equipment",
        "Points",
        "Design CFM",
        "Design Tonnage",
        "Design GPM",
        "Design kW",
        "Voltage",
        "Phase",
        "Status",
        "Graphic Sections",
        "Notes",
        "Tags",
    ]
    point_fields = [
        "Point Name",
        "Equipment ID",
        "Point Kind",
        "Direction",
        "Units",
        "Unit System",
        "Range Min",
        "Range Max",
        "Controller ID",
        "BACnet Object Type",
        "BACnet Instance",
        "Modbus Register",
        "Modbus Type",
        "Source",
        "Source Reference",
        "Description",
        "Tags",
    ]
    controller_fields = [
        "Controller ID",
        "Name",
        "Vendor",
        "Model",
        "Firmware",
        "Type",
        "Protocols",
        "IP Address",
        "MS/TP MAC",
        "Network Number",
        "Panel Location",
        "Electrical Panel",
        "Circuit",
        "Serves Equipment",
        "Owned Points",
        "Universal Inputs",
        "Digital Inputs",
        "Analog Outputs",
        "Digital Outputs",
        "Total Points",
        "Status",
        "Notes",
    ]
    equipment_path = _write_demo_csv(seed_dir / "equipment_schedule.csv", equipment_fields, equipment_rows)
    points_path = _write_demo_csv(seed_dir / "point_list.csv", point_fields, point_rows)
    controllers_path = _write_demo_csv(seed_dir / "controller_schedule.csv", controller_fields, controller_rows)
    return equipment_path, points_path, controllers_path


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


def _write_codex_station_runtime_files(project: Project, seed_dir: Path) -> None:
    """Write station-facing runtime documents that match the focused emulator scenario."""
    from bas_assistant.emulation import BasEmulationLab

    lab = BasEmulationLab(project)
    snapshot = lab.snapshot()
    manifest = lab.manifest()
    fake_station_dir = seed_dir / "fake_station"

    controller_runtime_rows: list[dict[str, Any]] = []
    for controller in manifest.controllers:
        controller_runtime_rows.append(
            {
                "controller_id": controller.device_id,
                "display_name": controller.display_name,
                "protocol": controller.protocol,
                "address": controller.address or "",
                "network_number": controller.network_number or "",
                "point_count": controller.point_count,
                "vendor": controller.vendor or "",
                "model": controller.model or "",
                "status": "online",
                "served_equipment": ",".join(self_project_equipment for self_project_equipment in (project.get_controller(controller.device_id).serves_equipment_ids if project.get_controller(controller.device_id) else [])),
            }
        )
    _write_demo_csv(
        fake_station_dir / "controller_runtime.csv",
        [
            "controller_id",
            "display_name",
            "protocol",
            "address",
            "network_number",
            "point_count",
            "vendor",
            "model",
            "status",
            "served_equipment",
        ],
        controller_runtime_rows,
    )

    snapshot_rows: list[dict[str, Any]] = []
    for device in snapshot.devices:
        if device.role != "controller":
            continue
        for point in device.points:
            snapshot_rows.append(
                {
                    "timestamp": snapshot.generated_at.isoformat(),
                    "controller_id": device.device_id,
                    "point_name": point.point_name,
                    "present_value": point.present_value,
                    "units": point.units or "",
                    "writable": "yes" if point.writable else "no",
                }
            )
    _write_demo_csv(
        fake_station_dir / "station_point_snapshot.csv",
        ["timestamp", "controller_id", "point_name", "present_value", "units", "writable"],
        snapshot_rows,
    )

    trend_targets = [
        "AHU-1 SAT",
        "AHU-1 MAT",
        "AHU-1 OAT",
        "AHU-1 SF CMD",
        "VAV-101 ZT",
        "VAV-101 FLOW",
        "VAV-102 ZT",
        "VAV-103 ZT",
        "VAV-104 REHEAT CMD",
    ]
    trend_rows: list[dict[str, Any]] = []
    for _ in range(6):
        stepped = lab.step()
        current_points = {
            point.point_name: point
            for device in stepped.devices
            if device.role == "controller"
            for point in device.points
        }
        for point_name in trend_targets:
            point = current_points.get(point_name)
            if point is None:
                continue
            trend_rows.append(
                {
                    "timestamp": stepped.generated_at.isoformat(),
                    "point_name": point_name,
                    "value": point.present_value,
                    "units": point.units or "",
                    "tick": stepped.tick,
                }
            )
    _write_demo_csv(
        fake_station_dir / "station_trends.csv",
        ["timestamp", "point_name", "value", "units", "tick"],
        trend_rows,
    )

    alarm_rows = [
        {
            "timestamp": snapshot.generated_at.isoformat(),
            "priority": "normal",
            "equipment_id": "AHU-1",
            "point_name": "AHU-1 SAF ALM",
            "message": "Alarm clear at seed load. Hot and humid weather profile active for testing.",
            "state": "normal",
        },
        {
            "timestamp": snapshot.generated_at.isoformat(),
            "priority": "info",
            "equipment_id": "VAV-104",
            "point_name": "VAV-104 REHEAT CMD",
            "message": "Fan-powered VAV included for controller override simulation.",
            "state": "normal",
        },
    ]
    _write_demo_csv(
        fake_station_dir / "station_alarms.csv",
        ["timestamp", "priority", "equipment_id", "point_name", "message", "state"],
        alarm_rows,
    )


def create_codex_demo_project(
    project_id: str,
    project_name: str,
    seed_dir: Path,
) -> Project:
    """Create the focused Codex station project used by the live graphics demo."""
    from bas_assistant.importers import CSVImporter

    equipment_path, points_path, controllers_path = _write_codex_station_seed_files(seed_dir)
    project = Project(metadata=_demo_project_metadata(project_id, project_name))
    importer = CSVImporter(project)
    importer.import_equipment_schedule(equipment_path, f"{project_id}_equipment")
    importer.import_point_list(points_path, f"{project_id}_points")
    importer.import_controller_schedule(controllers_path, f"{project_id}_controllers")
    _write_codex_station_runtime_files(project, seed_dir)
    _attach_demo_source_documents(
        project,
        project_id,
        seed_dir,
        generated_documents_dir=seed_dir,
    )
    return project


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
    generated_documents_dir = demo_generated_documents_dir(projects_repo, project_id, examples_dir)
    if project_id == "codex-test-project":
        project = create_codex_demo_project(project_id, project_name, generated_documents_dir)
    else:
        project = create_demo_project(
            project_id,
            project_name,
            examples_dir,
            generated_documents_dir=generated_documents_dir,
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
