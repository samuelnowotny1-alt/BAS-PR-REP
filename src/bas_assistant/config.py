"""Application configuration for BAS Assistant."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="BAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "BAS Assistant"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_dir: Path = Field(default_factory=lambda: Path("logs"))
    log_file_name: str = "bas-assistant.log"
    data_dir: Path = Field(default_factory=lambda: Path("ui/data"))
    output_dir: Path = Field(default_factory=lambda: Path("ui/output"))
    static_dir: Path = Field(default_factory=lambda: Path("ui/static"))
    templates_dir: Path = Field(default_factory=lambda: Path("ui/templates"))
    uploads_dir: Path = Field(default_factory=lambda: Path("uploads"))
    database_url: str = "sqlite:///./data/bas_assistant.db"
    session_secret: str = "change-me-in-production"
    session_cookie_name: str = "bas_assistant_session"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123!"
    bootstrap_admin_email: str = "admin@example.com"

    @property
    def log_file(self) -> Path:
        """Return the application log file path."""
        return self.log_dir / self.log_file_name


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
