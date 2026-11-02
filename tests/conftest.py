"""Shared fixtures.

Keeps everything in-process so Phase 0 smoke tests don't need Docker. Tests
that depend on Redis or on a live Saboten service belong under
``@pytest.mark.integration`` and will arrive in Phase 1.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from sentinel.config import SentinelConfig, SentinelSettings, load_config


@pytest.fixture
def sentinel_yaml(tmp_path: Path) -> Path:
    """A minimal valid sentinel.yaml with one HTTP check."""
    path = tmp_path / "sentinel.yaml"
    path.write_text(dedent("""
        environments:
          dev:
            services:
              dummy-api:
                host: "localhost"
                checks:
                  - type: http
                    path: "/health"
                    port: 9999
                    interval: 60
                    timeout: 5

        alerting:
          teams:
            enabled: false
          slack:
            enabled: false
          routing:
            - severity: critical
              channels: [teams]
          dedup:
            cooldown_minutes: 1
    """).strip())
    return path


@pytest.fixture
def sentinel_config(sentinel_yaml: Path, monkeypatch: pytest.MonkeyPatch) -> SentinelConfig:
    """Load the fixture YAML as a SentinelConfig."""
    monkeypatch.setenv("SENTINEL_ENVIRONMENT", "dev")
    monkeypatch.setenv("SENTINEL_CONFIG_PATH", str(sentinel_yaml))
    # Point at a loopback redis URL that won't be dialed in unit tests.
    monkeypatch.setenv("SENTINEL_REDIS_URL", "redis://localhost:6379/15")
    return load_config(str(sentinel_yaml))


@pytest.fixture
def default_settings() -> SentinelSettings:
    """SentinelSettings with no env vars overriding defaults."""
    return SentinelSettings()
