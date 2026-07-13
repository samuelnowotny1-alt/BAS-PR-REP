"""Station sync models for Niagara/JACE connectivity."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class StationSyncProtocol(str, Enum):
    """Supported station communication protocols."""

    OBIX_HTTP = "oBIX/HTTP"
    FILE_EXPORT = "File Export"


class StationSyncTarget(str, Enum):
    """Supported station target families."""

    NIAGARA = "Niagara Station"


class StationConnectionConfig(BaseModel):
    """Persisted station connection settings."""

    enabled: bool = False
    target: StationSyncTarget = StationSyncTarget.NIAGARA
    protocol: StationSyncProtocol = StationSyncProtocol.OBIX_HTTP
    host: str | None = None
    port: int = 443
    use_tls: bool = True
    verify_tls: bool = True
    station_name: str | None = None
    username: str | None = None
    obix_path: str = "/obix"
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    last_tested_at: datetime | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None

    def base_url(self) -> str:
        scheme = "https" if self.use_tls else "http"
        host = (self.host or "").strip()
        return f"{scheme}://{host}:{self.port}"

    def obix_url(self) -> str:
        path = self.obix_path.strip() or "/obix"
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url()}{path}"


class StationSyncPlanItem(BaseModel):
    """One operation that would be synchronized to the station."""

    category: str
    name: str
    action: str
    ord_path: str | None = None
    status: str = "planned"
    details: str | None = None


class StationSyncPlan(BaseModel):
    """Planned station sync workload."""

    target: str
    protocol: str
    generated_at: datetime = Field(default_factory=datetime.now)
    summary: str
    items: list[StationSyncPlanItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StationProbeResult(BaseModel):
    """Connection test result for a station endpoint."""

    success: bool
    endpoint: str
    status_code: int | None = None
    message: str
    checked_at: datetime = Field(default_factory=datetime.now)


__all__ = [
    "StationConnectionConfig",
    "StationProbeResult",
    "StationSyncPlan",
    "StationSyncPlanItem",
    "StationSyncProtocol",
    "StationSyncTarget",
]
