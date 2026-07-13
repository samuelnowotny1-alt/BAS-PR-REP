"""Application service container."""

from __future__ import annotations

from dataclasses import dataclass

from bas_assistant.auth import AuthenticationService
from bas_assistant.config import Settings
from bas_assistant.database import DatabaseManager
from bas_assistant.services import JsonProjectRepository


@dataclass(slots=True)
class ApplicationContainer:
    """Shared application services."""

    settings: Settings
    db: DatabaseManager
    auth: AuthenticationService
    projects: JsonProjectRepository


def build_container(settings: Settings) -> ApplicationContainer:
    """Construct the application container."""
    db = DatabaseManager(settings)
    db.create_all()
    projects = JsonProjectRepository(settings.data_dir, db=db)
    auth = AuthenticationService(db, settings)
    auth.ensure_bootstrap_admin()
    return ApplicationContainer(settings=settings, db=db, auth=auth, projects=projects)
