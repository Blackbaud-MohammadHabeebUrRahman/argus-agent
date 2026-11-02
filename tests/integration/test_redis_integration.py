"""Integration tests that run against a real Redis via testcontainers.

Skipped automatically unless the ``integration`` extra is installed and
Docker is reachable. Run with ``make test-all`` or
``pytest -m integration``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("testcontainers.redis")

from testcontainers.redis import RedisContainer  # noqa: E402

from argus.alert.dedup import AlertDedup  # noqa: E402
from argus.core.state import IncidentStore  # noqa: E402
from argus.models import CheckResult, CheckStatus, Severity  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redis_url():
    with RedisContainer("redis:7-alpine") as redis:
        host = redis.get_container_host_ip()
        port = redis.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


async def test_incident_store_create_get_resolve_against_real_redis(redis_url):
    store = IncidentStore(redis_url)
    try:
        result = CheckResult(
            check_name="chk",
            service="svc",
            status=CheckStatus.CRITICAL,
            severity=Severity.CRITICAL,
            message="down",
            environment="test",
        )
        incident, is_new = await store.create_or_update(result)
        assert is_new is True
        assert incident.service == "svc"

        active = await store.get_active("chk:svc:test")
        assert active is not None
        assert active.id == incident.id

        await store.resolve("chk:svc:test")
        assert await store.get_active("chk:svc:test") is None
    finally:
        await store.close()


async def test_dedup_escalation_across_processes(redis_url):
    """Severity escalation re-alerts even against a persistent Redis."""
    dedup = AlertDedup(redis_url, cooldown_minutes=30)
    try:
        key = "svc:a:test"
        assert await dedup.should_alert(key, Severity.WARNING) is True
        await dedup.mark_alerted(key, Severity.WARNING)
        assert await dedup.should_alert(key, Severity.WARNING) is False
        # Escalation bypasses the cooldown
        assert await dedup.should_alert(key, Severity.CRITICAL) is True
        await dedup.mark_alerted(key, Severity.CRITICAL)
        # And now the stored severity is critical — a warning doesn't re-page
        assert await dedup.should_alert(key, Severity.WARNING) is False
        await dedup.clear(key)
    finally:
        await dedup.close()
