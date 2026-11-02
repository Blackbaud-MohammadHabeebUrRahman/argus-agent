"""Saboten investigation tools.

Layer product knowledge on top of the core tools: convenience wrappers
that know Saboten's log sourcetypes, the orchestrator's job-lookup
endpoint, and which vendor APIs each job type calls.

Phase 2 ships two production-shaped stubs — ``get_saboten_job_history``
and ``check_saboten_vendor_api_health``. Both return canned responses
until real backend integration is wired up (the orchestrator's
``/api/1.0/jobs/{uuid}`` and the vendor status endpoints), which is a
Phase 2b job the Blackbaud ops team will drive.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from argus.plugins import Tool

if TYPE_CHECKING:
    from argus.plugins import Hub

logger = logging.getLogger(__name__)

# Vendor APIs Saboten calls, indexed by job type.
_VENDOR_API: dict[str, str] = {
    "NCOA": "Anchor NCOA (USPS)",
    "Deceased": "Anchor Deceased",
    "DHC": "DHC Scorecard",
    "Fundraising": "BBDS WealthService",
    "Social": "Anchor Social",
    "EDQ": "Experian EDQ",
}


class _JobHistoryArgs(BaseModel):
    external_job_id: str = Field(description="The Saboten external_job_id (UUID).")


async def _job_history_stub(args: _JobHistoryArgs) -> dict[str, Any]:
    return {
        "configured": False,
        "message": (
            "Saboten orchestrator credentials not configured in this build. "
            "Wire this to GET /api/1.0/jobs/{uuid} on saboten-service-3 to "
            "return actual state history."
        ),
        "external_job_id": args.external_job_id,
    }


class _VendorHealthArgs(BaseModel):
    vendor: str = Field(
        description=(f"The vendor name to probe. One of: {', '.join(sorted(_VENDOR_API))}.")
    )


async def _vendor_health_stub(args: _VendorHealthArgs) -> dict[str, Any]:
    api = _VENDOR_API.get(args.vendor)
    if not api:
        return {
            "configured": False,
            "error": f"unknown vendor {args.vendor!r}",
            "known_vendors": sorted(_VENDOR_API),
        }
    return {
        "configured": False,
        "message": (
            f"Vendor status endpoints not configured. Wire this to {api}'s "
            f"status page or health endpoint to probe availability."
        ),
        "vendor": args.vendor,
        "api": api,
    }


def register_tools(hub: Hub) -> None:
    """Install Saboten-specific investigation tools on the hub."""
    hub.register_tool(
        Tool(
            name="get_saboten_job_history",
            description=(
                "Look up a Saboten job by its external_job_id and return its "
                "state transitions, timestamps, worker that picked it up, "
                "and the vendor API it called. Essential when investigating "
                "a stuck or failed job — stuck_jobs_critical alerts should "
                "always start with this. (Currently stubbed until orchestrator "
                "API access is wired up.)"
            ),
            args_model=_JobHistoryArgs,
            impl=_job_history_stub,
        )
    )
    hub.register_tool(
        Tool(
            name="check_saboten_vendor_api_health",
            description=(
                "Probe the health/status endpoint of a vendor Saboten "
                "depends on (NCOA, Deceased, DHC, Fundraising/BBDS, Social, "
                "EDQ). A vendor outage shows up here before it shows up in "
                "job-queue metrics. (Currently stubbed until vendor status "
                "endpoints are wired up.)"
            ),
            args_model=_VendorHealthArgs,
            impl=_vendor_health_stub,
        )
    )
