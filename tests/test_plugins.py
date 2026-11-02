"""Plugin registry tests."""

from __future__ import annotations

import pytest

from argus.config import CheckConfig, ServiceConfig
from argus.monitor.base import HealthCheck
from argus.monitor.http_check import HttpCheck
from argus.plugins import Hub, build_hub


def _dummy_factory(
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


class TestHub:
    def test_register_and_get_check(self):
        hub = Hub()
        hub.register_check("custom.one", _dummy_factory)
        assert hub.get_check_factory("custom.one") is _dummy_factory
        assert "custom.one" in hub.check_types()

    def test_duplicate_check_registration_raises(self):
        hub = Hub()
        hub.register_check("custom.one", _dummy_factory)
        with pytest.raises(ValueError, match="already registered"):
            hub.register_check("custom.one", _dummy_factory)

    def test_unknown_check_returns_none(self):
        hub = Hub()
        assert hub.get_check_factory("nope") is None

    def test_tool_and_action_registration(self):
        from pydantic import BaseModel

        from argus.plugins import Tool
        from argus.remediate.action import Action

        class _Args(BaseModel):
            x: int = 1

        async def _impl(_args: _Args) -> dict[str, str]:
            return {"ok": "yes"}

        tool = Tool(name="search_things", description="d", args_model=_Args, impl=_impl)
        hub = Hub()
        hub.register_tool(tool)
        assert hub.tools()["search_things"] is tool

        with pytest.raises(ValueError, match="already registered"):
            hub.register_tool(tool)

        action = Action(
            name="restart_thing",
            description="d",
            args_model=_Args,
            impl=_impl,
            destructive=True,
        )
        hub.register_action(action)
        assert hub.actions()["restart_thing"] is action


class TestBuildHub:
    def test_core_checks_always_registered(self):
        """Core checks ship with every install, no plugin needed."""
        hub = build_hub(enabled_products=[])
        types = hub.check_types()
        assert "http" in types
        assert "redis" in types

    def test_saboten_plugin_discovered(self):
        """The in-repo Saboten plugin registers via entry points."""
        hub = build_hub()  # all plugins
        assert "saboten.job_health" in hub.check_types()

    def test_example_plugin_discovered(self):
        """The in-repo example plugin proves the core is not Saboten-only."""
        hub = build_hub()
        assert "example.echo" in hub.check_types()

    def test_enabled_products_filter(self):
        hub = build_hub(enabled_products=["example"])
        types = hub.check_types()
        assert "example.echo" in types
        assert "saboten.job_health" not in types

    def test_empty_products_list_loads_core_only(self):
        hub = build_hub(enabled_products=[])
        types = hub.check_types()
        assert "example.echo" not in types
        assert "saboten.job_health" not in types
        assert "http" in types
