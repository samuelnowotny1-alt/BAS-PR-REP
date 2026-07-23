"""Dashboard aggregation services."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from bas_assistant.auth.schemas import UserIdentity
from bas_assistant.database import (
    ControllerRecord,
    ConversationRecord,
    DatabaseManager,
    DocumentRecord,
    EquipmentRecord,
    KnowledgeRecord,
    PointRecord,
    ProjectRecord,
    TaskRecord,
)
from bas_assistant.runtime import build_health_report

from .projects import JsonProjectRepository
from .project_queries import ProjectQueryService
from .uploads import UploadService


@dataclass(slots=True)
class DashboardSnapshot:
    """Snapshot of dashboard state for the engineering home page."""

    project_count: int
    equipment_count: int
    point_count: int
    controller_count: int
    document_count: int
    knowledge_count: int
    conversation_count: int
    open_task_count: int
    recent_uploads: list[dict[str, object]]
    health: dict[str, object]
    projects: dict[str, dict[str, object]]
    total_object_count: int
    points_per_equipment: float
    controllers_per_project: float
    featured_project: dict[str, object] | None
    top_projects: list[dict[str, object]]


class DashboardService:
    """Build dashboard view models from persisted services."""

    def __init__(
        self,
        *,
        db: DatabaseManager,
        project_repository: JsonProjectRepository,
        project_queries: ProjectQueryService,
        upload_service: UploadService,
        health_report_factory,
    ) -> None:
        self.db = db
        self.project_repository = project_repository
        self.project_queries = project_queries
        self.upload_service = upload_service
        self.health_report_factory = health_report_factory

    def snapshot(self, user: UserIdentity | None = None) -> DashboardSnapshot:
        """Return the current dashboard snapshot."""
        scope = self.project_queries.scope_for_user(user)
        with self.db.session() as session:
            project_filter = (
                ProjectRecord.project_id.in_(scope.allowed_project_ids)
                if scope.allowed_project_ids is not None
                else None
            )
            project_statement = select(ProjectRecord).order_by(ProjectRecord.updated_at.desc(), ProjectRecord.name)
            if project_filter is not None:
                project_statement = project_statement.where(project_filter)
            project_records = list(session.scalars(project_statement))
            project_db_ids = [project.id for project in project_records]
            project_count = len(project_records)
            equipment_count = self._count_related(session, EquipmentRecord, project_db_ids)
            point_count = self._count_related(session, PointRecord, project_db_ids)
            controller_count = self._count_related(session, ControllerRecord, project_db_ids)
            document_count = self._count_related(session, DocumentRecord, project_db_ids)
            knowledge_count = self._count_related(session, KnowledgeRecord, project_db_ids)
            conversation_count = session.scalar(select(func.count()).select_from(ConversationRecord)) or 0
            open_task_count = session.scalar(
                select(func.count()).select_from(TaskRecord).where(TaskRecord.status != "completed")
            ) or 0
            projects = self.project_queries.project_cards_for_records(session, project_records)
        recent_uploads = [
            {
                "filename": upload.filename,
                "category": upload.category,
                "status": upload.status,
                "stored_path": upload.stored_path,
                "created_at": upload.created_at,
            }
            for upload in self.upload_service.list_recent_uploads(
                project_ids=sorted(scope.allowed_project_ids) if scope.allowed_project_ids is not None else None,
                limit=8,
            )
        ]
        project_cards = list(projects.values())
        total_object_count = equipment_count + point_count + controller_count
        points_per_equipment = round(point_count / equipment_count, 1) if equipment_count else 0.0
        controllers_per_project = round(controller_count / project_count, 1) if project_count else 0.0
        featured_project = project_cards[0] if project_cards else None
        top_projects = sorted(
            project_cards,
            key=lambda card: (
                int(card.get("point_count", 0)),
                int(card.get("equipment_count", 0)),
                int(card.get("controller_count", 0)),
                str(card.get("name", "")),
            ),
            reverse=True,
        )[:3]
        return DashboardSnapshot(
            project_count=project_count,
            equipment_count=equipment_count,
            point_count=point_count,
            controller_count=controller_count,
            document_count=document_count,
            knowledge_count=knowledge_count,
            conversation_count=conversation_count,
            open_task_count=open_task_count,
            recent_uploads=recent_uploads,
            health=self.health_report_factory(),
            projects=projects,
            total_object_count=total_object_count,
            points_per_equipment=points_per_equipment,
            controllers_per_project=controllers_per_project,
            featured_project=featured_project,
            top_projects=top_projects,
        )

    def _count_related(self, session, model, project_db_ids: list[int]) -> int:
        if not project_db_ids:
            return 0
        return session.scalar(
            select(func.count()).select_from(model).where(model.project_id.in_(project_db_ids))
        ) or 0
