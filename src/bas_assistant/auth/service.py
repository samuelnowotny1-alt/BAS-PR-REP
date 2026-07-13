"""Authentication service layer."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from bas_assistant.config import Settings
from bas_assistant.database import DatabaseManager, UserAccount, UserRole

from .schemas import UserIdentity
from .security import hash_password, verify_password


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
            return UserIdentity(id=user.id, username=user.username, email=user.email, role=user.role)

    def get_user(self, user_id: int) -> UserIdentity | None:
        """Return a persisted user identity."""
        with self.db.session() as session:
            user = session.get(UserAccount, user_id)
            if user is None or not user.is_active:
                return None
            return UserIdentity(id=user.id, username=user.username, email=user.email, role=user.role)
