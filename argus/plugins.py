"""Plugin registry — the extension point for product-specific behaviour.

Argus's core (engine, scheduler, alerting, agent harness, MCP server) is
product-agnostic. Product-specific pieces — check types that know a given
system's health endpoints, investigation tools that know its data model,
remediation actions that know its deploy mechanics — are contributed by
plugins through a ``Hub``.

A plugin is any installable Python package that declares an entry point:

    [project.entry-points."argus.plugins"]
    saboten = "products.saboten:register"

At startup ``build_hub()`` discovers every such entry point and calls its
``register(hub)`` function. The plugin uses the hub to register check
factories, tools, or remediation actions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from argus.config import CheckConfig, ServiceConfig
    from argus.monitor.base import HealthCheck

logger = logging.getLogger(__name__)

CheckFactory = Callable[[str, str, "ServiceConfig", "CheckConfig", str], "HealthCheck"]
"""Signature: (check_name, service_name, service_cfg, check_cfg, environment)."""


class Hub:
    """Central registry that plugins populate at startup."""

    def __init__(self) -> None:
        self._checks: dict[str, CheckFactory] = {}
        self._tools: dict[str, Callable[..., Any]] = {}
        self._actions: dict[str, Callable[..., Any]] = {}

    def register_check(self, type_name: str, factory: CheckFactory) -> None:
        if type_name in self._checks:
            raise ValueError(f"Check type {type_name!r} is already registered")
        self._checks[type_name] = factory
        logger.debug("registered check type %r", type_name)

    def register_tool(self, name: str, func: Callable[..., Any]) -> None:
        """Reserved for Phase 2 (investigation tools)."""
        if name in self._tools:
            raise ValueError(f"Tool {name!r} is already registered")
        self._tools[name] = func
        logger.debug("registered tool %r", name)

    def register_action(self, name: str, func: Callable[..., Any]) -> None:
        """Reserved for Phase 5 (remediation actions)."""
        if name in self._actions:
            raise ValueError(f"Action {name!r} is already registered")
        self._actions[name] = func
        logger.debug("registered action %r", name)

    def get_check_factory(self, type_name: str) -> CheckFactory | None:
        return self._checks.get(type_name)

    def check_types(self) -> list[str]:
        return sorted(self._checks)

    def tools(self) -> dict[str, Callable[..., Any]]:
        return dict(self._tools)

    def actions(self) -> dict[str, Callable[..., Any]]:
        return dict(self._actions)


def _register_core_checks(hub: Hub) -> None:
    """Checks that ship with every install, independent of any plugin."""
    from argus.monitor.http_check import HttpCheck
    from argus.monitor.redis_check import RedisCheck

    def http_factory(
        name: str,
        svc_name: str,
        svc_cfg: ServiceConfig,
        chk_cfg: CheckConfig,
        env: str,
    ) -> HealthCheck:
        return HttpCheck(
            name=name,
            service=svc_name,
            host=svc_cfg.host,
            port=chk_cfg.port,
            path=chk_cfg.path,
            interval=chk_cfg.interval,
            timeout=chk_cfg.timeout,
            environment=env,
            thresholds=chk_cfg.thresholds,
        )

    def redis_factory(
        name: str,
        svc_name: str,
        svc_cfg: ServiceConfig,
        chk_cfg: CheckConfig,
        env: str,
    ) -> HealthCheck:
        return RedisCheck(
            name=name,
            service=svc_name,
            host=svc_cfg.host,
            port=chk_cfg.port,
            interval=chk_cfg.interval,
            timeout=chk_cfg.timeout,
            environment=env,
            thresholds=chk_cfg.thresholds,
        )

    hub.register_check("http", http_factory)
    hub.register_check("redis", redis_factory)


def build_hub(enabled_products: list[str] | None = None) -> Hub:
    """Create a hub, install core checks, then run every discovered plugin.

    ``enabled_products`` filters which plugins run. ``None`` means load all
    discovered plugins; an empty list loads none (core checks only); a list
    of names loads only those entry points.
    """
    hub = Hub()
    _register_core_checks(hub)

    for ep in entry_points(group="argus.plugins"):
        if enabled_products is not None and ep.name not in enabled_products:
            logger.debug("skipping plugin %r (not in enabled list)", ep.name)
            continue
        try:
            register_fn = ep.load()
        except Exception:
            logger.exception("failed to load plugin entry point %r", ep.name)
            continue
        try:
            register_fn(hub)
            logger.info("loaded plugin %r", ep.name)
        except Exception:
            logger.exception("plugin %r raised during register()", ep.name)

    return hub
