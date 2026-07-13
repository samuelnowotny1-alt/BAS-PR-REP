"""Authentication schemas and DTOs."""

from __future__ import annotations

from pydantic import BaseModel


class UserIdentity(BaseModel):
    """User session identity."""

    id: int
    username: str
    email: str
    role: str


class LoginCredentials(BaseModel):
    """Incoming login payload."""

    username: str
    password: str
