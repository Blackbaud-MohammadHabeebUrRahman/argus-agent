"""Saboten-specific health checks.

Only one for now: ``saboten.job_health`` polls Saboten's ``/monitor``
endpoint for in-progress and failed-in-24h job counts by vendor type.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

from argus.models import CheckResult, CheckStatus
from argus.monitor.base import HealthCheck

if TYPE_CHECKING:
    from argus.config import CheckConfig, ServiceConfig
    from argus.plugins import Hub

logger = logging.getLogger(__name__)

JOB_TYPES = ["NCOA", "DHC", "Deceased", "Fundraising", "Social"]


class SabotenJobHealthCheck(HealthCheck):
    """Check Saboten job queue health via its ``/monitor`` endpoint."""

    def __init__(
        self,
        name: str,
        service: str,
        host: str,
        port: int = 5000,
        path: str = "/monitor",
        scheme: str = "http",
        **kwargs: Any,
    ):
        super().__init__(name=name, service=service, **kwargs)
        self.base_url = f"{scheme}://{host}:{port}{path}"
        self.stuck_warning = self.thresholds.get("stuck_jobs_warning", 5)
        self.stuck_critical = self.thresholds.get("stuck_jobs_critical", 15)
        self.failed_rate_warning = self.thresholds.get("failed_rate_warning", 0.10)
        self.failed_rate_critical = self.thresholds.get("failed_rate_critical", 0.25)

    async def execute(self) -> CheckResult:
        start = time.monotonic()
        issues: list[str] = []
        details: dict[str, Any] = {}
        worst_status = CheckStatus.OK

        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                for job_type in JOB_TYPES:
                    try:
                        in_progress_url = f"{self.base_url}/{job_type}/in_progress/1"
                        resp = await client.get(in_progress_url)
                        if resp.status_code == 200:
                            data = (
                                resp.json()
                                if resp.headers.get("content-type", "").startswith(
                                    "application/json"
                                )
                                else {}
                            )
                            count = data.get("count", 0) if isinstance(data, dict) else 0
                            details[f"{job_type}_in_progress"] = count
                    except Exception:
                        details[f"{job_type}_in_progress"] = "error"

                    try:
                        failed_url = f"{self.base_url}/{job_type}/failed/24"
                        resp = await client.get(failed_url)
                        if resp.status_code == 200:
                            data = (
                                resp.json()
                                if resp.headers.get("content-type", "").startswith(
                                    "application/json"
                                )
                                else {}
                            )
                            count = data.get("count", 0) if isinstance(data, dict) else 0
                            details[f"{job_type}_failed_24h"] = count

                            if count >= self.stuck_critical:
                                worst_status = CheckStatus.CRITICAL
                                issues.append(
                                    f"{job_type}: {count} failed jobs in 24h "
                                    f"(critical threshold: {self.stuck_critical})"
                                )
                            elif count >= self.stuck_warning:
                                if worst_status != CheckStatus.CRITICAL:
                                    worst_status = CheckStatus.WARNING
                                issues.append(
                                    f"{job_type}: {count} failed jobs in 24h "
                                    f"(warning threshold: {self.stuck_warning})"
                                )
                    except Exception:
                        details[f"{job_type}_failed_24h"] = "error"

        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return self._result(
                CheckStatus.UNKNOWN,
                f"Job health check failed: {exc}",
                duration_ms=duration_ms,
            )

        duration_ms = (time.monotonic() - start) * 1000

        if worst_status == CheckStatus.OK:
            return self._result(
                CheckStatus.OK,
                "Job queue healthy across all job types",
                duration_ms=duration_ms,
                details=details,
            )
        return self._result(
            worst_status,
            "; ".join(issues),
            duration_ms=duration_ms,
            details=details,
        )


def register_checks(hub: Hub) -> None:
    """Register check types the Saboten orchestrator exposes."""

    def factory(
        name: str,
        svc_name: str,
        svc_cfg: ServiceConfig,
        chk_cfg: CheckConfig,
        env: str,
    ) -> HealthCheck:
        return SabotenJobHealthCheck(
            name=name,
            service=svc_name,
            host=svc_cfg.host,
            port=chk_cfg.port,
            path=chk_cfg.path or "/monitor",
            interval=chk_cfg.interval,
            timeout=chk_cfg.timeout,
            environment=env,
            thresholds=chk_cfg.thresholds,
        )

    hub.register_check("saboten.job_health", factory)
