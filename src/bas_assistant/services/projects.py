"""Project repository services."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import delete, desc, select

from bas_assistant.database import ControllerRecord, DatabaseManager, EquipmentRecord, PointRecord, ProjectRecord
from bas_assistant.models import Project


class JsonProjectRepository:
    """Project persistence repository backed by JSON files with relational indexing."""

    def __init__(self, data_dir: Path, db: DatabaseManager | None = None) -> None:
        self.data_dir = data_dir
        self.db = db
        self.project_dir = self.data_dir / "projects"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Project] = {}

    def list_projects(self) -> dict[str, Project]:
        """Return all cached and on-disk projects."""
        if not self._cache:
            self.load_from_disk()
        return dict(self._cache)

    def get(self, project_id: str) -> Project | None:
        """Return a project by ID."""
        if project_id in self._cache:
            return self._cache[project_id]
        project_file = self.project_dir / project_id / "project.json"
        if self.db is not None and not project_file.exists():
            with self.db.session() as session:
                record = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
                if record is not None and record.source_path:
                    project_file = Path(record.source_path)
        if not project_file.exists():
            return None
        project = self._load_project_file(project_file)
        self._cache[project_id] = project
        return project

    def list_summaries(self) -> list[ProjectRecord]:
        """Return persisted project summary records from the database when available."""
        if self.db is None:
            return []
        with self.db.session() as session:
            return list(session.scalars(select(ProjectRecord).order_by(desc(ProjectRecord.updated_at), ProjectRecord.name)))

    def save(self, project: Project) -> None:
        """Persist and index a project."""
        self._cache[project.metadata.project_id] = project
        project_dir = self.project_dir / project.metadata.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        project_file = project_dir / "project.json"
        project_file.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        if self.db is not None:
            self._upsert_project_index(project, project_file)

    def load_from_disk(self) -> dict[str, Project]:
        """Load all project definitions from disk."""
        loaded: dict[str, Project] = {}
        for project_file in self.project_dir.glob("*/project.json"):
            project = self._load_project_file(project_file)
            loaded[project.metadata.project_id] = project
            if self.db is not None:
                self._upsert_project_index(project, project_file)
        self._cache = loaded
        return dict(self._cache)

    def clear_cache(self) -> None:
        """Reset in-memory cache."""
        self._cache.clear()

    def _load_project_file(self, project_file: Path) -> Project:
        return Project.model_validate(json.loads(project_file.read_text(encoding="utf-8")))

    def _upsert_project_index(self, project: Project, project_file: Path) -> None:
        if self.db is None:
            return
        with self.db.session() as session:
            record = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project.metadata.project_id))
            metadata_json = project.metadata.model_dump(mode="json")
            if record is None:
                session.add(
                    ProjectRecord(
                        project_id=project.metadata.project_id,
                        name=project.metadata.name,
                        client=project.metadata.client,
                        location=project.metadata.location,
                        status=project.validation_status,
                        source_path=str(project_file),
                        metadata_json=metadata_json,
                    )
                )
                session.flush()
                project_record = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project.metadata.project_id))
            else:
                record.name = project.metadata.name
                record.client = project.metadata.client
                record.location = project.metadata.location
                record.status = project.validation_status
                record.source_path = str(project_file)
                record.metadata_json = metadata_json
                project_record = record

            if project_record is None:
                return

            session.execute(delete(EquipmentRecord).where(EquipmentRecord.project_id == project_record.id))
            session.execute(delete(PointRecord).where(PointRecord.project_id == project_record.id))
            session.execute(delete(ControllerRecord).where(ControllerRecord.project_id == project_record.id))

            for equipment in project.equipment:
                session.add(
                    EquipmentRecord(
                        project_id=project_record.id,
                        equipment_key=equipment.id,
                        equipment_type=equipment.type.value,
                        display_name=equipment.subtype or equipment.id,
                        parent_equipment_key=equipment.parent_equipment_id,
                        status=equipment.status,
                        payload_json=equipment.model_dump(mode="json"),
                    )
                )

            for point in project.points:
                session.add(
                    PointRecord(
                        project_id=project_record.id,
                        equipment_key=point.equipment_id,
                        controller_key=point.controller_id,
                        point_name=point.name,
                        point_kind=point.kind.value,
                        direction=point.direction.value,
                        units=point.units,
                        payload_json=point.model_dump(mode="json"),
                    )
                )

            for controller in project.controllers:
                primary_protocol = controller.protocols[0].value if controller.protocols else None
                session.add(
                    ControllerRecord(
                        project_id=project_record.id,
                        controller_key=controller.id,
                        controller_type=controller.type,
                        protocol=primary_protocol,
                        payload_json=controller.model_dump(mode="json"),
                    )
                )
