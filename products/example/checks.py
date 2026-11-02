"""Example plugin check: an always-healthy echo.

Trivial on purpose. Demonstrates how a plugin registers a new check
type — ``example.echo`` — that any argus.yaml can then reference.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from argus.models import CheckResult, CheckStatus
from argus.monitor.base import HealthCheck

if TYPE_CHECKING:
    from argus.config import CheckConfig, ServiceConfig
    from argus.plugins import Hub

logger = logging.getLogger(__name__)


class ExampleEchoCheck(HealthCheck):
    """Always returns OK. For demonstrating the plugin registration path."""

    def __init__(self, name: str, service: str, message: str = "pong", **kwargs: Any):
        super().__init__(name=name, service=service, **kwargs)
        self.message = message

    async def execute(self) -> CheckResult:
        start = time.monotonic()
        duration_ms = (time.monotonic() - start) * 1000
        return self._result(
            CheckStatus.OK,
            f"echo: {self.message}",
            duration_ms=duration_ms,
            details={"echo": self.message},
        )


def register_checks(hub: Hub) -> None:
    def factory(
        name: str,
        svc_name: str,
        svc_cfg: ServiceConfig,
        chk_cfg: CheckConfig,
        env: str,
    ) -> HealthCheck:
        return ExampleEchoCheck(
            name=name,
            service=svc_name,
            message=chk_cfg.thresholds.get("message", "pong"),
            interval=chk_cfg.interval,
            timeout=chk_cfg.timeout,
            environment=env,
            thresholds=chk_cfg.thresholds,
        )

    hub.register_check("example.echo", factory)
