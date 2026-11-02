from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from sentinel.models import CheckResult, CheckStatus, Severity, SEVERITY_FROM_STATUS

logger = logging.getLogger(__name__)


class HealthCheck(ABC):
    """Base class for all health checks."""

    def __init__(
        self,
        name: str,
        service: str,
        interval: int = 60,
        timeout: int = 10,
        environment: str = "dev",
        thresholds: dict[str, Any] | None = None,
    ):
        self.name = name
        self.service = service
        self.interval = interval
        self.timeout = timeout
        self.environment = environment
        self.thresholds = thresholds or {}

    @abstractmethod
    async def execute(self) -> CheckResult:
        ...

    def _result(
        self,
        status: CheckStatus,
        message: str,
        duration_ms: float = 0.0,
        details: dict[str, Any] | None = None,
    ) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            service=self.service,
            status=status,
            severity=SEVERITY_FROM_STATUS[status],
            message=message,
            duration_ms=duration_ms,
            environment=self.environment,
            details=details or {},
        )
