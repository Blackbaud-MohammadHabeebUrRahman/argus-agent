"""Smoke tests for config loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from argus.config import load_config


def test_load_config_reads_yaml(argus_config):
    assert "dev" in argus_config.environments
    env = argus_config.active_env
    assert "dummy-api" in env.services
    check = env.services["dummy-api"].checks[0]
    assert check.type == "http"
    assert check.port == 9999


def test_load_config_env_overlay(argus_yaml: Path, monkeypatch: pytest.MonkeyPatch):
    overlay = argus_yaml.parent / "argus.dev.yaml"
    overlay.write_text(
        "environments:\n"
        "  dev:\n"
        "    services:\n"
        "      extra-service:\n"
        '        host: "localhost"\n'
        "        checks: []\n"
    )
    monkeypatch.setenv("ARGUS_ENVIRONMENT", "dev")
    cfg = load_config(str(argus_yaml))
    assert "extra-service" in cfg.active_env.services
    assert "dummy-api" in cfg.active_env.services


def test_webhook_env_var_enables_channel(argus_yaml: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGUS_SLACK_WEBHOOK_URL", "https://hooks.example/XYZ")
    cfg = load_config(str(argus_yaml))
    assert cfg.alerting.slack.enabled is True
    assert cfg.alerting.slack.webhook_url == "https://hooks.example/XYZ"


def test_missing_env_returns_empty_env_config(argus_yaml: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGUS_ENVIRONMENT", "nope")
    cfg = load_config(str(argus_yaml))
    assert cfg.active_env.services == {}
