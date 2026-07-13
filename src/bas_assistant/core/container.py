"""Application service container."""

from __future__ import annotations

from dataclasses import dataclass

from bas_assistant.auth import AuthenticationService
from bas_assistant.config import Settings
from bas_assistant.database import DatabaseManager
from bas_assistant.parsers import NiagaraArtifactParser
from bas_assistant.services import DashboardService, JsonProjectRepository, KnowledgeIngestionService, ProjectQueryService, UploadService


@dataclass(slots=True)
class ApplicationContainer:
    """Shared application services."""

    settings: Settings
    db: DatabaseManager
    auth: AuthenticationService
    projects: JsonProjectRepository
    project_queries: ProjectQueryService
    uploads: UploadService
    knowledge: KnowledgeIngestionService
    parsers: NiagaraArtifactParser
    dashboard: DashboardService


def build_container(settings: Settings) -> ApplicationContainer:
    """Construct the application container."""
    db = DatabaseManager(settings)
    db.create_all()
    projects = JsonProjectRepository(settings.data_dir, db=db)
    project_queries = ProjectQueryService(db)
    uploads = UploadService(settings.uploads_dir, db=db)
    knowledge = KnowledgeIngestionService(db)
    parsers = NiagaraArtifactParser()
    auth = AuthenticationService(db, settings)
    auth.ensure_bootstrap_admin()
    dashboard = DashboardService(
        db=db,
        project_repository=projects,
        project_queries=project_queries,
        upload_service=uploads,
        health_report_factory=lambda: {},
    )
    return ApplicationContainer(
        settings=settings,
        db=db,
        auth=auth,
        projects=projects,
        project_queries=project_queries,
        uploads=uploads,
        knowledge=knowledge,
        parsers=parsers,
        dashboard=dashboard,
    )
