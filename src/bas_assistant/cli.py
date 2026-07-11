"""CLI entry point for BAS Assistant."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from pathlib import Path

from .models import (
    Project,
    ProjectMetadata,
    Equipment,
    EquipmentType,
    Point,
    PointKind,
    PointDirection,
    PointSource,
    Controller,
    Protocol,
    UnitSystem,
)
from .importers import CSVImporter, create_sample_csvs
from .validation import ValidationEngine, BUILTIN_RULES
from .exporters import (
    NiagaraExporter,
    BACnetExporter,
    TridiumExporter,
    JCIExporter,
    SiemensExporter,
    HoneywellExporter,
)


console = Console()


@click.group()
@click.version_option(version="0.1.0")
def main():
    """BAS Programming Assistant - Deterministic import, validation, and generation for building automation systems."""
    pass


@main.command()
@click.option("--output-dir", "-o", default="./examples", help="Output directory for sample CSVs")
def init(output_dir: str):
    """Create sample CSV files for equipment, points, and controllers."""
    path = Path(output_dir)
    create_sample_csvs(path)
    console.print(Panel.fit(
        f"[green]Created sample CSVs in {path}[/green]\n"
        f"  - equipment_schedule.csv\n"
        f"  - point_list.csv\n"
        f"  - controller_schedule.csv",
        title="BAS Assistant Init",
    ))


@main.command()
@click.option("--project-id", "-p", required=True, help="Project ID")
@click.option("--name", "-n", required=True, help="Project name")
@click.option("--output", "-o", default="project.json", help="Output JSON file")
def new(project_id: str, name: str, output: str):
    """Create a new empty project."""
    metadata = ProjectMetadata(project_id=project_id, name=name)
    project = Project(metadata=metadata)

    with open(output, "w") as f:
        f.write(project.model_dump_json(indent=2))

    console.print(Panel.fit(
        f"[green]Created project {project_id}: {name}[/green]\nSaved to {output}",
        title="New Project",
    ))


@main.command()
@click.argument("project_file", type=click.Path(exists=True))
@click.option("--equipment", "-e", type=click.Path(exists=True), help="Equipment schedule CSV")
@click.option("--points", "-p", type=click.Path(exists=True), help="Point list CSV")
@click.option("--controllers", "-c", type=click.Path(exists=True), help="Controller schedule CSV")
@click.option("--output", "-o", type=click.Path(), help="Output project file (defaults to overwrite)")
def import_data(project_file: str, equipment: str, points: str, controllers: str, output: str):
    """Import data from CSV files into a project."""
    # Load project
    with open(project_file) as f:
        project = Project.model_validate_json(f.read())

    importer = CSVImporter(project)

    if equipment:
        console.print(f"[cyan]Importing equipment from {equipment}...[/cyan]")
        result = importer.import_equipment_schedule(Path(equipment), "equip_schedule_1")
        _print_import_result(result)

    if points:
        console.print(f"[cyan]Importing points from {points}...[/cyan]")
        result = importer.import_point_list(Path(points), "point_list_1")
        _print_import_result(result)

    if controllers:
        console.print(f"[cyan]Importing controllers from {controllers}...[/cyan]")
        result = importer.import_controller_schedule(Path(controllers), "ctrl_schedule_1")
        _print_import_result(result)

    # Save
    out_path = output or project_file
    with open(out_path, "w") as f:
        f.write(project.model_dump_json(indent=2))

    console.print(f"[green]Project saved to {out_path}[/green]")
    console.print(f"  Equipment: {len(project.equipment)}")
    console.print(f"  Points: {len(project.points)}")
    console.print(f"  Controllers: {len(project.controllers)}")


@main.command()
@click.argument("project_file", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output validation report JSON")
@click.option("--format", "-f", type=click.Choice(["table", "json"]), default="table", help="Report format")
def validate(project_file: str, output: str, format: str):
    """Validate a project against built-in rules."""
    with open(project_file) as f:
        project = Project.model_validate_json(f.read())

    engine = ValidationEngine()
    report = engine.validate(project)

    if format == "json":
        if output:
            with open(output, "w") as f:
                f.write(report.model_dump_json(indent=2))
        else:
            console.print(report.model_dump_json(indent=2))
    else:
        _print_validation_report(report)

    if output and format == "table":
        with open(output, "w") as f:
            f.write(report.model_dump_json(indent=2))

    # Exit code based on validation status
    if report.has_errors:
        raise SystemExit(1)


@main.command()
@click.argument("project_file", type=click.Path(exists=True))
def summary(project_file: str):
    """Show project summary."""
    with open(project_file) as f:
        project = Project.model_validate_json(f.read())

    console.print(Panel.fit(
        f"[bold]{project.metadata.name}[/bold] ({project.metadata.project_id})\n"
        f"Client: {project.metadata.client or 'N/A'}\n"
        f"Location: {project.metadata.location or 'N/A'}\n"
        f"Phase: {project.metadata.design_phase or 'N/A'}\n"
        f"Unit System: {project.metadata.unit_system.value}",
        title="Project Summary",
    ))

    # Equipment table
    if project.equipment:
        table = Table(title="Equipment")
        table.add_column("ID")
        table.add_column("Type")
        table.add_column("Controller")
        table.add_column("Points")
        table.add_column("Status")
        for equip in project.equipment:
            pts = project.get_points_for_equipment(equip.id)
            table.add_row(
                equip.id,
                equip.type.value,
                equip.controller_id or "—",
                str(len(pts)),
                equip.status,
            )
        console.print(table)

    # Controllers table
    if project.controllers:
        table = Table(title="Controllers")
        table.add_column("ID")
        table.add_column("Type")
        table.add_column("Protocols")
        table.add_column("Equipment")
        table.add_column("Points")
        table.add_column("I/O Util.")
        for ctrl in project.controllers:
            pts = project.get_points_for_controller(ctrl.id)
            util = ctrl.utilization_pct()
            table.add_row(
                ctrl.id,
                ctrl.type,
                ", ".join(p.value for p in ctrl.protocols),
                str(len(ctrl.serves_equipment_ids)),
                str(len(pts)),
                f"{util:.1f}%" if util is not None else "—",
            )
        console.print(table)

    # Points summary by kind
    if project.points:
        kind_counts = {}
        for pt in project.points:
            kind_counts[pt.kind.value] = kind_counts.get(pt.kind.value, 0) + 1

        table = Table(title="Points by Kind")
        table.add_column("Kind")
        table.add_column("Count")
        for kind, count in sorted(kind_counts.items()):
            table.add_row(kind, str(count))
        console.print(table)


def _print_import_result(result):
    """Print import result."""
    if result.success:
        console.print(f"  [green]✓[/green] {result.message}")
    else:
        console.print(f"  [red]✗[/red] {result.message}")

    for w in result.warnings:
        console.print(f"  [yellow]⚠[/yellow] {w}")
    for e in result.errors:
        console.print(f"  [red]✗[/red] {e}")


def _print_validation_report(report):
    """Print validation report as table."""
    console.print(Panel.fit(
        f"Project: {report.project_id}\n"
        f"Status: {'[red]INVALID[/red]' if report.has_errors else ('[yellow]WARNING[/yellow]' if report.has_warnings else '[green]VALID[/green]')}\n"
        f"Rules: {report.total_rules_run} | Objects: {report.total_objects_checked}\n"
        f"Errors: {len(report.errors)} | Warnings: {len(report.warnings)} | Infos: {len(report.infos)} | Passed: {len(report.passed)}",
        title="Validation Report",
    ))

    if report.errors:
        table = Table(title="Errors")
        table.add_column("Object")
        table.add_column("ID")
        table.add_column("Rule")
        table.add_column("Message")
        for r in report.errors:
            table.add_row(r.object_type, r.object_id, r.rule_id, r.message)
        console.print(table)

    if report.warnings:
        table = Table(title="Warnings")
        table.add_column("Object")
        table.add_column("ID")
        table.add_column("Rule")
        table.add_column("Message")
        for r in report.warnings:
            table.add_row(r.object_type, r.object_id, r.rule_id, r.message)
        console.print(table)


if __name__ == "__main__":
    main()


@main.command()
@click.option("--project", "-p", type=click.Path(exists=True), required=True, help="Project JSON file")
@click.option("--output", "-o", type=click.Path(), default="checkout", help="Output directory")
def checkout(project: str, output: str):
    """Generate checkout sheets."""
    console.print(f"[blue]Loading project:[/blue] {project}")
    
    import json
    with open(project) as f:
        data = json.load(f)
    
    proj = Project.model_validate(data)
    
    from .generators import generate_checkout_sheets
    result = generate_checkout_sheets(proj, Path(output))
    
    console.print(f"[green]✓[/green] Generated {result['sheet_count']} checkout sheets")
    console.print(f"  Markdown: {len(result['markdown'])} files")
    console.print(f"  Excel: {result['excel']}")


@main.command()
@click.option("--project", "-p", type=click.Path(exists=True), required=True, help="Project JSON file")
@click.option("--output", "-o", type=click.Path(), default="reports", help="Output directory")
def reports(project: str, output: str):
    """Generate submittal reports."""
    console.print(f"[blue]Loading project:[/blue] {project}")
    
    import json
    with open(project) as f:
        data = json.load(f)
    
    proj = Project.model_validate(data)
    
    from .generators import generate_reports
    paths = generate_reports(proj, Path(output))
    
    console.print(f"[green]✓[/green] Generated report package")
    for name, path in paths.items():
        console.print(f"  {name}: {path}")


@main.command()
@click.option("--project", "-p", type=click.Path(exists=True), required=True, help="Project JSON file")
@click.option("--output", "-o", type=click.Path(), default="graphics", help="Output directory")
def graphics(project: str, output: str):
    """Generate graphics definitions."""
    console.print(f"[blue]Loading project:[/blue] {project}")
    
    import json
    with open(project) as f:
        data = json.load(f)
    
    proj = Project.model_validate(data)
    
    from .generators import generate_graphics
    result = generate_graphics(proj, Path(output))
    
    console.print(f"[green]✓[/green] Generated graphics")
    for fmt, paths in result.items():
        console.print(f"  {fmt}: {len(paths)} files")


@main.command()
@click.option("--project", "-p", type=click.Path(exists=True), required=True, help="Project JSON file")
@click.option("--output", "-o", type=click.Path(), default="logic", help="Output directory")
def logic(project: str, output: str):
    """Generate control logic diagrams."""
    console.print(f"[blue]Loading project:[/blue] {project}")
    
    import json
    with open(project) as f:
        data = json.load(f)
    
    proj = Project.model_validate(data)
    
    from .generators import generate_logic
    result = generate_logic(proj, Path(output))
    
    console.print(f"[green]✓[/green] Generated logic diagrams")
    for fmt, paths in result.items():
        console.print(f"  {fmt}: {len(paths)} files")

@main.command()
@click.option("--project", "-p", type=click.Path(exists=True), required=True, help="Project JSON file")
@click.option("--output", "-o", type=click.Path(), default="export", help="Output directory")
@click.option("--format", "-f", type=click.Choice(["niagara", "bacnet", "all"]), default="all", help="Export format")
def export(project: str, output: str, format: str):
    """Export project to vendor formats."""
    console.print(f"[blue]Loading project:[/blue] {project}")

    import json
    with open(project) as f:
        data = json.load(f)

    proj = Project.model_validate(data)

    out_path = Path(output)
    out_path.mkdir(parents=True, exist_ok=True)

    if format in ("niagara", "all"):
        console.print("[cyan]Exporting to Niagara format...[/cyan]")
        from .exporters import export_niagara
        result = export_niagara(proj, out_path / "niagara")
        _print_export_result(result)

    if format in ("bacnet", "all"):
        console.print("[cyan]Exporting to BACnet format...[/cyan]")
        from .exporters import export_bacnet
        result = export_bacnet(proj, out_path / "bacnet")
        _print_export_result(result)

    console.print(f"[green]Export complete. Output in:[/green] {out_path}")


def _print_export_result(result):
    """Print export result."""
    if result.success:
        console.print(f"  [green]✓[/green] {result.message}")
    else:
        console.print(f"  [red]✗[/red] {result.message}")

    for f in result.files:
        console.print(f"    [cyan]{f}[/cyan]")
    for w in result.warnings:
        console.print(f"    [yellow]⚠[/yellow] {w}")
    for e in result.errors:
        console.print(f"    [red]✗[/red] {e}")
