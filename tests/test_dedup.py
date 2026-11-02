"""AlertDedup severity-escalation and cooldown behavior.

Uses a tiny in-memory Redis fake so we don't need a Redis container just
for this. The integration test under tests/integration/ covers the real
thing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from argus.alert.dedup import KEY_PREFIX, AlertDedup
from argus.models import Severity


class FakeAsyncRedis:
    """Minimal subset of the ``redis.asyncio`` API the dedup actually uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def aclose(self) -> None:
        pass


@pytest.fixture
def dedup():
    with patch("argus.alert.dedup.aioredis.from_url", return_value=FakeAsyncRedis()):
        yield AlertDedup("redis://unused", cooldown_minutes=30)


class TestDedup:
    async def test_first_alert_fires(self, dedup):
        assert await dedup.should_alert("svc:a:dev", Severity.WARNING) is True

    async def test_second_alert_within_cooldown_is_suppressed(self, dedup):
        await dedup.mark_alerted("svc:a:dev", Severity.WARNING)
        assert await dedup.should_alert("svc:a:dev", Severity.WARNING) is False

    async def test_escalation_to_higher_severity_alerts_again(self, dedup):
        """The core Phase 1 fix: warning → critical must NOT be suppressed."""
        await dedup.mark_alerted("svc:a:dev", Severity.WARNING)
        assert await dedup.should_alert("svc:a:dev", Severity.CRITICAL) is True

    async def test_escalation_to_fatal_from_critical_alerts(self, dedup):
        await dedup.mark_alerted("svc:a:dev", Severity.CRITICAL)
        assert await dedup.should_alert("svc:a:dev", Severity.FATAL) is True

    async def test_de_escalation_from_critical_to_warning_is_suppressed(self, dedup):
        """A dropping severity inside the window shouldn't re-page."""
        await dedup.mark_alerted("svc:a:dev", Severity.CRITICAL)
        assert await dedup.should_alert("svc:a:dev", Severity.WARNING) is False

    async def test_mark_alerted_records_the_triggering_severity(self, dedup):
        await dedup.mark_alerted("svc:a:dev", Severity.WARNING)
        # Confirm by direct inspection of the fake store.
        assert dedup._redis.store[f"{KEY_PREFIX}svc:a:dev"] == "warning"

    async def test_mark_alerted_at_critical_blocks_subsequent_critical(self, dedup):
        await dedup.mark_alerted("svc:a:dev", Severity.CRITICAL)
        assert await dedup.should_alert("svc:a:dev", Severity.CRITICAL) is False

    async def test_clear_resets_state(self, dedup):
        await dedup.mark_alerted("svc:a:dev", Severity.CRITICAL)
        await dedup.clear("svc:a:dev")
        assert await dedup.should_alert("svc:a:dev", Severity.WARNING) is True

    async def test_flapping_cycle_alerts_once_per_cooldown(self, dedup):
        """OK→FAIL→OK→FAIL inside the window: first FAIL alerts, second doesn't."""
        # First failure
        assert await dedup.should_alert("svc:a:dev", Severity.CRITICAL) is True
        await dedup.mark_alerted("svc:a:dev", Severity.CRITICAL)
        # Recovery clears
        await dedup.clear("svc:a:dev")
        # Immediate re-failure DOES alert because the cooldown was cleared.
        assert await dedup.should_alert("svc:a:dev", Severity.CRITICAL) is True
        await dedup.mark_alerted("svc:a:dev", Severity.CRITICAL)
        # A third failure without an intervening OK is suppressed.
        assert await dedup.should_alert("svc:a:dev", Severity.CRITICAL) is False
