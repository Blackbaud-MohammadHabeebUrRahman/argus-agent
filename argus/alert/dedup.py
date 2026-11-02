from __future__ import annotations

import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

KEY_PREFIX = "argus:dedup:"


class AlertDedup:
    """Redis-backed alert deduplication with cooldown."""

    def __init__(self, redis_url: str, cooldown_minutes: int = 30):
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._cooldown_seconds = cooldown_minutes * 60

    async def should_alert(self, dedup_key: str) -> bool:
        """Returns True if no active cooldown exists for this key."""
        key = f"{KEY_PREFIX}{dedup_key}"
        exists = await self._redis.exists(key)
        return not exists

    async def mark_alerted(self, dedup_key: str) -> None:
        """Set a cooldown for this dedup key."""
        key = f"{KEY_PREFIX}{dedup_key}"
        await self._redis.setex(key, self._cooldown_seconds, "1")

    async def clear(self, dedup_key: str) -> None:
        """Clear cooldown for a dedup key (e.g., on resolution)."""
        key = f"{KEY_PREFIX}{dedup_key}"
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()
