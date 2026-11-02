"""Smoke tests for config loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.config import load_config


def test_load_config_reads_yaml(sentinel_config):
    assert "dev" in sentinel_config.environments
    env = sentinel_config.active_env
    assert "dummy-api" in env.services
    check = env.services["dummy-api"].checks[0]
    assert check.type == "http"
    assert check.port == 9999


def test_load_config_env_overlay(sentinel_yaml: Path, monkeypatch: pytest.MonkeyPatch):
    overlay = sentinel_yaml.parent / "sentinel.dev.yaml"
    overlay.write_text(
        "environments:\n"
        "  dev:\n"
        "    services:\n"
        "      extra-service:\n"
        '        host: "localhost"\n'
        "        checks: []\n"
    )
    monkeypatch.setenv("SENTINEL_ENVIRONMENT", "dev")
    cfg = load_config(str(sentinel_yaml))
    assert "extra-service" in cfg.active_env.services
    assert "dummy-api" in cfg.active_env.services


def test_webhook_env_var_enables_channel(sentinel_yaml: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SENTINEL_SLACK_WEBHOOK_URL", "https://hooks.example/XYZ")
    cfg = load_config(str(sentinel_yaml))
    assert cfg.alerting.slack.enabled is True
    assert cfg.alerting.slack.webhook_url == "https://hooks.example/XYZ"


def test_missing_env_returns_empty_env_config(sentinel_yaml: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SENTINEL_ENVIRONMENT", "nope")
    cfg = load_config(str(sentinel_yaml))
    assert cfg.active_env.services == {}
