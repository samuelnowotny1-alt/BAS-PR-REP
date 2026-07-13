"""Runtime bootstrap helpers for BAS Assistant."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

from .config import Settings


def ensure_runtime_directories(settings: Settings) -> None:
    """Create required runtime directories if they do not already exist."""
    settings.static_dir.mkdir(parents=True, exist_ok=True)
    settings.templates_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    (settings.output_dir / "projects").mkdir(parents=True, exist_ok=True)


def configure_logging(settings: Settings) -> None:
    """Configure application logging for console and file output."""
    ensure_runtime_directories(settings)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": settings.log_level,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "standard",
                    "level": settings.log_level,
                    "filename": str(settings.log_file),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 5,
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
            },
        }
    )


def is_path_writable(path: Path) -> bool:
    """Return whether the application can write to a directory."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_file = path / ".write_test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        return True
    except OSError:
        return False


def build_health_report(settings: Settings, *, loaded_projects: int) -> dict[str, Any]:
    """Create a production-friendly health payload."""
    data_dir_ready = settings.data_dir.exists() and is_path_writable(settings.data_dir)
    output_dir_ready = settings.output_dir.exists() and is_path_writable(settings.output_dir)
    overall_status = "ok" if data_dir_ready and output_dir_ready else "degraded"
    return {
        "status": overall_status,
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "projects_loaded": loaded_projects,
        "checks": {
            "data_dir": {
                "path": str(settings.data_dir),
                "ready": data_dir_ready,
            },
            "output_dir": {
                "path": str(settings.output_dir),
                "ready": output_dir_ready,
            },
            "uploads_dir": {
                "path": str(settings.uploads_dir),
                "ready": settings.uploads_dir.exists() and is_path_writable(settings.uploads_dir),
            },
            "log_dir": {
                "path": str(settings.log_dir),
                "ready": settings.log_dir.exists(),
            },
        },
    }
