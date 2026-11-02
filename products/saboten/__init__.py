"""Saboten plugin.

Blackbaud's internal data-enrichment orchestration platform. The first
production target for Argus and the reference implementation for the
plugin interface.

See ``docs/writing-a-plugin.md`` for how this is wired up.
"""

from __future__ import annotations

from argus.plugins import Hub

from .checks import register_checks


def register(hub: Hub) -> None:
    """Entry point called by Argus to install Saboten-specific features."""
    register_checks(hub)
    # register_tools(hub) will land in Phase 2 (investigation agent).
    # register_remediations(hub) will land in Phase 5 (HITL remediation).
