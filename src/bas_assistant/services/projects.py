"""Project repository services."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from bas_assistant.database import DatabaseManager, ProjectRecord
from bas_assistant.models import Project


class JsonProjectRepository:
    """Project persistence repository backed by JSON files with DB indexing."""

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
        if not project_file.exists():
            return None
        project = self._load_project_file(project_file)
        self._cache[project_id] = project
        return project

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
                return
            record.name = project.metadata.name
            record.client = project.metadata.client
            record.location = project.metadata.location
            record.status = project.validation_status
            record.source_path = str(project_file)
            record.metadata_json = metadata_json
