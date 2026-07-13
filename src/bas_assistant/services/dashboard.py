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
            project_ids_statement = select(ProjectRecord.id)
            if project_filter is not None:
                project_ids_statement = project_ids_statement.where(project_filter)
            project_db_ids = list(session.scalars(project_ids_statement))
            project_count = len(project_db_ids)
            equipment_count = self._count_related(session, EquipmentRecord, project_db_ids)
            point_count = self._count_related(session, PointRecord, project_db_ids)
            controller_count = self._count_related(session, ControllerRecord, project_db_ids)
            document_count = self._count_related(session, DocumentRecord, project_db_ids)
            knowledge_count = self._count_related(session, KnowledgeRecord, project_db_ids)
            conversation_count = session.scalar(select(func.count()).select_from(ConversationRecord)) or 0
            open_task_count = session.scalar(
                select(func.count()).select_from(TaskRecord).where(TaskRecord.status != "completed")
            ) or 0

        projects = self.project_queries.list_project_cards(user)
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
        )

    def _count_related(self, session, model, project_db_ids: list[int]) -> int:
        if not project_db_ids:
            return 0
        return session.scalar(
            select(func.count()).select_from(model).where(model.project_id.in_(project_db_ids))
        ) or 0
