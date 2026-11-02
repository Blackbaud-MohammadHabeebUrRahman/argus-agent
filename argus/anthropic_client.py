"""Shared ``AsyncAnthropic`` factory.

Keeps the Anthropic client construction in one place so the investigation
agent and the eval judge build identical clients. Two things vary and the
factory handles both automatically:

1. **Key type.** ``sk-ant-api-...`` keys are plain API keys and go in the
   ``x-api-key`` header. ``sk-ant-usr-...`` keys are OAuth-style user
   tokens and must be sent as ``Authorization: Bearer`` plus the beta
   header ``anthropic-beta: oauth-2025-04-20``. Mixing these up gets a
   ``401 invalid x-api-key``.

2. **Workspace binding.** User-scoped keys aren't tied to a workspace, so
   the request needs an ``anthropic-workspace-id`` header. Workspace-scoped
   keys already encode this and don't need it.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_OAUTH_KEY_PREFIX = "sk-ant-usr-"
_OAUTH_BETA_HEADER = "oauth-2025-04-20"


def build_async_client(
    *,
    api_key: str | None = None,
    workspace_id: str | None = None,
    base_url: str | None = None,
) -> Any:
    """Return an ``anthropic.AsyncAnthropic`` configured from args + env.

    Resolution order per field:
      - ``api_key``: explicit arg, else ``ANTHROPIC_API_KEY``, else
        ``ARGUS_ANTHROPIC_API_KEY``, else SDK default (OAuth profile, …).
      - ``workspace_id``: explicit arg, else ``ARGUS_ANTHROPIC_WORKSPACE_ID``,
        else ``ANTHROPIC_WORKSPACE_ID``. Omitted entirely if unset.
      - ``base_url``: explicit arg, else SDK default.
    """
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' package is required. Install with: pip install -e '.[ai]'"
        ) from exc

    kwargs: dict[str, Any] = {}
    headers: dict[str, str] = {}

    resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("ARGUS_ANTHROPIC_API_KEY")
    if resolved_key and resolved_key.startswith(_OAUTH_KEY_PREFIX):
        # OAuth-style user token: Bearer auth + OAuth beta flag.
        # Also unset ANTHROPIC_API_KEY in this process so the SDK's own env
        # fallback doesn't ALSO attach an x-api-key header — the server
        # validates x-api-key first and rejects the usr key there with a 401.
        kwargs["auth_token"] = resolved_key
        headers["anthropic-beta"] = _OAUTH_BETA_HEADER
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        logger.debug("anthropic client using OAuth-style user key")
    elif resolved_key:
        kwargs["api_key"] = resolved_key

    ws_id = (
        workspace_id
        or os.getenv("ARGUS_ANTHROPIC_WORKSPACE_ID")
        or os.getenv("ANTHROPIC_WORKSPACE_ID")
    )
    if ws_id:
        headers["anthropic-workspace-id"] = ws_id
        logger.debug("anthropic client scoped to workspace %s", ws_id)

    if headers:
        kwargs["default_headers"] = headers
    if base_url:
        kwargs["base_url"] = base_url

    return AsyncAnthropic(**kwargs)
