from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from argus.metrics import CHECK_DURATION, CHECKS_TOTAL
from argus.models import CheckResult
from argus.monitor.base import HealthCheck

logger = logging.getLogger(__name__)


class CheckScheduler:
    """Schedules health checks at configured intervals using APScheduler."""

    def __init__(self, on_result: Callable[[CheckResult], Awaitable[None]]):
        self._scheduler = AsyncIOScheduler()
        self._on_result = on_result
        self._checks: list[HealthCheck] = []

    def register(self, check: HealthCheck) -> None:
        self._checks.append(check)
        self._scheduler.add_job(
            self._run_check,
            "interval",
            seconds=check.interval,
            args=[check],
            id=f"{check.service}:{check.name}",
            name=f"{check.service}/{check.name}",
            max_instances=1,
            misfire_grace_time=30,
        )
        logger.info(
            "Registered check %s/%s (every %ds)",
            check.service,
            check.name,
            check.interval,
        )

    async def _run_check(self, check: HealthCheck) -> None:
        start = time.monotonic()
        try:
            result = await check.execute()
            CHECKS_TOTAL.labels(
                service=check.service, check=check.name, status=result.status.value
            ).inc()
            CHECK_DURATION.labels(service=check.service, check=check.name).observe(
                time.monotonic() - start
            )
            await self._on_result(result)
        except Exception:
            CHECKS_TOTAL.labels(service=check.service, check=check.name, status="error").inc()
            logger.exception("Failed to run check %s/%s", check.service, check.name)

    async def start(self) -> None:
        if not self._checks:
            logger.warning("No checks registered — scheduler not starting")
            return
        self._scheduler.start()
        logger.info("Scheduler started with %d checks", len(self._checks))

        # Run all checks immediately on startup
        for check in self._checks:
            await self._run_check(check)

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
