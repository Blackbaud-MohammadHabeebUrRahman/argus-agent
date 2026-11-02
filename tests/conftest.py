"""Shared fixtures.

Keeps everything in-process so Phase 0 smoke tests don't need Docker. Tests
that depend on Redis or on a live service belong under
``@pytest.mark.integration`` and will arrive in Phase 1.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from argus.config import ArgusConfig, ArgusSettings, load_config


@pytest.fixture
def argus_yaml(tmp_path: Path) -> Path:
    """A minimal valid argus.yaml with one HTTP check."""
    path = tmp_path / "argus.yaml"
    path.write_text(
        dedent("""
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
    """).strip()
    )
    return path


@pytest.fixture
def argus_config(argus_yaml: Path, monkeypatch: pytest.MonkeyPatch) -> ArgusConfig:
    """Load the fixture YAML as an ArgusConfig."""
    monkeypatch.setenv("ARGUS_ENVIRONMENT", "dev")
    monkeypatch.setenv("ARGUS_CONFIG_PATH", str(argus_yaml))
    # Point at a loopback redis URL that won't be dialed in unit tests.
    monkeypatch.setenv("ARGUS_REDIS_URL", "redis://localhost:6379/15")
    return load_config(str(argus_yaml))


@pytest.fixture
def default_settings() -> ArgusSettings:
    """ArgusSettings with no env vars overriding defaults."""
    return ArgusSettings()
