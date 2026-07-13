"""Read-oriented project query services backed by the relational store."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from bas_assistant.auth.schemas import UserIdentity
from bas_assistant.database import (
    ArtifactObjectLinkRecord,
    ControllerRecord,
    DatabaseManager,
    DocumentRecord,
    EquipmentRecord,
    KnowledgeRecord,
    PointRecord,
    ProjectMembershipRecord,
    ProjectRecord,
    TaskRecord,
    UploadRecord,
    UserAccount,
)
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
                "client": project.client,
                "location": project.location,
                "metadata": dict(project.metadata_json or {}),
                "equipment_count": equipment_count,
                "points_count": point_count,
                "controllers_count": controller_count,
                "validation_status": project.status,
            }

    def detail_view(self, project_id: str) -> dict[str, object] | None:
        """Return a DB-backed detail view for a project."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return None
            equipment_records = list(
                session.scalars(
                    select(EquipmentRecord)
                    .where(EquipmentRecord.project_id == project.id)
                    .order_by(EquipmentRecord.equipment_key)
                )
            )
            point_count = session.scalar(
                select(func.count()).select_from(PointRecord).where(PointRecord.project_id == project.id)
            ) or 0
            controller_count = session.scalar(
                select(func.count()).select_from(ControllerRecord).where(ControllerRecord.project_id == project.id)
            ) or 0
            documents = list(
                session.scalars(
                    select(DocumentRecord)
                    .where(DocumentRecord.project_id == project.id)
                    .order_by(DocumentRecord.created_at.desc())
                    .limit(8)
                )
            )
            uploads = list(
                session.scalars(
                    select(UploadRecord)
                    .where(UploadRecord.project_id == project.id)
                    .order_by(UploadRecord.created_at.desc())
                    .limit(8)
                )
            )
            knowledge = list(
                session.scalars(
                    select(KnowledgeRecord)
                    .where(KnowledgeRecord.project_id == project.id)
                    .order_by(KnowledgeRecord.created_at.desc())
                    .limit(8)
                )
            )
            tasks = list(
                session.scalars(
                    select(TaskRecord)
                    .where(TaskRecord.project_id == project.id)
                    .order_by(TaskRecord.updated_at.desc(), TaskRecord.created_at.desc())
                    .limit(8)
                )
            )
            memberships = list(
                session.execute(
                    select(UserAccount.username, ProjectMembershipRecord.access_level)
                    .join(ProjectMembershipRecord, ProjectMembershipRecord.user_id == UserAccount.id)
                    .where(ProjectMembershipRecord.project_id == project.id)
                    .order_by(UserAccount.username)
                )
            )

        equipment_view = []
        for record in equipment_records:
            payload = dict(record.payload_json or {})
            equipment_view.append(
                {
                    "id": record.equipment_key,
                    "type": record.equipment_type,
                    "building": payload.get("building"),
                    "controller_id": payload.get("controller_id"),
                    "graphic_sections": ((payload.get("template") or {}).get("parameters") or {}).get("graphic_sections", ""),
                    "point_count": len(payload.get("point_names", [])),
                    "status": record.status,
                    "provenance": dict(payload.get("provenance") or {}),
                }
            )

        return {
            "project_id": project.project_id,
            "name": project.name,
            "client": project.client,
            "location": project.location,
            "metadata": dict(project.metadata_json or {}),
            "validation_status": project.status,
            "equipment_count": len(equipment_records),
            "point_count": int(point_count),
            "controller_count": int(controller_count),
            "source_document_count": len(documents),
            "equipment": equipment_view,
            "documents": [
                {
                    "name": record.name,
                    "document_type": record.document_type,
                    "created_at": record.created_at,
                }
                for record in documents
            ],
            "uploads": [
                {
                    "filename": record.filename,
                    "category": record.category,
                    "status": record.status,
                    "created_at": record.created_at,
                }
                for record in uploads
            ],
            "knowledge": [
                {
                    "source_name": record.source_name,
                    "source_type": record.source_type,
                    "status": record.status,
                    "chunk_count": record.chunk_count,
                }
                for record in knowledge
            ],
            "tasks": [
                {
                    "id": record.id,
                    "task_type": record.task_type,
                    "status": record.status,
                    "updated_at": record.updated_at,
                }
                for record in tasks
            ],
            "memberships": [
                {
                    "username": username,
                    "access_level": access_level,
                }
                for username, access_level in memberships
            ],
        }

    def equipment_detail(self, project_id: str, equipment_id: str) -> dict[str, object] | None:
        """Return detailed view data for an equipment object."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return None
            record = session.scalar(
                select(EquipmentRecord).where(
                    EquipmentRecord.project_id == project.id,
                    EquipmentRecord.equipment_key == equipment_id,
                )
            )
            if record is None:
                return None
            point_records = list(
                session.scalars(
                    select(PointRecord)
                    .where(PointRecord.project_id == project.id, PointRecord.equipment_key == equipment_id)
                    .order_by(PointRecord.point_name)
                )
            )
        payload = dict(record.payload_json or {})
        return {
            "entity_type": "equipment",
            "project_id": project_id,
            "title": equipment_id,
            "subtitle": record.equipment_type,
            "payload": payload,
            "linked_points": [point.point_name for point in point_records],
        }

    def point_detail(self, project_id: str, point_name: str) -> dict[str, object] | None:
        """Return detailed view data for a point object."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return None
            record = session.scalar(
                select(PointRecord).where(
                    PointRecord.project_id == project.id,
                    PointRecord.point_name == point_name,
                )
            )
            if record is None:
                return None
        return {
            "entity_type": "point",
            "project_id": project_id,
            "title": point_name,
            "subtitle": record.point_kind,
            "payload": dict(record.payload_json or {}),
            "linked_points": [],
        }

    def controller_detail(self, project_id: str, controller_id: str) -> dict[str, object] | None:
        """Return detailed view data for a controller object."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return None
            record = session.scalar(
                select(ControllerRecord).where(
                    ControllerRecord.project_id == project.id,
                    ControllerRecord.controller_key == controller_id,
                )
            )
            if record is None:
                return None
        return {
            "entity_type": "controller",
            "project_id": project_id,
            "title": controller_id,
            "subtitle": record.controller_type or "controller",
            "payload": dict(record.payload_json or {}),
            "linked_points": list((record.payload_json or {}).get("owned_point_names", [])),
        }

    def activity_view(self, project_id: str) -> dict[str, object] | None:
        """Return project activity history including task status transitions."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return None
            tasks = list(
                session.scalars(
                    select(TaskRecord)
                    .where(TaskRecord.project_id == project.id)
                    .order_by(TaskRecord.updated_at.desc(), TaskRecord.created_at.desc())
                    .limit(40)
                )
            )
            uploads = list(
                session.scalars(
                    select(UploadRecord)
                    .where(UploadRecord.project_id == project.id)
                    .order_by(UploadRecord.created_at.desc())
                    .limit(20)
                )
            )
        return {
            "project_id": project.project_id,
            "project_name": project.name,
            "tasks": [self._task_to_view(task) for task in tasks],
            "uploads": [
                {
                    "filename": upload.filename,
                    "category": upload.category,
                    "status": upload.status,
                    "created_at": upload.created_at,
                    "metadata": dict(upload.metadata_json or {}),
                }
                for upload in uploads
            ],
        }

    def memberships_view(self, project_id: str) -> dict[str, object] | None:
        """Return project membership management data."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return None
            users = list(session.scalars(select(UserAccount).order_by(UserAccount.username)))
            memberships = list(
                session.scalars(
                    select(ProjectMembershipRecord).where(ProjectMembershipRecord.project_id == project.id)
                )
            )
        membership_map = {membership.user_id: membership.access_level for membership in memberships}
        return {
            "project_id": project.project_id,
            "project_name": project.name,
            "users": [
                {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "is_active": user.is_active,
                    "access_level": membership_map.get(user.id, ""),
                }
                for user in users
            ],
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

    def _task_to_view(self, task: TaskRecord) -> dict[str, object]:
        result_json = dict(task.result_json or {})
        return {
            "id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "payload": dict(task.payload_json or {}),
            "result": result_json.get("result", {}),
            "error": result_json.get("error"),
            "status_history": list(result_json.get("status_history", [])),
        }

    def artifact_links_for_entity(self, project_id: str, entity_type: str, entity_key: str) -> list[dict[str, object]]:
        """Return explicit artifact links for an entity."""
        with self.db.session() as session:
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project_id))
            if project is None:
                return []
            rows = list(
                session.execute(
                    select(
                        ArtifactObjectLinkRecord.parser_name,
                        ArtifactObjectLinkRecord.relationship_type,
                        ArtifactObjectLinkRecord.metadata_json,
                        DocumentRecord.name,
                        DocumentRecord.document_type,
                    )
                    .join(DocumentRecord, ArtifactObjectLinkRecord.document_id == DocumentRecord.id)
                    .where(
                        ArtifactObjectLinkRecord.project_id == project.id,
                        ArtifactObjectLinkRecord.entity_type == entity_type,
                        ArtifactObjectLinkRecord.entity_key == entity_key,
                    )
                    .order_by(ArtifactObjectLinkRecord.created_at.desc())
                )
            )
        return [
            {
                "parser_name": parser_name,
                "relationship_type": relationship_type,
                "metadata": dict(metadata_json or {}),
                "document_name": document_name,
                "document_type": document_type,
            }
            for parser_name, relationship_type, metadata_json, document_name, document_type in rows
        ]
