"""Engine construction smoke test.

Verifies ``SentinelEngine`` builds its check registry from config without
touching Redis or the network. Full lifecycle (start/stop) belongs in
Phase 1 integration tests with testcontainers.
"""

from __future__ import annotations

from sentinel.core.engine import SentinelEngine


def test_engine_builds_from_config(sentinel_config):
    engine = SentinelEngine(sentinel_config)
    # Private, but Phase 0 wants to prove the registry was populated.
    scheduler = engine._scheduler  # noqa: SLF001
    assert scheduler is not None
