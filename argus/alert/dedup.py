"""Alert deduplication with severity-aware re-alerting.

A pure cooldown-based dedup silences the *second* alert for the same
underlying problem, which is what you want for an identical repeat. It
is NOT what you want when the problem escalates from warning to
critical — operators need to hear about that. This store records the
severity that triggered the last alert, and lets any strictly higher
severity bypass the cooldown.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from argus.models import Severity

logger = logging.getLogger(__name__)

KEY_PREFIX = "argus:dedup:"

_SEVERITY_RANK: dict[str, int] = {
    Severity.INFO.value: 0,
    Severity.WARNING.value: 1,
    Severity.CRITICAL.value: 2,
    Severity.FATAL.value: 3,
}


def _rank(severity: Severity | str) -> int:
    value = severity.value if isinstance(severity, Severity) else severity
    return _SEVERITY_RANK.get(value, 0)


class AlertDedup:
    """Redis-backed alert deduplication with cooldown + severity escalation."""

    def __init__(self, redis_url: str, cooldown_minutes: int = 30):
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._cooldown_seconds = cooldown_minutes * 60

    async def should_alert(self, dedup_key: str, severity: Severity) -> bool:
        """True if nothing is in cooldown, or the new severity exceeds the stored one."""
        key = f"{KEY_PREFIX}{dedup_key}"
        existing = await self._redis.get(key)
        if existing is None:
            return True
        return _rank(severity) > _rank(existing)

    async def mark_alerted(self, dedup_key: str, severity: Severity) -> None:
        """Record that we alerted at this severity; restarts the cooldown TTL."""
        key = f"{KEY_PREFIX}{dedup_key}"
        await self._redis.setex(key, self._cooldown_seconds, severity.value)

    async def clear(self, dedup_key: str) -> None:
        """Clear cooldown (e.g. on resolution)."""
        key = f"{KEY_PREFIX}{dedup_key}"
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()
