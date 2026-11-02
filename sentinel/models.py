from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CheckStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    FATAL = "fatal"


class IncidentState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


SEVERITY_FROM_STATUS = {
    CheckStatus.OK: Severity.INFO,
    CheckStatus.WARNING: Severity.WARNING,
    CheckStatus.CRITICAL: Severity.CRITICAL,
    CheckStatus.UNKNOWN: Severity.WARNING,
}

SEVERITY_COLORS = {
    Severity.INFO: "#2DC72D",
    Severity.WARNING: "#FFA500",
    Severity.CRITICAL: "#FF0000",
    Severity.FATAL: "#8B0000",
}


class CheckResult(BaseModel):
    check_name: str
    service: str
    status: CheckStatus
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0
    environment: str = "dev"


class Incident(BaseModel):
    id: str
    check_name: str
    service: str
    state: IncidentState = IncidentState.OPEN
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    alert_count: int = 0
    environment: str = "dev"
    check_results: list[CheckResult] = Field(default_factory=list)

    @property
    def dedup_key(self) -> str:
        return f"{self.check_name}:{self.service}:{self.environment}"
