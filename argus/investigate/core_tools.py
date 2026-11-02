"""Core investigation tools — generic, no product knowledge required.

Four tools ship by default:

- ``get_incident_context``: full incident record from the store (resolved
  or active, with recent check results and timeline). Always available.
- ``query_splunk``: run arbitrary SPL against the configured Splunk
  instance. Falls back to a canned "no credentials configured" response
  so demos work without live Splunk.
- ``get_recent_deploys``: stub that returns an empty list by default —
  deploy systems vary too much to hardcode. Operators wire this to
  Spinnaker / Argo CD / Jenkins / Octopus / their own system.
- ``search_github_prs``: real GitHub Search API when a token is set,
  stubbed empty otherwise.

Plugin-contributed tools (e.g. ``get_saboten_job_history``) live under
``products/<name>/tools.py`` and layer on top of these.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, Field

from argus.integrations.splunk_api import SplunkClient
from argus.plugins import Tool

if TYPE_CHECKING:
    from argus.core.state import IncidentStore
    from argus.plugins import Hub

logger = logging.getLogger(__name__)


# ---------- get_incident_context ----------


class _IncidentContextArgs(BaseModel):
    incident_id: str = Field(description="The Argus incident id to look up.")


def _make_incident_context_tool(store: IncidentStore | None) -> Tool:
    async def impl(args: _IncidentContextArgs) -> dict[str, Any]:
        if store is None:
            return {"error": "no incident store configured in this process"}
        # The current store API keys by dedup key (check:service:env). The
        # agent only has incident_id, so scan — fine for a tool call cost
        # that happens at most ~20 times per investigation.
        try:
            incident_bytes = await store._redis.get(  # noqa: SLF001 — until a get_by_id helper exists
                f"sentinel:incident:{args.incident_id}"
            )
        except Exception as exc:
            return {"error": f"failed to query incident store: {exc}"}
        if not incident_bytes:
            return {
                "error": f"incident {args.incident_id} not found",
                "hint": "the incident may have resolved and been evicted",
            }
        return {"raw": incident_bytes}

    return Tool(
        name="get_incident_context",
        description=(
            "Look up the full stored record for an incident by its id — "
            "severity, timestamps, the last several check results, and "
            "whatever details the check attached. Use this once at the "
            "start of an investigation to confirm what the dispatch "
            "message summarized."
        ),
        args_model=_IncidentContextArgs,
        impl=impl,
    )


# ---------- query_splunk ----------


class _QuerySplunkArgs(BaseModel):
    query: str = Field(
        description=(
            "An SPL search string, starting with 'search'. Example: "
            "'search index=prod sourcetype=api_access status>=500 earliest=-1h'."
        )
    )
    earliest: str = Field(
        default="-1h",
        description="Relative or absolute time for the search start (e.g. '-15m', '-24h').",
    )
    max_results: int = Field(
        default=50,
        description="Cap on the number of events returned. Keep small to control token spend.",
    )


def _make_query_splunk_tool() -> Tool:
    client = SplunkClient(
        base_url=os.getenv("ARGUS_SPLUNK_BASE_URL", ""),
        token=os.getenv("ARGUS_SPLUNK_TOKEN", ""),
    )

    async def impl(args: _QuerySplunkArgs) -> dict[str, Any]:
        if not client._configured:  # noqa: SLF001
            return {
                "configured": False,
                "message": (
                    "Splunk credentials not set (ARGUS_SPLUNK_BASE_URL / "
                    "ARGUS_SPLUNK_TOKEN). This tool is stubbed in this "
                    "environment — report no evidence from Splunk."
                ),
                "echo_query": args.query,
            }
        results = await client.search(
            query=args.query,
            earliest=args.earliest,
            max_results=args.max_results,
        )
        return {"configured": True, "result_count": len(results), "results": results}

    return Tool(
        name="query_splunk",
        description=(
            "Run an SPL query against Splunk and return matching events. "
            "Useful for finding error spikes, status-code distributions, "
            "and specific log lines around an incident time. If credentials "
            "aren't configured in this environment the tool returns a "
            "stub response — report no Splunk evidence rather than inferring."
        ),
        args_model=_QuerySplunkArgs,
        impl=impl,
    )


# ---------- get_recent_deploys ----------


class _RecentDeploysArgs(BaseModel):
    service: str = Field(description="Service name to look up deploys for.")
    hours: int = Field(default=24, description="Lookback window in hours.")


async def _recent_deploys_stub(args: _RecentDeploysArgs) -> dict[str, Any]:
    return {
        "configured": False,
        "message": (
            "No deploy integration wired up in this build. Hook this up to "
            "your deploy system (Spinnaker, Argo CD, Jenkins, Octopus, custom) "
            "to make deploy correlation available to the agent."
        ),
        "service": args.service,
        "hours": args.hours,
    }


def _make_recent_deploys_tool() -> Tool:
    return Tool(
        name="get_recent_deploys",
        description=(
            "Return deploys of a service in the lookback window, most "
            "recent first. Recent deploys are the single highest-value "
            "signal for an incident — if a deploy went out an hour before "
            "the incident fired, that's your first hypothesis. If no "
            "deploy integration is wired up the tool returns a stub — "
            "report no deploy evidence rather than inferring."
        ),
        args_model=_RecentDeploysArgs,
        impl=_recent_deploys_stub,
    )


# ---------- search_github_prs ----------


class _SearchGithubPRsArgs(BaseModel):
    repo: str = Field(description="owner/name — e.g. 'blackbaud/saboten-service-3'.")
    since: str = Field(
        default="7d",
        description="Lookback window (Nd for days or Nh for hours).",
    )
    query: str = Field(
        default="",
        description="Optional extra GitHub search qualifiers (e.g. 'is:merged author:someone').",
    )


def _make_search_github_prs_tool() -> Tool:
    token = os.getenv("ARGUS_GITHUB_TOKEN", "")

    async def impl(args: _SearchGithubPRsArgs) -> dict[str, Any]:
        if not token:
            return {
                "configured": False,
                "message": "GITHUB token not set (ARGUS_GITHUB_TOKEN); tool stubbed.",
                "echo_args": args.model_dump(),
            }
        # Convert "Nd" / "Nh" to an ISO date string GitHub search understands.
        unit = args.since[-1] if args.since else "d"
        try:
            amount = int(args.since[:-1])
        except ValueError:
            amount = 7
            unit = "d"
        from datetime import datetime, timedelta, timezone

        delta = timedelta(hours=amount) if unit == "h" else timedelta(days=amount)
        since_date = (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%d")

        q_parts = [f"repo:{args.repo}", "is:pr", f"updated:>={since_date}"]
        if args.query.strip():
            q_parts.append(args.query.strip())
        q = " ".join(q_parts)

        async with httpx.AsyncClient(
            timeout=15,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        ) as client:
            resp = await client.get(
                "https://api.github.com/search/issues",
                params={"q": q, "per_page": 25, "sort": "updated", "order": "desc"},
            )
        if resp.status_code != 200:
            return {
                "configured": True,
                "error": f"github returned {resp.status_code}",
                "body": resp.text[:500],
            }
        data = resp.json()
        items = [
            {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "merged_at": pr.get("pull_request", {}).get("merged_at"),
                "user": (pr.get("user") or {}).get("login"),
                "html_url": pr.get("html_url"),
            }
            for pr in data.get("items", [])
        ]
        return {
            "configured": True,
            "query": q,
            "total_count": data.get("total_count", 0),
            "returned": len(items),
            "prs": items,
        }

    return Tool(
        name="search_github_prs",
        description=(
            "Search a GitHub repository for pull requests updated recently. "
            "Useful for correlating code changes with incidents. Pass "
            "repo as 'owner/name' and a lookback window like '24h' or '7d'. "
            "Optional 'query' adds raw GitHub search qualifiers "
            "('is:merged author:alice', 'label:hotfix', etc.)."
        ),
        args_model=_SearchGithubPRsArgs,
        impl=impl,
    )


# ---------- register ----------


def register_core_tools(hub: Hub, *, incident_store: IncidentStore | None = None) -> None:
    """Install the four core tools on the hub.

    ``incident_store`` is optional so the agent CLI can run against a
    JSON-dumped incident without a Redis connection.
    """
    hub.register_tool(_make_incident_context_tool(incident_store))
    hub.register_tool(_make_query_splunk_tool())
    hub.register_tool(_make_recent_deploys_tool())
    hub.register_tool(_make_search_github_prs_tool())
