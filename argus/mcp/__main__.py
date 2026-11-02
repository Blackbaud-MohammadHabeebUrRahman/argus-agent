"""CLI: ``python -m argus.mcp`` runs the MCP server over stdio.

Wire this into Claude Code or Claude Desktop by registering it as an
MCP server — see docs/mcp.md for the config snippet.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from argus.config import load_config
from argus.core.state import IncidentStore
from argus.dotenv import load_dotenv_if_present
from argus.logging import configure_logging
from argus.plugins import build_hub

from .server import ArgusMCP, run_stdio

load_dotenv_if_present()


async def _run() -> None:
    config = load_config()
    # MCP server logs to stderr; stdout is the transport channel.
    configure_logging(level=config.settings.log_level, json_output=False)
    logger = logging.getLogger("argus.mcp")

    hub = build_hub(enabled_products=config.enabled_products)
    store = IncidentStore(config.settings.redis_url)
    mcp = ArgusMCP(config, hub, incident_store=store)

    logger.info("argus MCP server starting on stdio")
    try:
        await run_stdio(mcp)
    finally:
        await store.close()


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
