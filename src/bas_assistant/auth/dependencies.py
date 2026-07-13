"""Authentication and authorization dependencies for FastAPI routes."""

from __future__ import annotations

from fastapi import HTTPException, Request

from .schemas import UserIdentity

READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}
ENGINEERING_WRITE_PATHS = (
    "/project/new",
    "/api/project/new",
    "/api/sample-data",
    "/api/load-demo",
)
PROJECT_WRITE_SEGMENTS = (
    "/import",
    "/validate",
    "/gaps",
    "/checkout",
    "/reports",
    "/graphics",
    "/logic",
    "/export",
    "/sequence",
    "/troubleshoot",
    "/assumptions",
)


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


def require_route_permission(request: Request) -> UserIdentity:
    """Require that the current user has permission for the current route and method."""
    user = require_authenticated_user(request)
    path = request.url.path
    method = request.method.upper()

    if path == "/logout":
        return user
    if method in READ_ONLY_METHODS:
        return user
    if user.role == "admin":
        return user
    if user.role == "engineer":
        return user
    if path in ENGINEERING_WRITE_PATHS:
        raise HTTPException(status_code=403, detail="Engineer or admin role required")
    if path.startswith("/project/") and any(segment in path for segment in PROJECT_WRITE_SEGMENTS):
        raise HTTPException(status_code=403, detail="Engineer or admin role required")
    if path.startswith("/api/"):
        raise HTTPException(status_code=403, detail="Engineer or admin role required")
    raise HTTPException(status_code=403, detail="Insufficient permissions")
