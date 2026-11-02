"""Tests for the Argus MCP adapter.

The handlers are decoupled from the official SDK transport, so these
tests exercise the real resource / tool / prompt wiring without any
stdio or JSON-RPC plumbing.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, Field

from argus.config import ArgusConfig, ArgusSettings, CheckConfig, EnvironmentConfig, ServiceConfig
from argus.mcp.server import ArgusMCP
from argus.plugins import Hub, Tool


class _EchoArgs(BaseModel):
    message: str = Field(description="the thing to echo")


async def _echo_impl(args: _EchoArgs) -> dict[str, Any]:
    return {"echoed": args.message}


@pytest.fixture
def config() -> ArgusConfig:
    return ArgusConfig(
        settings=ArgusSettings(environment="dev"),
        environments={
            "dev": EnvironmentConfig(
                services={
                    "api": ServiceConfig(
                        host="localhost",
                        checks=[CheckConfig(type="http", path="/health", port=8080, interval=60)],
                    )
                }
            )
        },
    )


@pytest.fixture
def hub() -> Hub:
    h = Hub()
    h.register_tool(
        Tool(
            name="echo",
            description="echo back whatever you send",
            args_model=_EchoArgs,
            impl=_echo_impl,
        )
    )
    return h


@pytest.fixture
def mcp(config: ArgusConfig, hub: Hub) -> ArgusMCP:
    return ArgusMCP(config, hub, incident_store=None)


class TestResources:
    def test_list_resources_includes_core_uris(self, mcp: ArgusMCP):
        uris = {r["uri"] for r in mcp.list_resources()}
        assert "argus://incidents" in uris
        assert "argus://services" in uris
        assert "argus://alerts/recent" in uris

    async def test_read_services_returns_configured_services(self, mcp: ArgusMCP):
        payload = await mcp.read_resource("argus://services")
        data = json.loads(payload)
        assert data["environment"] == "dev"
        assert "api" in data["services"]
        assert data["services"]["api"]["checks"][0]["type"] == "http"

    async def test_read_incidents_without_store_returns_diagnostic(self, mcp: ArgusMCP):
        payload = await mcp.read_resource("argus://incidents")
        data = json.loads(payload)
        assert data["configured"] is False

    async def test_read_unknown_resource_returns_error(self, mcp: ArgusMCP):
        payload = await mcp.read_resource("argus://nope")
        assert "unknown resource" in json.loads(payload)["error"]


class TestTools:
    def test_list_tools_includes_investigate_and_hub_tools(self, mcp: ArgusMCP):
        names = {t["name"] for t in mcp.list_tools()}
        assert "investigate_incident" in names
        assert "echo" in names  # from the hub

    def test_hub_tool_schema_is_passed_through(self, mcp: ArgusMCP):
        echo = next(t for t in mcp.list_tools() if t["name"] == "echo")
        assert echo["inputSchema"]["properties"]["message"]["type"] == "string"

    async def test_call_hub_tool_dispatches_to_impl(self, mcp: ArgusMCP):
        result = json.loads(await mcp.call_tool("echo", {"message": "hi"}))
        assert result == {"echoed": "hi"}

    async def test_unknown_tool_returns_error(self, mcp: ArgusMCP):
        result = json.loads(await mcp.call_tool("nope", {}))
        assert "unknown tool" in result["error"]

    async def test_investigate_without_store_returns_error(self, mcp: ArgusMCP):
        result = json.loads(await mcp.call_tool("investigate_incident", {"incident_id": "x"}))
        assert "no incident store" in result["error"]

    async def test_investigate_without_incident_id_returns_error(self, mcp: ArgusMCP):
        result = json.loads(await mcp.call_tool("investigate_incident", {}))
        assert "incident_id required" in result["error"]


class TestPrompts:
    def test_list_prompts_includes_named_templates(self, mcp: ArgusMCP):
        names = {p["name"] for p in mcp.list_prompts()}
        assert {"incident-triage", "stuck-jobs", "worker-crash-loop"} <= names

    def test_get_prompt_fills_arguments(self, mcp: ArgusMCP):
        result = mcp.get_prompt("incident-triage", {"incident_id": "abc123"})
        text = result["messages"][0]["content"]["text"]
        assert "abc123" in text

    def test_get_stuck_jobs_prompt_defaults_gracefully(self, mcp: ArgusMCP):
        result = mcp.get_prompt("stuck-jobs", {})
        text = result["messages"][0]["content"]["text"]
        assert "stuck" in text.lower()

    def test_unknown_prompt_returns_placeholder(self, mcp: ArgusMCP):
        result = mcp.get_prompt("nope", {})
        text = result["messages"][0]["content"]["text"]
        assert "unknown prompt" in text
