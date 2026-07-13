"""Application service container."""

from __future__ import annotations

from dataclasses import dataclass

from bas_assistant.auth import AuthenticationService
from bas_assistant.config import Settings
from bas_assistant.database import DatabaseManager
from bas_assistant.services import DashboardService, JsonProjectRepository, UploadService


@dataclass(slots=True)
class ApplicationContainer:
    """Shared application services."""

    settings: Settings
    db: DatabaseManager
    auth: AuthenticationService
    projects: JsonProjectRepository
    uploads: UploadService
    dashboard: DashboardService


def build_container(settings: Settings) -> ApplicationContainer:
    """Construct the application container."""
    db = DatabaseManager(settings)
    db.create_all()
    projects = JsonProjectRepository(settings.data_dir, db=db)
    uploads = UploadService(settings.uploads_dir, db=db)
    auth = AuthenticationService(db, settings)
    auth.ensure_bootstrap_admin()
    dashboard = DashboardService(
        db=db,
        project_repository=projects,
        upload_service=uploads,
        health_report_factory=lambda: {},
    )
    return ApplicationContainer(
        settings=settings,
        db=db,
        auth=auth,
        projects=projects,
        uploads=uploads,
        dashboard=dashboard,
    )
