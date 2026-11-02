"""Splunk REST API client — stub for Phase 1.

The interface is defined here so the engine can reference it. Real
implementation will be wired up once Splunk REST API credentials are
available (coordinate with Daryl for stg/prd access).

Splunk sourcetypes for Saboten services:
  saboten:api, saboten:ikari, saboten:racha, saboten:tomi,
  saboten:mock-worker, saboten:shared-worker, saboten:admin-console,
  saboten:scorecard-generator, saboten:scorecards-dashboard,
  saboten:nginx, saboten:nginx:access, saboten:nginx:error

All events land in the ``bb_rdo_nix`` index.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SOURCETYPE_MAP = {
    "saboten-api": "saboten:api",
    "ikari-worker": "saboten:ikari",
    "racha-worker": "saboten:racha",
    "tomi-worker": "saboten:tomi",
    "mock-worker": "saboten:mock-worker",
    "admin-console": "saboten:admin-console",
    "scorecard-generator": "saboten:scorecard-generator",
    "nginx": "saboten:nginx",
}

DEFAULT_INDEX = "bb_rdo_nix"


class SplunkClient:
    """Splunk REST API client.

    Phase 1: stub implementation — logs a warning and returns empty results.
    Phase 2: real implementation using ``POST /services/search/jobs``.
    """

    def __init__(self, base_url: str = "", token: str = ""):
        self.base_url = base_url
        self.token = token
        self._configured = bool(base_url and token)
        if not self._configured:
            logger.warning(
                "SplunkClient not configured (no base_url/token) — "
                "operating in stub mode. Set SENTINEL_SPLUNK_BASE_URL "
                "and SENTINEL_SPLUNK_TOKEN to enable."
            )

    async def search(
        self,
        query: str,
        earliest: str = "-4h",
        latest: str = "now",
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """Run a Splunk search and return results.

        Parameters
        ----------
        query : str
            SPL query string (e.g., ``search index=bb_rdo_nix sourcetype=saboten:api levelname=ERROR``).
        earliest : str
            Relative or absolute time for search start.
        latest : str
            Relative or absolute time for search end.
        max_results : int
            Maximum results to return.
        """
        if not self._configured:
            logger.debug("SplunkClient stub: query=%s", query[:100])
            return []

        # Phase 2: real implementation
        # POST /services/search/jobs with search=<SPL>
        # Poll /services/search/jobs/<sid>/results until done
        # Parse XML/JSON results
        raise NotImplementedError("Real Splunk integration not yet implemented")

    async def get_error_logs(
        self,
        service: str,
        hours: int = 4,
        keywords: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Convenience: fetch ERROR-level logs for a service.

        Maps service name to Splunk sourcetype using SOURCETYPE_MAP.
        """
        sourcetype = SOURCETYPE_MAP.get(service, service)
        spl = f"search index={DEFAULT_INDEX} sourcetype={sourcetype} levelname=ERROR earliest=-{hours}h"
        if keywords:
            keyword_filter = " OR ".join(f'"{kw}"' for kw in keywords)
            spl += f" ({keyword_filter})"
        return await self.search(spl, earliest=f"-{hours}h")

    async def get_recent_logs(
        self,
        service: str,
        hours: int = 1,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch the most recent logs for a service."""
        sourcetype = SOURCETYPE_MAP.get(service, service)
        spl = f"search index={DEFAULT_INDEX} sourcetype={sourcetype} earliest=-{hours}h | head {max_results}"
        return await self.search(spl, earliest=f"-{hours}h", max_results=max_results)
