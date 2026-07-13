"""Authentication package exports."""

from .dependencies import get_current_user, require_authenticated_user, require_role
from .schemas import LoginCredentials, UserIdentity
from .security import hash_password, verify_password
from .service import AuthenticationService

__all__ = [
    "AuthenticationService",
    "LoginCredentials",
    "UserIdentity",
    "get_current_user",
    "hash_password",
    "require_authenticated_user",
    "require_role",
    "verify_password",
]
