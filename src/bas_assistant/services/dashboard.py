"""Dashboard aggregation services."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from bas_assistant.database import (
    ControllerRecord,
    ConversationRecord,
    DatabaseManager,
    DocumentRecord,
    EquipmentRecord,
    KnowledgeRecord,
    ProjectRecord,
    TaskRecord,
)
from bas_assistant.runtime import build_health_report

from .projects import JsonProjectRepository
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
    projects: dict[str, object]


class DashboardService:
    """Build dashboard view models from persisted services."""

    def __init__(
        self,
        *,
        db: DatabaseManager,
        project_repository: JsonProjectRepository,
        upload_service: UploadService,
        health_report_factory,
    ) -> None:
        self.db = db
        self.project_repository = project_repository
        self.upload_service = upload_service
        self.health_report_factory = health_report_factory

    def snapshot(self) -> DashboardSnapshot:
        """Return the current dashboard snapshot."""
        with self.db.session() as session:
            project_count = session.scalar(select(func.count()).select_from(ProjectRecord)) or 0
            equipment_count = session.scalar(select(func.count()).select_from(EquipmentRecord)) or 0
            controller_count = session.scalar(select(func.count()).select_from(ControllerRecord)) or 0
            document_count = session.scalar(select(func.count()).select_from(DocumentRecord)) or 0
            knowledge_count = session.scalar(select(func.count()).select_from(KnowledgeRecord)) or 0
            conversation_count = session.scalar(select(func.count()).select_from(ConversationRecord)) or 0
            open_task_count = session.scalar(
                select(func.count()).select_from(TaskRecord).where(TaskRecord.status != "completed")
            ) or 0

        projects = self.project_repository.list_projects()
        point_count = sum(len(project.points) for project in projects.values())
        recent_uploads = [
            {
                "filename": upload.filename,
                "category": upload.category,
                "status": upload.status,
                "stored_path": upload.stored_path,
                "created_at": upload.created_at,
            }
            for upload in self.upload_service.list_recent_uploads(limit=8)
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
