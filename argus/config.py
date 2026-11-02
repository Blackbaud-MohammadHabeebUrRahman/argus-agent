from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class CheckConfig(BaseModel):
    type: str
    path: str = ""
    port: int = 80
    interval: int = 60
    timeout: int = 10
    thresholds: dict[str, Any] = Field(default_factory=dict)


class ServiceConfig(BaseModel):
    host: str
    checks: list[CheckConfig] = Field(default_factory=list)


class ChannelConfig(BaseModel):
    enabled: bool = False


class TeamsConfig(ChannelConfig):
    webhook_url: str = ""


class SlackConfig(ChannelConfig):
    webhook_url: str = ""
    channel: str = "#argus-alerts"


class EmailConfig(ChannelConfig):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_address: str = "argus@example.com"
    recipients: list[str] = Field(default_factory=list)


class RoutingRule(BaseModel):
    severity: str
    channels: list[str]
    recipients_email: list[str] = Field(default_factory=list)


class DedupConfig(BaseModel):
    cooldown_minutes: int = 30


class MetricsConfig(BaseModel):
    enabled: bool = True
    port: int = 9090
    addr: str = "0.0.0.0"


class AlertingConfig(BaseModel):
    teams: TeamsConfig = Field(default_factory=TeamsConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    routing: list[RoutingRule] = Field(default_factory=list)
    dedup: DedupConfig = Field(default_factory=DedupConfig)


class EnvironmentConfig(BaseModel):
    services: dict[str, ServiceConfig] = Field(default_factory=dict)


class ArgusSettings(BaseSettings):
    environment: str = "dev"
    config_path: str = "config/argus.yaml"
    log_level: str = "INFO"
    redis_url: str = "redis://localhost:6379/1"
    teams_webhook_url: str = ""
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "argus@example.com"
    splunk_base_url: str = ""
    splunk_token: str = ""
    github_token: str = ""
    github_org: str = "blackbaud"
    anthropic_api_key: str = ""

    model_config = {"env_prefix": "ARGUS_"}


class ArgusConfig(BaseModel):
    settings: ArgusSettings
    environments: dict[str, EnvironmentConfig] = Field(default_factory=dict)
    alerting: AlertingConfig = Field(default_factory=AlertingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    product: str | None = None
    products: list[str] | None = None

    @property
    def active_env(self) -> EnvironmentConfig:
        return self.environments.get(self.settings.environment, EnvironmentConfig())

    @property
    def enabled_products(self) -> list[str] | None:
        """Which plugin entry points to activate.

        ``None`` means "load every discovered plugin"; a list means "load
        only these". ``product:`` (singular) and ``products:`` (list) in
        YAML combine into one list.
        """
        if self.product is None and self.products is None:
            return None
        names: list[str] = []
        if self.product:
            names.append(self.product)
        if self.products:
            names.extend(self.products)
        return names


def _deep_merge(base: dict, overlay: dict) -> dict:
    merged = base.copy()
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: str | None = None, env: str | None = None) -> ArgusConfig:
    settings = ArgusSettings()
    path = Path(config_path or settings.config_path)

    yaml_data: dict[str, Any] = {}
    if path.exists():
        with open(path) as f:
            yaml_data = yaml.safe_load(f) or {}

    env_name = env or settings.environment
    env_overlay_path = path.parent / f"argus.{env_name}.yaml"
    if env_overlay_path.exists():
        with open(env_overlay_path) as f:
            overlay = yaml.safe_load(f) or {}
            yaml_data = _deep_merge(yaml_data, overlay)

    alerting_data = yaml_data.get("alerting", {})
    teams_cfg = alerting_data.get("teams", {})
    slack_cfg = alerting_data.get("slack", {})

    # An explicit webhook via env var always enables the channel. The YAML
    # default of enabled=false is for safety when no URL is configured; once
    # an operator provides a URL they are opting in.
    if settings.teams_webhook_url:
        teams_cfg["webhook_url"] = settings.teams_webhook_url
        teams_cfg["enabled"] = True
    if settings.slack_webhook_url:
        slack_cfg["webhook_url"] = settings.slack_webhook_url
        slack_cfg["enabled"] = True
    if settings.smtp_host:
        email_cfg = alerting_data.get("email", {})
        email_cfg["smtp_host"] = settings.smtp_host
        email_cfg["smtp_port"] = settings.smtp_port
        email_cfg["smtp_user"] = settings.smtp_user
        email_cfg["smtp_password"] = settings.smtp_password
        email_cfg["from_address"] = settings.email_from
        alerting_data["email"] = email_cfg

    alerting_data["teams"] = teams_cfg
    alerting_data["slack"] = slack_cfg

    environments = {}
    for env_key, env_val in yaml_data.get("environments", {}).items():
        environments[env_key] = EnvironmentConfig(**env_val)

    alerting = AlertingConfig(**alerting_data)

    metrics = MetricsConfig(**yaml_data.get("metrics", {}))

    return ArgusConfig(
        settings=settings,
        environments=environments,
        alerting=alerting,
        metrics=metrics,
        product=yaml_data.get("product"),
        products=yaml_data.get("products"),
    )
