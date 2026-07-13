"""Read-oriented project query services backed by the relational store."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from bas_assistant.auth.schemas import UserIdentity
from bas_assistant.database import ControllerRecord, DatabaseManager, EquipmentRecord, PointRecord, ProjectMembershipRecord, ProjectRecord


@dataclass(slots=True)
class ProjectQueryScope:
    """Project filter scope derived from the current user."""

    allowed_project_ids: set[str] | None


class ProjectQueryService:
    """Build project-facing read models from structured database records."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def scope_for_user(self, user: UserIdentity | None) -> ProjectQueryScope:
        """Return the relational filter scope for a user."""
        if user is None or user.role == "admin" or not user.assigned_project_ids:
            return ProjectQueryScope(allowed_project_ids=None)
        return ProjectQueryScope(allowed_project_ids=set(user.assigned_project_ids))

    def list_project_cards(self, user: UserIdentity | None = None) -> dict[str, dict[str, object]]:
        """Return dashboard-ready project card data."""
        scope = self.scope_for_user(user)
        with self.db.session() as session:
            project_statement = select(ProjectRecord).order_by(ProjectRecord.updated_at.desc(), ProjectRecord.name)
            project_statement = self._apply_scope(project_statement, scope)
            projects = list(session.scalars(project_statement))
            if not projects:
                return {}
            project_db_ids = [project.id for project in projects]
            equipment_counts = self._count_by_project(session, EquipmentRecord.project_id, EquipmentRecord, project_db_ids)
            point_counts = self._count_by_project(session, PointRecord.project_id, PointRecord, project_db_ids)
            controller_counts = self._count_by_project(session, ControllerRecord.project_id, ControllerRecord, project_db_ids)

        cards: dict[str, dict[str, object]] = {}
        for project in projects:
            metadata = project.metadata_json or {}
            cards[project.project_id] = {
                "project_id": project.project_id,
                "name": project.name,
                "client": project.client,
                "location": project.location,
                "status": project.status,
                "metadata": metadata,
                "equipment_count": equipment_counts.get(project.id, 0),
                "point_count": point_counts.get(project.id, 0),
                "controller_count": controller_counts.get(project.id, 0),
            }
        return cards

    def summary(self, project_id: str) -> dict[str, object] | None:
        """Return a summary view for a single project."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return None
            equipment_count = session.scalar(
                select(func.count()).select_from(EquipmentRecord).where(EquipmentRecord.project_id == project.id)
            ) or 0
            point_count = session.scalar(
                select(func.count()).select_from(PointRecord).where(PointRecord.project_id == project.id)
            ) or 0
            controller_count = session.scalar(
                select(func.count()).select_from(ControllerRecord).where(ControllerRecord.project_id == project.id)
            ) or 0
            return {
                "project_id": project.project_id,
                "name": project.name,
                "equipment_count": equipment_count,
                "points_count": point_count,
                "controllers_count": controller_count,
                "validation_status": project.status,
            }

    def equipment_list(self, project_id: str) -> list[dict[str, object]]:
        """Return structured equipment records for a project."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return []
            records = list(
                session.scalars(
                    select(EquipmentRecord)
                    .where(EquipmentRecord.project_id == project.id)
                    .order_by(EquipmentRecord.equipment_key)
                )
            )
        return [
            {
                "id": record.equipment_key,
                "type": record.equipment_type,
                "controller": record.payload_json.get("controller_id"),
                "points": len(record.payload_json.get("point_names", [])),
                "status": record.status,
            }
            for record in records
        ]

    def points_list(self, project_id: str) -> list[dict[str, object]]:
        """Return structured point records for a project."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return []
            records = list(
                session.scalars(
                    select(PointRecord)
                    .where(PointRecord.project_id == project.id)
                    .order_by(PointRecord.point_name)
                )
            )
        return [
            {
                "name": record.point_name,
                "equipment": record.equipment_key,
                "kind": record.point_kind,
                "units": record.units,
                "controller": record.controller_key,
            }
            for record in records
        ]

    def controllers_list(self, project_id: str) -> list[dict[str, object]]:
        """Return structured controller records for a project."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return []
            records = list(
                session.scalars(
                    select(ControllerRecord)
                    .where(ControllerRecord.project_id == project.id)
                    .order_by(ControllerRecord.controller_key)
                )
            )
        return [
            {
                "id": record.controller_key,
                "type": record.controller_type,
                "protocols": [record.protocol] if record.protocol else [],
                "equipment": len(record.payload_json.get("serves_equipment_ids", [])),
                "points": len(record.payload_json.get("owned_point_names", [])),
            }
            for record in records
        ]

    def count_project_memberships(self, project_id: str) -> int:
        """Return membership count for a project."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return 0
            return session.scalar(
                select(func.count()).select_from(ProjectMembershipRecord).where(ProjectMembershipRecord.project_id == project.id)
            ) or 0

    def _apply_scope(self, statement, scope: ProjectQueryScope):
        if scope.allowed_project_ids is None:
            return statement
        return statement.where(ProjectRecord.project_id.in_(scope.allowed_project_ids))

    def _count_by_project(self, session, column, model, project_db_ids: list[int]) -> dict[int, int]:
        rows = session.execute(
            select(column, func.count())
            .select_from(model)
            .where(column.in_(project_db_ids))
            .group_by(column)
        )
        counts: dict[int, int] = defaultdict(int)
        for project_id, count in rows:
            counts[project_id] = int(count)
        return counts
