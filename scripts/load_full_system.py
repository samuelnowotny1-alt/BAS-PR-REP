#!/usr/bin/env python3
"""Provision and verify the canonical full-building HVAC project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from bas_assistant.emulation import BasEmulationLab
from bas_assistant.runtime import (
    _attach_demo_source_documents,
    _write_codex_station_runtime_files,
    generate_demo_outputs,
)
from bas_assistant.services.projects import JsonProjectRepository
from scripts.load_demo import load_demo_project


REQUIRED_SCENARIOS = (
    "occupied",
    "hot_humid",
    "morning_warmup",
    "freeze_alarm",
    "fan_failure",
)


def provision_full_system(
    *,
    project_id: str,
    project_name: str,
    data_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Create the full project, generate outputs, and verify operator workflows."""
    source_dir = data_dir / "projects" / project_id / "source_documents"
    source_dir.mkdir(parents=True, exist_ok=True)

    project = load_demo_project(
        data_dir,
        source_dir,
        project_id=project_id,
        project_name=project_name,
    )
    _write_codex_station_runtime_files(project, source_dir)
    _attach_demo_source_documents(
        project,
        project_id,
        source_dir,
        generated_documents_dir=source_dir,
    )
    JsonProjectRepository(data_dir).save(project)
    generate_demo_outputs(project, output_dir)

    lab = BasEmulationLab(project)
    scenario_results: dict[str, dict[str, object]] = {}
    for scenario_id in REQUIRED_SCENARIOS:
        snapshot = lab.set_scenario(scenario_id)
        snapshot = lab.step(steps=2)
        scenario_results[scenario_id] = {
            "tick": snapshot.tick,
            "weather": snapshot.weather,
            "alarms": snapshot.station["alarm_count"],
            "controllers": len(snapshot.station["controllers"]),
            "points": snapshot.station["point_count"],
        }

    graphics_dir = (
        output_dir
        / project_id
        / "exports"
        / "niagara"
        / f"{project_id}_wxf"
        / "graphics"
    )
    required_graphics = {
        "dashboard_main.px",
        "graphic_system_ahu-1.px",
        "graphic_system_cooling_plant.px",
        "graphic_system_heating_plant.px",
        "AHU-1.px",
        "VAV-101.px",
        "CHLR-1.px",
        "BLR-1.px",
    }
    generated_graphics = {path.name for path in graphics_dir.glob("*.px")}
    missing_graphics = sorted(required_graphics - generated_graphics)
    if missing_graphics:
        raise RuntimeError(
            "Full-system Niagara export is missing: "
            + ", ".join(missing_graphics)
        )

    report = {
        "project_id": project_id,
        "project_name": project.metadata.name,
        "equipment_count": len(project.equipment),
        "point_count": len(project.points),
        "controller_count": len(project.controllers),
        "source_document_count": len(project.source_documents),
        "graphics_count": len(generated_graphics),
        "required_graphics": sorted(required_graphics),
        "scenarios": scenario_results,
        "niagara_bog": str(
            output_dir
            / project_id
            / "exports"
            / "niagara"
            / f"{project_id}.bog"
        ),
    }
    report_path = output_dir / project_id / "full_system_validation.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default="imported-hvac-system")
    parser.add_argument("--project-name", default="Imported HVAC System")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = provision_full_system(
        project_id=args.project_id,
        project_name=args.project_name,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
