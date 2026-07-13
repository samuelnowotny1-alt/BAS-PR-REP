"""Niagara and PX upload parsers."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from bas_assistant.generators.px_graphics import PXFile
from bas_assistant.models import Equipment, EquipmentType, Point, PointDirection, PointKind, PointSource, Project


@dataclass(slots=True)
class ArtifactParseResult:
    """Result of parsing a Niagara-related artifact."""

    parsed: bool
    parser_name: str
    equipment_added: int = 0
    points_added: int = 0
    warnings: list[str] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)


class NiagaraArtifactParser:
    """Parse PX pages and Niagara station archives into structured BAS objects."""

    SUPPORTED_SUFFIXES = {".px", ".zip"}

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, *, project: Project, file_path: Path) -> ArtifactParseResult:
        suffix = file_path.suffix.lower()
        if suffix == ".px":
            return self._parse_px_file(project=project, file_path=file_path)
        if suffix == ".zip":
            return self._parse_station_archive(project=project, file_path=file_path)
        return ArtifactParseResult(parsed=False, parser_name="niagara", warnings=["Unsupported artifact type"])

    def _parse_station_archive(self, *, project: Project, file_path: Path) -> ArtifactParseResult:
        equipment_added = 0
        points_added = 0
        parsed_pages = 0
        warnings: list[str] = []
        with zipfile.ZipFile(file_path) as archive, TemporaryDirectory() as temp_dir:
            for member in archive.namelist():
                if not member.lower().endswith(".px"):
                    continue
                parsed_pages += 1
                target_path = Path(temp_dir) / Path(member).name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(archive.read(member))
                result = self._parse_px_file(project=project, file_path=target_path)
                equipment_added += result.equipment_added
                points_added += result.points_added
                warnings.extend(result.warnings)
        return ArtifactParseResult(
            parsed=parsed_pages > 0,
            parser_name="niagara_station_archive",
            equipment_added=equipment_added,
            points_added=points_added,
            warnings=warnings,
            details={"parsed_px_pages": parsed_pages},
        )

    def _parse_px_file(self, *, project: Project, file_path: Path) -> ArtifactParseResult:
        px_file = PXFile.load(file_path)
        equipment_id = self._infer_equipment_id(file_path)
        equipment = project.get_equipment(equipment_id)
        equipment_added = 0
        if equipment is None:
            equipment = Equipment(id=equipment_id, type=EquipmentType.CUSTOM, subtype="NiagaraPX")
            project.add_equipment(equipment)
            equipment_added = 1

        point_names = set()
        if px_file.root_widget is not None:
            self._collect_point_names(px_file.root_widget, point_names)

        points_added = 0
        for point_name in sorted(point_names):
            normalized_name = f"{equipment_id}_{point_name}"
            if project.get_point(normalized_name) is not None:
                continue
            project.add_point(
                Point(
                    name=normalized_name,
                    equipment_id=equipment_id,
                    kind=self._infer_point_kind(point_name),
                    direction=PointDirection.INPUT,
                    source=PointSource.MANUAL,
                    description=f"Imported from PX binding {point_name}",
                )
            )
            equipment.add_point(normalized_name)
            points_added += 1

        return ArtifactParseResult(
            parsed=True,
            parser_name="niagara_px",
            equipment_added=equipment_added,
            points_added=points_added,
            details={
                "px_name": px_file.name,
                "widget_count": len(point_names),
                "variables": dict(px_file.variables),
            },
        )

    def _collect_point_names(self, widget, point_names: set[str]) -> None:
        for binding in widget.bindings:
            ord_value = str(binding.ord)
            point_name = self._extract_point_name(ord_value)
            if point_name:
                point_names.add(point_name)
        for child in widget.children:
            self._collect_point_names(child, point_names)

    def _extract_point_name(self, ord_value: str) -> str | None:
        cleaned = ord_value.split("?")[0].rstrip("/")
        candidate = cleaned.split("/")[-1].split("|")[-1].strip()
        if not candidate:
            return None
        normalized = re.sub(r"[^A-Za-z0-9_]+", "_", candidate).strip("_")
        return normalized or None

    def _infer_equipment_id(self, file_path: Path) -> str:
        normalized_stem = re.sub(
            r"^\d{8}T\d{6}Z-[A-F0-9]{8}-",
            "",
            file_path.stem.upper(),
        )
        stem = re.sub(r"[^A-Za-z0-9]+", "-", normalized_stem).strip("-")
        return stem or "PX-EQUIPMENT"

    def _infer_point_kind(self, point_name: str) -> PointKind:
        upper_name = point_name.upper()
        if any(token in upper_name for token in {"SP", "SETPOINT"}):
            return PointKind.SETPOINT
        if any(token in upper_name for token in {"CMD", "ENABLE", "VALVE", "DAMPER"}):
            return PointKind.ACTUATOR
        if any(token in upper_name for token in {"STATUS", "ALARM", "FAIL"}):
            return PointKind.STATUS
        return PointKind.SENSOR
