from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis

from sentinel.models import CheckResult, Incident

logger = logging.getLogger(__name__)

KEY_PREFIX = "sentinel:incident:"


class IncidentStore:
    """Redis-backed incident state tracking."""

    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def get_active(self, dedup_key: str) -> Incident | None:
        key = f"{KEY_PREFIX}{dedup_key}"
        data = await self._redis.get(key)
        if data:
            return Incident.model_validate_json(data)
        return None

    async def create_or_update(self, result: CheckResult) -> tuple[Incident, bool]:
        """Create a new incident or update an existing one.

        Returns (incident, is_new).
        """
        dedup_key = f"{result.check_name}:{result.service}:{result.environment}"
        existing = await self.get_active(dedup_key)

        if existing:
            existing.updated_at = datetime.now(timezone.utc)
            existing.message = result.message
            existing.severity = result.severity
            existing.details = result.details
            existing.check_results.append(result)
            if len(existing.check_results) > 10:
                existing.check_results = existing.check_results[-10:]
            existing.alert_count += 1
            await self._save(dedup_key, existing)
            return existing, False

        incident = Incident(
            id=uuid.uuid4().hex[:12],
            check_name=result.check_name,
            service=result.service,
            severity=result.severity,
            message=result.message,
            details=result.details,
            environment=result.environment,
            check_results=[result],
            alert_count=1,
        )
        await self._save(dedup_key, incident)
        return incident, True

    async def resolve(self, dedup_key: str) -> None:
        key = f"{KEY_PREFIX}{dedup_key}"
        await self._redis.delete(key)
        logger.info("Incident resolved: %s", dedup_key)

    async def _save(self, dedup_key: str, incident: Incident) -> None:
        key = f"{KEY_PREFIX}{dedup_key}"
        # TTL of 24h so stale incidents auto-expire
        await self._redis.setex(key, 86400, incident.model_dump_json())

    async def close(self) -> None:
        await self._redis.aclose()
