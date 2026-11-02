"""Shared ``AsyncAnthropic`` factory.

Keeps the Anthropic client construction in one place so the investigation
agent and the eval judge build identical clients. Reads optional
workspace-id header from env — required for user-scoped keys
(``sk-ant-usr-...``), unused for workspace-scoped keys
(``sk-ant-api-...``).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def build_async_client(
    *,
    api_key: str | None = None,
    workspace_id: str | None = None,
    base_url: str | None = None,
) -> Any:
    """Return an ``anthropic.AsyncAnthropic`` configured from args + env.

    Resolution order per field:
      - ``api_key``: explicit arg, else SDK default (ANTHROPIC_API_KEY, OAuth, …).
      - ``workspace_id``: explicit arg, else ``ARGUS_ANTHROPIC_WORKSPACE_ID``,
        else ``ANTHROPIC_WORKSPACE_ID``. Omitted entirely if unset.
      - ``base_url``: explicit arg, else ``ANTHROPIC_BASE_URL``, else SDK default.
    """
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' package is required. Install with: pip install -e '.[ai]'"
        ) from exc

    kwargs: dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    ws_id = (
        workspace_id
        or os.getenv("ARGUS_ANTHROPIC_WORKSPACE_ID")
        or os.getenv("ANTHROPIC_WORKSPACE_ID")
    )
    if ws_id:
        kwargs["default_headers"] = {"anthropic-workspace-id": ws_id}
        logger.debug("anthropic client scoped to workspace %s", ws_id)
    return AsyncAnthropic(**kwargs)
