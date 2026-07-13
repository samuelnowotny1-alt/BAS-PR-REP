"""Authentication dependencies for FastAPI routes."""

from __future__ import annotations

from fastapi import HTTPException, Request

from .schemas import UserIdentity


def get_current_user(request: Request) -> UserIdentity | None:
    """Return the authenticated user from the session if present."""
    session_user = request.scope.get("session", {}).get("user")
    if not session_user:
        return None
    return UserIdentity.model_validate(session_user)


def require_authenticated_user(request: Request) -> UserIdentity:
    """Require an authenticated session."""
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(request: Request, *roles: str) -> UserIdentity:
    """Require that the current user has one of the allowed roles."""
    user = require_authenticated_user(request)
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user
