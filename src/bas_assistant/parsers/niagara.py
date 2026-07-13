"""Niagara and PX upload parsers."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

from bas_assistant.generators.px_graphics import PXFile
from bas_assistant.models import Controller, Equipment, EquipmentType, Point, PointDirection, PointKind, PointSource, Project, Protocol
from bas_assistant.models.equipment import EquipmentRelationship
from bas_assistant.services.artifact_links import ArtifactEntityLink


@dataclass(slots=True)
class ArtifactParseResult:
    """Result of parsing a Niagara-related artifact."""

    parsed: bool
    parser_name: str
    equipment_added: int = 0
    points_added: int = 0
    controllers_added: int = 0
    links: list[ArtifactEntityLink] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class NiagaraStationGraph:
    """Minimal station graph extracted from Niagara slot paths."""

    controller_points: list[dict[str, str]] = field(default_factory=list)
    equipment_paths: list[list[str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "controller_points": list(self.controller_points),
            "equipment_paths": [list(path) for path in self.equipment_paths],
        }


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
        controllers_added = 0
        parsed_pages = 0
        links: list[ArtifactEntityLink] = []
        warnings: list[str] = []
        manifest_hits = 0
        with zipfile.ZipFile(file_path) as archive, TemporaryDirectory() as temp_dir:
            for member in archive.namelist():
                target_path = Path(temp_dir) / Path(member).name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(archive.read(member))
                lower_member = member.lower()
                if lower_member.endswith(".px"):
                    parsed_pages += 1
                    result = self._parse_px_file(project=project, file_path=target_path)
                    equipment_added += result.equipment_added
                    points_added += result.points_added
                    controllers_added += result.controllers_added
                    links.extend(result.links)
                    warnings.extend(result.warnings)
                    continue
                if lower_member.endswith((".json", ".txt", ".csv", ".xml")):
                    result = self._parse_station_metadata_file(project=project, file_path=target_path)
                    if result.parsed:
                        manifest_hits += 1
                    equipment_added += result.equipment_added
                    points_added += result.points_added
                    controllers_added += result.controllers_added
                    links.extend(result.links)
                    warnings.extend(result.warnings)
        return ArtifactParseResult(
            parsed=parsed_pages > 0 or manifest_hits > 0,
            parser_name="niagara_station_archive",
            equipment_added=equipment_added,
            points_added=points_added,
            controllers_added=controllers_added,
            links=links,
            warnings=warnings,
            details={
                "parsed_px_pages": parsed_pages,
                "parsed_metadata_files": manifest_hits,
                "controllers_added": controllers_added,
            },
        )

    def _parse_px_file(self, *, project: Project, file_path: Path) -> ArtifactParseResult:
        px_file = PXFile.load(file_path)
        equipment_id = self._infer_equipment_id(file_path)
        equipment = project.get_equipment(equipment_id)
        equipment_added = 0
        if equipment is None:
            equipment = Equipment(
                id=equipment_id,
                type=EquipmentType.CUSTOM,
                subtype="NiagaraPX",
                provenance={
                    "source_type": "px",
                    "source_name": file_path.name,
                    "parser": "niagara_px",
                },
            )
            project.add_equipment(equipment)
            equipment_added = 1

        point_names = set()
        links: list[ArtifactEntityLink] = [
            ArtifactEntityLink(
                entity_type="equipment",
                entity_key=equipment_id,
                parser_name="niagara_px",
                metadata={"source_name": file_path.name},
            )
        ]
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
                    provenance={
                        "source_type": "px",
                        "source_name": file_path.name,
                        "binding_ord": point_name,
                        "parser": "niagara_px",
                    },
                )
            )
            equipment.add_point(normalized_name)
            points_added += 1
            links.append(
                ArtifactEntityLink(
                    entity_type="point",
                    entity_key=normalized_name,
                    parser_name="niagara_px",
                    metadata={"binding_ord": point_name, "source_name": file_path.name},
                )
            )

        return ArtifactParseResult(
            parsed=True,
            parser_name="niagara_px",
            equipment_added=equipment_added,
            points_added=points_added,
            links=links,
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

    def _parse_station_metadata_file(self, *, project: Project, file_path: Path) -> ArtifactParseResult:
        suffix = file_path.suffix.lower()
        try:
            if suffix == ".json":
                return self._parse_json_manifest(project=project, file_path=file_path)
            if suffix == ".xml":
                return self._parse_xml_manifest(project=project, file_path=file_path)
            return self._parse_text_manifest(project=project, file_path=file_path)
        except Exception as exc:
            return ArtifactParseResult(
                parsed=False,
                parser_name="niagara_station_manifest",
                warnings=[f"{file_path.name}: {exc}"],
            )

    def _parse_json_manifest(self, *, project: Project, file_path: Path) -> ArtifactParseResult:
        import json

        payload = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
        text = json.dumps(payload)
        return self._parse_manifest_text(project=project, text=text, source_name=file_path.name)

    def _parse_xml_manifest(self, *, project: Project, file_path: Path) -> ArtifactParseResult:
        root = ET.fromstring(file_path.read_text(encoding="utf-8", errors="ignore"))
        text = self._flatten_station_xml(root)
        return self._parse_manifest_text(project=project, text=text, source_name=file_path.name)

    def _parse_text_manifest(self, *, project: Project, file_path: Path) -> ArtifactParseResult:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return self._parse_manifest_text(project=project, text=text, source_name=file_path.name)

    def _parse_manifest_text(self, *, project: Project, text: str, source_name: str) -> ArtifactParseResult:
        equipment_added = 0
        points_added = 0
        controllers_added = 0
        station_tree_hits = 0
        links: list[ArtifactEntityLink] = []

        for controller_id in sorted(set(re.findall(r"\b(?:JACE|MEC|MPC|VAVC|CTRL|UC)-?[A-Z0-9]+\b", text, flags=re.IGNORECASE))):
            normalized_controller = controller_id.upper()
            if project.get_controller(normalized_controller) is None:
                project.add_controller(
                    Controller(
                        id=normalized_controller,
                        type="niagara",
                        protocols=[Protocol.BACNET_IP],
                        provenance={
                            "source_type": "station_metadata",
                            "source_name": source_name,
                            "parser": "niagara_station_manifest",
                        },
                    )
                )
                controllers_added += 1
            links.append(
                ArtifactEntityLink(
                    entity_type="controller",
                    entity_key=normalized_controller,
                    parser_name="niagara_station_manifest",
                    metadata={"source_name": source_name},
                )
            )

        for equipment_id in sorted(set(re.findall(r"\b(?:AHU|RTU|VAV|FCU|CHWP|HWP|EF|SF|RF)-?\d+\b", text, flags=re.IGNORECASE))):
            normalized_equipment = equipment_id.upper()
            if project.get_equipment(normalized_equipment) is None:
                project.add_equipment(
                    Equipment(
                        id=normalized_equipment,
                        type=self._infer_equipment_type(normalized_equipment),
                        subtype="NiagaraStation",
                        provenance={
                            "source_type": "station_metadata",
                            "source_name": source_name,
                            "parser": "niagara_station_manifest",
                        },
                    )
                )
                equipment_added += 1
            links.append(
                ArtifactEntityLink(
                    entity_type="equipment",
                    entity_key=normalized_equipment,
                    parser_name="niagara_station_manifest",
                    metadata={"source_name": source_name},
                )
            )

        for equipment_id, point_name in re.findall(
            r"\b((?:AHU|RTU|VAV|FCU|CHWP|HWP|EF|SF|RF)-?\d+)[\s:_/-]+([A-Za-z][A-Za-z0-9_]{1,40})",
            text,
            flags=re.IGNORECASE,
        ):
            normalized_equipment = equipment_id.upper()
            if project.get_equipment(normalized_equipment) is None:
                project.add_equipment(
                    Equipment(
                        id=normalized_equipment,
                        type=self._infer_equipment_type(normalized_equipment),
                        subtype="NiagaraStation",
                        provenance={
                            "source_type": "station_metadata",
                            "source_name": source_name,
                            "parser": "niagara_station_manifest",
                        },
                    )
                )
                equipment_added += 1
            normalized_point = f"{normalized_equipment}_{re.sub(r'[^A-Za-z0-9_]+', '_', point_name).upper()}"
            if project.get_point(normalized_point) is not None:
                continue
            project.add_point(
                Point(
                    name=normalized_point,
                    equipment_id=normalized_equipment,
                    kind=self._infer_point_kind(point_name),
                    direction=PointDirection.INPUT,
                    source=PointSource.BACNET,
                    description=f"Imported from Niagara station metadata in {source_name}",
                    provenance={
                        "source_type": "station_metadata",
                        "source_name": source_name,
                        "parser": "niagara_station_manifest",
                    },
                )
            )
            equipment = project.get_equipment(normalized_equipment)
            if equipment is not None:
                equipment.add_point(normalized_point)
            points_added += 1
            links.append(
                ArtifactEntityLink(
                    entity_type="point",
                    entity_key=normalized_point,
                    parser_name="niagara_station_manifest",
                    metadata={"source_name": source_name},
                )
            )

        tree_result = self._parse_station_tree_text(project=project, text=text, source_name=source_name)
        equipment_added += tree_result.equipment_added
        points_added += tree_result.points_added
        controllers_added += tree_result.controllers_added
        station_tree_hits = int(tree_result.details.get("station_tree_hits", 0))
        links.extend(tree_result.links)

        return ArtifactParseResult(
            parsed=equipment_added > 0 or points_added > 0 or controllers_added > 0 or station_tree_hits > 0,
            parser_name="niagara_station_manifest",
            equipment_added=equipment_added,
            points_added=points_added,
            controllers_added=controllers_added,
            links=links,
            details={
                "controllers_added": controllers_added,
                "source_name": source_name,
                "station_tree_hits": station_tree_hits,
                "station_graph": tree_result.details.get("station_graph", {}),
            },
        )

    def _infer_equipment_type(self, equipment_id: str) -> EquipmentType:
        prefix = equipment_id.split("-", 1)[0].upper()
        mapping = {
            "AHU": EquipmentType.AHU,
            "RTU": EquipmentType.RTU,
            "VAV": EquipmentType.VAV,
            "FCU": EquipmentType.FAN_COIL,
            "CHWP": EquipmentType.PUMP_CHW,
            "HWP": EquipmentType.PUMP_HW,
            "EF": EquipmentType.EXHAUST_FAN,
            "SF": EquipmentType.SUPPLY_FAN,
            "RF": EquipmentType.RETURN_FAN,
        }
        return mapping.get(prefix, EquipmentType.CUSTOM)

    def _flatten_station_xml(self, root: ET.Element) -> str:
        """Extract Niagara-relevant identifiers from structured XML hierarchies."""
        tokens: list[str] = []
        self._collect_xml_tokens(root, tokens=tokens, path_segments=[])
        return " ".join(token for token in tokens if token)

    def _collect_xml_tokens(
        self,
        element: ET.Element,
        *,
        tokens: list[str],
        path_segments: list[str],
    ) -> None:
        normalized_tag = element.tag.split("}", 1)[-1]
        attrs = {key.split("}", 1)[-1]: value for key, value in element.attrib.items()}
        segment = (
            attrs.get("name")
            or attrs.get("slot")
            or attrs.get("slotName")
            or attrs.get("displayName")
            or normalized_tag
        )
        next_segments = [*path_segments, segment]

        text_value = (element.text or "").strip()
        if text_value:
            tokens.append(text_value)
        tokens.append(normalized_tag)
        for value in attrs.values():
            if value:
                tokens.append(value)

        path_text = "/".join(part for part in next_segments if part)
        if path_text:
            tokens.append(path_text)

        if "Drivers" in next_segments and "Points" in next_segments:
            point_index = next_segments.index("Points")
            point_path = "/".join(next_segments[next_segments.index("Drivers"):])
            tokens.append(f"station:|slot:/{point_path}")
            if point_index >= 1 and point_index + 1 < len(next_segments):
                controller = next_segments[point_index - 1]
                point_name = next_segments[-1]
                tokens.append(f"{controller} {point_name}")

        if "Config" in next_segments and "Equipment" in next_segments:
            equipment_path = "/".join(next_segments[next_segments.index("Config"):])
            tokens.append(f"station:|slot:/{equipment_path}")
            tokens.append(next_segments[-1])

        for child in list(element):
            self._collect_xml_tokens(child, tokens=tokens, path_segments=next_segments)

    def _parse_station_tree_text(self, *, project: Project, text: str, source_name: str) -> ArtifactParseResult:
        controller_map: dict[str, str] = {}
        equipment_added = 0
        points_added = 0
        controllers_added = 0
        station_tree_hits = 0
        links: list[ArtifactEntityLink] = []
        station_graph = NiagaraStationGraph()

        for controller_id in sorted(set(re.findall(r"station:\|slot:/Drivers/[^/\s]+/([A-Za-z0-9_-]+)", text))):
            normalized_controller = controller_id.upper()
            controller_map[normalized_controller] = normalized_controller
            if project.get_controller(normalized_controller) is None:
                project.add_controller(
                    Controller(
                        id=normalized_controller,
                        type="niagara_station",
                        protocols=[Protocol.BACNET_IP],
                        provenance={
                            "source_type": "station_tree",
                            "source_name": source_name,
                            "parser": "niagara_station_tree",
                        },
                    )
                )
                controllers_added += 1
            else:
                controller = project.get_controller(normalized_controller)
                if controller is not None:
                    controller.provenance = {
                        "source_type": "station_tree",
                        "source_name": source_name,
                        "parser": "niagara_station_tree",
                    }
            station_tree_hits += 1
            links.append(
                ArtifactEntityLink(
                    entity_type="controller",
                    entity_key=normalized_controller,
                    parser_name="niagara_station_tree",
                    metadata={"source_name": source_name},
                )
            )

        point_pattern = re.compile(
            r"station:\|slot:/Drivers/[^/\s]+/([A-Za-z0-9_-]+)/Points/([A-Za-z0-9_:\-]+)"
        )
        for controller_id, raw_point_name in point_pattern.findall(text):
            normalized_controller = controller_id.upper()
            point_token = re.sub(r"[^A-Za-z0-9_\-]+", "_", raw_point_name).strip("_").upper()
            equipment_id = self._infer_equipment_id_from_point_token(point_token)
            if equipment_id is None:
                continue
            equipment = project.get_equipment(equipment_id)
            if equipment is None:
                equipment = Equipment(
                    id=equipment_id,
                    type=self._infer_equipment_type(equipment_id),
                    subtype="NiagaraStationTree",
                    controller_id=normalized_controller,
                    provenance={
                        "source_type": "station_tree",
                        "source_name": source_name,
                        "parser": "niagara_station_tree",
                    },
                )
                project.add_equipment(equipment)
                equipment_added += 1
            else:
                if equipment.controller_id is None:
                    equipment.controller_id = normalized_controller
                equipment.provenance = {
                    "source_type": "station_tree",
                    "source_name": source_name,
                    "parser": "niagara_station_tree",
                }
            controller = project.get_controller(normalized_controller)
            if controller is not None:
                controller.add_equipment(equipment_id)
            links.append(
                ArtifactEntityLink(
                    entity_type="equipment",
                    entity_key=equipment_id,
                    parser_name="niagara_station_tree",
                    metadata={"controller_id": normalized_controller, "source_name": source_name},
                )
            )
            normalized_point = point_token
            if project.get_point(normalized_point) is None:
                project.add_point(
                    Point(
                        name=normalized_point,
                        equipment_id=equipment_id,
                        controller_id=normalized_controller,
                        kind=self._infer_point_kind(raw_point_name),
                        direction=PointDirection.INPUT,
                        source=PointSource.BACNET,
                        description=f"Imported from Niagara station tree in {source_name}",
                        provenance={
                            "source_type": "station_tree",
                            "source_name": source_name,
                            "point_ord": raw_point_name,
                            "parser": "niagara_station_tree",
                        },
                    )
                )
                points_added += 1
            else:
                point = project.get_point(normalized_point)
                if point is not None:
                    point.controller_id = normalized_controller
                    point.provenance = {
                        "source_type": "station_tree",
                        "source_name": source_name,
                        "point_ord": raw_point_name,
                        "parser": "niagara_station_tree",
                    }
            equipment.add_point(normalized_point)
            if controller is not None:
                controller.add_point(normalized_point)
            station_graph.controller_points.append(
                {
                    "controller_id": normalized_controller,
                    "equipment_id": equipment_id,
                    "point_name": normalized_point,
                }
            )
            station_tree_hits += 1
            links.append(
                ArtifactEntityLink(
                    entity_type="point",
                    entity_key=normalized_point,
                    parser_name="niagara_station_tree",
                    metadata={"controller_id": normalized_controller, "source_name": source_name},
                )
            )

        for equipment_path in self._extract_equipment_paths(text):
            station_graph.equipment_paths.append(equipment_path)
        for equipment_id in sorted({path[-1] for path in station_graph.equipment_paths if path}):
            normalized_equipment = equipment_id.upper()
            if project.get_equipment(normalized_equipment) is None:
                project.add_equipment(
                    Equipment(
                        id=normalized_equipment,
                        type=self._infer_equipment_type(normalized_equipment),
                        subtype="NiagaraStationTree",
                        provenance={
                            "source_type": "station_tree",
                            "source_name": source_name,
                            "parser": "niagara_station_tree",
                        },
                    )
                )
                equipment_added += 1
            else:
                equipment = project.get_equipment(normalized_equipment)
                if equipment is not None:
                    equipment.provenance = {
                        "source_type": "station_tree",
                        "source_name": source_name,
                        "parser": "niagara_station_tree",
                    }
            station_tree_hits += 1
            links.append(
                ArtifactEntityLink(
                    entity_type="equipment",
                    entity_key=normalized_equipment,
                    parser_name="niagara_station_tree",
                    metadata={"source_name": source_name},
                )
            )
        self._apply_station_graph(project=project, graph=station_graph)

        return ArtifactParseResult(
            parsed=station_tree_hits > 0,
            parser_name="niagara_station_tree",
            equipment_added=equipment_added,
            points_added=points_added,
            controllers_added=controllers_added,
            links=links,
            details={
                "station_tree_hits": station_tree_hits,
                "station_graph": station_graph.as_dict(),
            },
        )

    def _infer_equipment_id_from_point_token(self, point_name: str) -> str | None:
        match = re.match(r"((?:AHU|RTU|VAV|FCU|CHWP|HWP|EF|SF|RF)-?\d+)_", point_name)
        if match:
            return match.group(1).upper()
        return None

    def _extract_equipment_paths(self, text: str) -> list[list[str]]:
        equipment_paths: list[list[str]] = []
        for raw_path in re.findall(r"station:\|slot:/Config/Equipment/([^\s]+)", text):
            segments = [segment for segment in raw_path.split("/") if segment]
            equipment_segments = [
                segment.upper()
                for segment in segments
                if re.fullmatch(r"(?:AHU|RTU|VAV|FCU|CHWP|HWP|EF|SF|RF)-?\d+", segment, flags=re.IGNORECASE)
            ]
            if equipment_segments:
                equipment_paths.append(equipment_segments)
        return equipment_paths

    def _apply_station_graph(self, *, project: Project, graph: NiagaraStationGraph) -> None:
        for path in graph.equipment_paths:
            for parent_id, child_id in zip(path, path[1:]):
                parent = project.get_equipment(parent_id)
                child = project.get_equipment(child_id)
                if parent is None or child is None:
                    continue
                child.parent_equipment_id = parent_id
                if child_id not in parent.child_equipment_ids:
                    parent.child_equipment_ids.append(child_id)
                if not any(
                    relationship.type == "contains" and relationship.target_equipment_id == child_id
                    for relationship in parent.relationships
                ):
                    parent.relationships.append(
                        EquipmentRelationship(
                            type="contains",
                            target_equipment_id=child_id,
                            description="Derived from Niagara station hierarchy",
                        )
                    )
