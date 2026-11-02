from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from sentinel.models import CheckResult
from sentinel.monitor.base import HealthCheck

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
        try:
            result = await check.execute()
            await self._on_result(result)
        except Exception:
            logger.exception("Failed to run check %s/%s", check.service, check.name)

    async def start(self) -> None:
        if not self._checks:
            logger.warning("No checks registered — scheduler not starting")
            return
        self._scheduler.start()
        logger.info("Scheduler started with %d checks", len(self._checks))

        # Run all checks immediately on startup
        for check in self._checks:
            try:
                result = await check.execute()
                await self._on_result(result)
            except Exception:
                logger.exception("Initial check failed: %s/%s", check.service, check.name)

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
