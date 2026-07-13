"""Authentication service layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select

from bas_assistant.config import Settings
from bas_assistant.database import DatabaseManager, ProjectMembershipRecord, ProjectRecord, UserAccount, UserRole

from .schemas import UserIdentity
from .security import hash_password, verify_password


@dataclass(slots=True)
class ManagedUser:
    """Administrative user summary."""

    id: int
    username: str
    email: str
    role: str
    is_active: bool
    assigned_projects: list[dict[str, str]]


class AuthenticationService:
    """Manage users and session authentication."""

    def __init__(self, db: DatabaseManager, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def ensure_bootstrap_admin(self) -> None:
        """Create the initial admin account if missing."""
        with self.db.session() as session:
            existing = session.scalar(select(UserAccount).where(UserAccount.username == self.settings.bootstrap_admin_username))
            if existing is not None:
                return
            session.add(
                UserAccount(
                    username=self.settings.bootstrap_admin_username,
                    email=self.settings.bootstrap_admin_email,
                    password_hash=hash_password(self.settings.bootstrap_admin_password),
                    role=UserRole.ADMIN.value,
                    is_active=True,
                )
            )

    def authenticate(self, username: str, password: str) -> UserIdentity | None:
        """Validate credentials and return a session identity."""
        with self.db.session() as session:
            user = session.scalar(select(UserAccount).where(UserAccount.username == username))
            if user is None or not user.is_active:
                return None
            if not verify_password(password, user.password_hash):
                return None
            user.last_login_at = datetime.now(timezone.utc)
            return UserIdentity(
                id=user.id,
                username=user.username,
                email=user.email,
                role=user.role,
                assigned_project_ids=self.project_ids_for_user(user.id),
            )

    def get_user(self, user_id: int) -> UserIdentity | None:
        """Return a persisted user identity."""
        with self.db.session() as session:
            user = session.get(UserAccount, user_id)
            if user is None or not user.is_active:
                return None
            return UserIdentity(
                id=user.id,
                username=user.username,
                email=user.email,
                role=user.role,
                assigned_project_ids=self.project_ids_for_user(user.id),
            )

    def list_users(self) -> list[ManagedUser]:
        """Return administrative user summaries."""
        with self.db.session() as session:
            users = list(session.scalars(select(UserAccount).order_by(UserAccount.username)))
            membership_rows = list(session.scalars(select(ProjectMembershipRecord)))
            projects_by_id = {project.id: project for project in session.scalars(select(ProjectRecord))}

        memberships_by_user: dict[int, list[dict[str, str]]] = {}
        for membership in membership_rows:
            project = projects_by_id.get(membership.project_id)
            if project is None:
                continue
            memberships_by_user.setdefault(membership.user_id, []).append(
                {
                    "project_id": project.project_id,
                    "project_name": project.name,
                    "access_level": membership.access_level,
                }
            )
        return [
            ManagedUser(
                id=user.id,
                username=user.username,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
                assigned_projects=memberships_by_user.get(user.id, []),
            )
            for user in users
        ]

    def create_user(
        self,
        *,
        username: str,
        email: str,
        password: str,
        role: str,
        is_active: bool = True,
        project_ids: list[str] | None = None,
        access_level: str | None = None,
    ) -> UserIdentity:
        """Create a new application user and optional project assignments."""
        with self.db.session() as session:
            existing = session.scalar(select(UserAccount).where(UserAccount.username == username))
            if existing is not None:
                raise ValueError(f"Username '{username}' already exists")
            email_existing = session.scalar(select(UserAccount).where(UserAccount.email == email))
            if email_existing is not None:
                raise ValueError(f"Email '{email}' already exists")
            user = UserAccount(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role=role,
                is_active=is_active,
            )
            session.add(user)
            session.flush()
            self._replace_memberships(
                session,
                user_id=user.id,
                project_ids=project_ids or [],
                access_level=access_level or self.default_access_level_for_role(role),
            )
            return UserIdentity(
                id=user.id,
                username=user.username,
                email=user.email,
                role=user.role,
                assigned_project_ids=self.project_ids_for_user(user.id),
            )

    def update_user(
        self,
        *,
        user_id: int,
        role: str,
        is_active: bool,
        project_ids: list[str] | None = None,
        access_level: str | None = None,
    ) -> ManagedUser:
        """Update an existing user and replace explicit project assignments."""
        with self.db.session() as session:
            user = session.get(UserAccount, user_id)
            if user is None:
                raise ValueError(f"User '{user_id}' not found")
            user.role = role
            user.is_active = is_active
            self._replace_memberships(
                session,
                user_id=user.id,
                project_ids=project_ids or [],
                access_level=access_level or self.default_access_level_for_role(role),
            )
        managed_user = next((managed for managed in self.list_users() if managed.id == user_id), None)
        if managed_user is None:
            raise ValueError(f"User '{user_id}' not found after update")
        return managed_user

    def project_ids_for_user(self, user_id: int) -> list[str]:
        """Return assigned project IDs for a user."""
        with self.db.session() as session:
            rows = list(
                session.execute(
                    select(ProjectRecord.project_id)
                    .join(ProjectMembershipRecord, ProjectMembershipRecord.project_id == ProjectRecord.id)
                    .where(ProjectMembershipRecord.user_id == user_id)
                    .order_by(ProjectRecord.project_id)
                )
            )
        return [row[0] for row in rows]

    def can_access_project(self, user: UserIdentity, project_id: str, *, write: bool = False) -> bool:
        """Return whether the user can access the project."""
        if user.role == UserRole.ADMIN.value:
            return True
        assigned_projects = set(user.assigned_project_ids)
        if assigned_projects:
            if project_id not in assigned_projects:
                return False
            if not write:
                return True
            membership_level = self.membership_level_for_user(user.id, project_id)
            return user.role == UserRole.ENGINEER.value and membership_level in {"editor", "owner"}
        if write:
            return user.role == UserRole.ENGINEER.value
        return user.role in {UserRole.ENGINEER.value, UserRole.TECHNICIAN.value, UserRole.VIEWER.value}

    def membership_level_for_user(self, user_id: int, project_id: str) -> str | None:
        """Return membership access level for a project assignment."""
        with self.db.session() as session:
            membership = session.scalar(
                select(ProjectMembershipRecord.access_level)
                .join(ProjectRecord, ProjectMembershipRecord.project_id == ProjectRecord.id)
                .where(ProjectMembershipRecord.user_id == user_id, ProjectRecord.project_id == project_id)
            )
        return membership

    def default_access_level_for_role(self, role: str) -> str:
        """Return the default project membership level for a role."""
        if role == UserRole.ENGINEER.value:
            return "editor"
        return "viewer"

    def _replace_memberships(
        self,
        session,
        *,
        user_id: int,
        project_ids: list[str],
        access_level: str,
    ) -> None:
        session.execute(delete(ProjectMembershipRecord).where(ProjectMembershipRecord.user_id == user_id))
        if not project_ids:
            return
        project_records = list(
            session.scalars(select(ProjectRecord).where(ProjectRecord.project_id.in_(project_ids)))
        )
        for project in project_records:
            session.add(
                ProjectMembershipRecord(
                    user_id=user_id,
                    project_id=project.id,
                    access_level=access_level,
                )
            )
