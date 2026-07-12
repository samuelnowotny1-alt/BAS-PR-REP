#!/usr/bin/env python3
"""
Demo project loader for BAS Assistant.
Loads the sample HVAC project on first run or on demand.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
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


def load_demo_project(data_dir: Path, examples_dir: Path) -> Project:
    """Load or create the demo HVAC project."""
    
    project_dir = data_dir / "projects" / "demo-hvac-project"
    project_file = project_dir / "project.json"
    
    if project_file.exists():
        print(f"Loading existing demo project from {project_file}")
        with open(project_file) as f:
            data = json.load(f)
        return Project.model_validate(data)
    
    print("Creating new demo project...")
    
    # Ensure sample CSVs exist
    create_sample_csvs(examples_dir)
    
    # Create project
    metadata = ProjectMetadata(
        project_id="demo-hvac-project",
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
    
    # Equipment schedule
    equip_file = examples_dir / "equipment_schedule.csv"
    if equip_file.exists():
        result = importer.import_equipment_schedule(equip_file, "equip_schedule_demo")
        print(f"  Equipment: {result.message}")
        if result.errors:
            for e in result.errors:
                print(f"    ERROR: {e}")
        if result.warnings:
            for w in result.warnings:
                print(f"    WARN: {w}")
    
    # Point list
    points_file = examples_dir / "point_list.csv"
    if points_file.exists():
        result = importer.import_point_list(points_file, "point_list_demo")
        print(f"  Points: {result.message}")
        if result.errors:
            for e in result.errors:
                print(f"    ERROR: {e}")
        if result.warnings:
            for w in result.warnings:
                print(f"    WARN: {w}")
    
    # Controller schedule
    ctrl_file = examples_dir / "controller_schedule.csv"
    if ctrl_file.exists():
        result = importer.import_controller_schedule(ctrl_file, "ctrl_schedule_demo")
        print(f"  Controllers: {result.message}")
        if result.errors:
            for e in result.errors:
                print(f"    ERROR: {e}")
        if result.warnings:
            for w in result.warnings:
                print(f"    WARN: {w}")
    
    # Save project
    project_dir.mkdir(parents=True, exist_ok=True)
    with open(project_file, "w") as f:
        f.write(project.model_dump_json(indent=2))
    
    print(f"Demo project saved to {project_file}")
    print(f"  Equipment: {len(project.equipment)}")
    print(f"  Points: {len(project.points)}")
    print(f"  Controllers: {len(project.controllers)}")
    
    return project


def generate_outputs(project: Project, output_dir: Path) -> None:
    """Generate all outputs for the demo project."""
    
    project_output_dir = output_dir / "demo-hvac-project"
    project_output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\nGenerating demo outputs...")
    
    # Validation
    engine = ValidationEngine()
    report = engine.validate(project)
    print(f"  Validation: {len(report.errors)} errors, {len(report.warnings)} warnings")
    
    # Gap analysis
    gap_report = analyze_gaps(project)
    print(f"  Gap Analysis: {gap_report.total_count} gaps found")
    
    # Checkout sheets
    checkout_dir = project_output_dir / "checkout"
    checkout_dir.mkdir(parents=True, exist_ok=True)
    result = generate_checkout_sheets(project, checkout_dir)
    print(f"  Checkout: {result['sheet_count']} sheets")
    
    # Reports
    reports_dir = project_output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    paths = generate_reports(project, reports_dir)
    print(f"  Reports: {len(paths)} files")
    
    # Graphics
    graphics_dir = project_output_dir / "graphics"
    graphics_dir.mkdir(parents=True, exist_ok=True)
    result = generate_graphics(project, graphics_dir)
    total_graphics = sum(len(v) for v in result.values())
    print(f"  Graphics: {total_graphics} files")
    
    # Logic
    logic_dir = project_output_dir / "logic"
    logic_dir.mkdir(parents=True, exist_ok=True)
    result = generate_logic(project, logic_dir)
    total_logic = sum(len(v) for v in result.values())
    print(f"  Logic: {total_logic} files")
    
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
        result = exporter.export(vendor_dir)
        if result.success:
            print(f"  Export {vendor_name}: {len(result.files)} files")
        else:
            print(f"  Export {vendor_name}: FAILED - {result.message}")
    
    print("\n✅ Demo project fully loaded and ready!")


def main():
    import os
    
    # Get directories from environment or defaults
    base_dir = Path(__file__).parent.parent
    data_dir = Path(os.environ.get("BAS_DATA_DIR", base_dir / "data"))
    output_dir = Path(os.environ.get("BAS_OUTPUT_DIR", base_dir / "ui" / "output"))
    examples_dir = base_dir / "examples"
    
    # Load demo project
    project = load_demo_project(data_dir, examples_dir)
    
    # Generate all outputs
    generate_outputs(project, output_dir)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
