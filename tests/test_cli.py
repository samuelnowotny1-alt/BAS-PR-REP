from click.testing import CliRunner

from bas_assistant.cli import main
from bas_assistant.models import Equipment, EquipmentType, Project, ProjectMetadata


def test_graphics_command_reports_mixed_output_types(tmp_path) -> None:
    project = Project(
        metadata=ProjectMetadata(project_id="CLI-TEST", name="CLI Graphics Test"),
        equipment=[Equipment(id="AHU-1", type=EquipmentType.AHU)],
        points=[],
        controllers=[],
    )
    project_path = tmp_path / "project.json"
    output_path = tmp_path / "graphics"
    project_path.write_text(project.model_dump_json(indent=2), encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "graphics",
            "--project",
            str(project_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "json: 2 files" in result.output
    assert "svg: 2 files" in result.output
    assert "niagara:" in result.output
    assert "summaries: 2 records" in result.output
    assert (output_path / "graphics_niagara.json").exists()
