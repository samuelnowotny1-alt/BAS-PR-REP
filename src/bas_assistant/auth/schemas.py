"""Authentication schemas and DTOs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserIdentity(BaseModel):
    """User session identity."""

    id: int
    username: str
    email: str
    role: str
    assigned_project_ids: list[str] = Field(default_factory=list)


class LoginCredentials(BaseModel):
    """Incoming login payload."""

    username: str
    password: str
