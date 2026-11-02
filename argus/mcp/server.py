"""Argus MCP server.

Exposes Argus to any MCP client — Claude Code, Claude Desktop, Cursor,
whatever — so an on-call engineer can drive investigations from chat
instead of SSHing into a box. The server is stateless beyond what the
IncidentStore holds, so running multiple instances behind the same
Redis is safe.

Resources (read-only):
  - ``argus://incidents``                  all currently active incidents
  - ``argus://incident/{id}``              one incident's full record
  - ``argus://services``                   configured services + checks
  - ``argus://alerts/recent``              recent alert dispatches (last 50)

Tools (actions the model can call):
  - ``investigate_incident(incident_id)``  run the Phase 2 agent on an incident
  - ``query_logs(query, earliest)``        passthrough to the Splunk tool
  - ``check_vendor_api(vendor)``           passthrough to the Saboten vendor tool

Prompts (templates the user can invoke by name):
  - ``incident-triage``                    generic "walk me through this"
  - ``stuck-jobs``                         Saboten job-queue flavored
  - ``worker-crash-loop``                  worker is crashlooping
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from argus.config import ArgusConfig
from argus.investigate.agent import InvestigationAgent
from argus.models import Incident

if TYPE_CHECKING:
    from argus.core.state import IncidentStore
    from argus.plugins import Hub

logger = logging.getLogger(__name__)

SERVER_NAME = "argus"
SERVER_VERSION = "0.1.0"


class ArgusMCP:
    """MCP server adapter.

    Keeps the SDK boundary thin: the handlers below return plain Python
    objects / dicts; wiring them to the official ``mcp`` SDK is a few
    lines in ``run_stdio``. The split makes the handlers unit-testable
    without any transport.
    """

    def __init__(
        self,
        config: ArgusConfig,
        hub: Hub,
        incident_store: IncidentStore | None = None,
    ):
        self._config = config
        self._hub = hub
        self._store = incident_store

    # ---------- Resources ----------

    def list_resources(self) -> list[dict[str, Any]]:
        return [
            {
                "uri": "argus://incidents",
                "name": "Open incidents",
                "description": "All currently active (unresolved) incidents.",
                "mimeType": "application/json",
            },
            {
                "uri": "argus://services",
                "name": "Configured services",
                "description": "Services and the checks that watch each one.",
                "mimeType": "application/json",
            },
            {
                "uri": "argus://alerts/recent",
                "name": "Recent alert dispatches",
                "description": "The last 50 alerts fired across all channels.",
                "mimeType": "application/json",
            },
        ]

    async def read_resource(self, uri: str) -> str:
        if uri == "argus://incidents":
            return json.dumps(await self._list_incidents(), default=str, indent=2)
        if uri.startswith("argus://incident/"):
            incident_id = uri.removeprefix("argus://incident/")
            return json.dumps(await self._get_incident(incident_id), default=str, indent=2)
        if uri == "argus://services":
            return json.dumps(self._list_services(), default=str, indent=2)
        if uri == "argus://alerts/recent":
            return json.dumps({"alerts": [], "note": "not yet persisted"}, indent=2)
        return json.dumps({"error": f"unknown resource uri {uri!r}"})

    async def _list_incidents(self) -> dict[str, Any]:
        if self._store is None:
            return {"configured": False, "note": "no incident store attached to this MCP"}
        # The IncidentStore keys by dedup_key — we expose whatever is there.
        try:
            keys = await self._store._redis.keys("sentinel:incident:*")  # noqa: SLF001
            if not keys:
                return {"incidents": [], "count": 0}
            incidents = []
            for key in keys[:50]:
                raw = await self._store._redis.get(key)  # noqa: SLF001
                if raw:
                    incidents.append(json.loads(raw))
            return {"incidents": incidents, "count": len(incidents)}
        except Exception as exc:
            return {"error": f"failed to read incidents: {exc}"}

    async def _get_incident(self, incident_id: str) -> dict[str, Any]:
        if self._store is None:
            return {"error": "no incident store attached to this MCP"}
        try:
            raw = await self._store._redis.get(f"sentinel:incident:{incident_id}")  # noqa: SLF001
            if not raw:
                return {"error": f"incident {incident_id} not found"}
            return json.loads(raw)
        except Exception as exc:
            return {"error": f"lookup failed: {exc}"}

    def _list_services(self) -> dict[str, Any]:
        env = self._config.active_env
        services = {
            name: {
                "host": cfg.host,
                "checks": [
                    {"type": c.type, "path": c.path, "port": c.port, "interval": c.interval}
                    for c in cfg.checks
                ],
            }
            for name, cfg in env.services.items()
        }
        return {"environment": self._config.settings.environment, "services": services}

    # ---------- Tools ----------

    def list_tools(self) -> list[dict[str, Any]]:
        tools = [
            {
                "name": "investigate_incident",
                "description": (
                    "Run the Argus investigation agent on an existing incident. "
                    "Returns the agent's markdown report plus a brief summary."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "incident_id": {
                            "type": "string",
                            "description": "Argus incident id (not the Saboten external_job_id).",
                        },
                        "model": {
                            "type": "string",
                            "description": "Override the default investigation model.",
                        },
                    },
                    "required": ["incident_id"],
                },
            }
        ]
        # Expose every hub-registered investigation tool directly too, so the
        # MCP client can call them without going through the agent loop.
        for name, tool in self._hub.tools().items():
            tools.append(
                {
                    "name": name,
                    "description": tool.description,
                    "inputSchema": tool.args_model.model_json_schema(),
                }
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "investigate_incident":
            return await self._investigate(arguments)
        tool = self._hub.tools().get(name)
        if tool is None:
            return json.dumps({"error": f"unknown tool {name!r}"})
        try:
            result = await tool.call(arguments)
            return json.dumps(result, default=str, indent=2)
        except Exception as exc:
            logger.exception("MCP tool %s failed", name)
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    async def _investigate(self, args: dict[str, Any]) -> str:
        incident_id = args.get("incident_id", "")
        if not incident_id:
            return json.dumps({"error": "incident_id required"})
        if self._store is None:
            return json.dumps({"error": "no incident store attached"})
        raw = await self._store._redis.get(f"sentinel:incident:{incident_id}")  # noqa: SLF001
        if not raw:
            return json.dumps({"error": f"incident {incident_id} not found"})
        incident = Incident.model_validate_json(raw)
        agent = InvestigationAgent(self._hub, model=args.get("model") or "claude-opus-5-5")
        report = await agent.investigate(incident)
        return json.dumps(
            {
                "status": report.status,
                "summary": report.to_summary(),
                "markdown": report.markdown,
                "trajectory_steps": len(report.trajectory.steps),
                "tool_calls": report.trajectory.tool_call_count,
                "cost_usd": report.trajectory.estimated_cost_usd,
            },
            default=str,
            indent=2,
        )

    # ---------- Prompts ----------

    def list_prompts(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "incident-triage",
                "description": "Walk the operator through investigating any incident.",
                "arguments": [
                    {
                        "name": "incident_id",
                        "description": "Argus incident id.",
                        "required": True,
                    }
                ],
            },
            {
                "name": "stuck-jobs",
                "description": "Saboten-specific stuck-jobs triage.",
                "arguments": [
                    {
                        "name": "job_type",
                        "description": "e.g. NCOA, DHC, Deceased.",
                        "required": False,
                    },
                    {
                        "name": "incident_id",
                        "description": "Optional incident to anchor on.",
                        "required": False,
                    },
                ],
            },
            {
                "name": "worker-crash-loop",
                "description": "Investigate a worker that's restarting repeatedly.",
                "arguments": [
                    {"name": "worker", "description": "Worker service name.", "required": True},
                ],
            },
        ]

    def get_prompt(self, name: str, arguments: dict[str, str]) -> dict[str, Any]:
        if name == "incident-triage":
            return _prompt_message(
                f"Investigate Argus incident {arguments.get('incident_id', '<missing>')}. "
                "Use the investigate_incident tool to run the agent, then summarize the "
                "root cause and recommended actions."
            )
        if name == "stuck-jobs":
            job_type = arguments.get("job_type") or "<all>"
            incident_hint = arguments.get("incident_id") or "the most recent stuck-jobs incident"
            return _prompt_message(
                f"We have stuck Saboten jobs for {job_type}. Start from {incident_hint}. "
                "Use investigate_incident, then check vendor health for the affected job type, "
                "and recommend remediation."
            )
        if name == "worker-crash-loop":
            worker = arguments.get("worker") or "<missing>"
            return _prompt_message(
                f"Worker {worker} is crashlooping. Investigate using recent deploys, "
                "recent PRs on the owning repo, and error logs."
            )
        return _prompt_message(f"(unknown prompt {name!r})")


def _prompt_message(text: str) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "user",
                "content": {"type": "text", "text": text},
            }
        ]
    }


async def run_stdio(mcp: ArgusMCP) -> None:
    """Wire the handlers to the official MCP SDK over stdio."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import (
            Prompt,
            PromptArgument,
            PromptMessage,
            Resource,
            TextContent,
            Tool,
        )
    except ImportError as exc:
        raise RuntimeError(
            "The 'mcp' extra is required. Install with: pip install -e '.[mcp]'"
        ) from exc

    server: Any = Server(SERVER_NAME)

    @server.list_resources()  # type: ignore[misc]
    async def _handle_list_resources() -> list[Any]:
        return [Resource(**r) for r in mcp.list_resources()]

    @server.read_resource()  # type: ignore[misc]
    async def _handle_read_resource(uri: Any) -> str:
        return await mcp.read_resource(str(uri))

    @server.list_tools()  # type: ignore[misc]
    async def _handle_list_tools() -> list[Any]:
        return [Tool(**t) for t in mcp.list_tools()]

    @server.call_tool()  # type: ignore[misc]
    async def _handle_call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        payload = await mcp.call_tool(name, arguments or {})
        return [TextContent(type="text", text=payload)]

    @server.list_prompts()  # type: ignore[misc]
    async def _handle_list_prompts() -> list[Any]:
        out = []
        for p in mcp.list_prompts():
            out.append(
                Prompt(
                    name=p["name"],
                    description=p["description"],
                    arguments=[PromptArgument(**a) for a in p.get("arguments", [])],
                )
            )
        return out

    @server.get_prompt()  # type: ignore[misc]
    async def _handle_get_prompt(name: str, arguments: dict[str, str] | None) -> Any:
        result = mcp.get_prompt(name, arguments or {})
        return {
            "messages": [
                PromptMessage(role=m["role"], content=TextContent(**m["content"]))
                for m in result["messages"]
            ]
        }

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
