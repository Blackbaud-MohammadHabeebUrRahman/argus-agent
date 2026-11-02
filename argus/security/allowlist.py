"""Per-severity tool allowlists.

A warning doesn't need the full tool surface a fatal needs. Scoping
down for the common case reduces the blast radius of a prompt
injection — if an attacker lands a steer in a warning-tier log line,
they can't convince the agent to call ``flush_cache_key`` because
flush_cache_key isn't in the allowlist for warning-tier runs.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from argus.models import Severity
from argus.plugins import Tool

logger = logging.getLogger(__name__)


@dataclass
class ToolAllowlist:
    """Per-severity allowlist for investigation tools.

    An empty set at a given severity means "all registered tools are
    allowed" (default-permissive); a non-empty set is strict.
    """

    info: set[str] = field(default_factory=set)
    warning: set[str] = field(default_factory=set)
    critical: set[str] = field(default_factory=set)
    fatal: set[str] = field(default_factory=set)

    def for_severity(self, severity: Severity) -> set[str]:
        return {
            Severity.INFO: self.info,
            Severity.WARNING: self.warning,
            Severity.CRITICAL: self.critical,
            Severity.FATAL: self.fatal,
        }.get(severity, set())


def filter_tools_for_severity(
    tools: Iterable[Tool],
    severity: Severity,
    allowlist: ToolAllowlist,
) -> list[Tool]:
    allowed = allowlist.for_severity(severity)
    if not allowed:
        return list(tools)
    out = [t for t in tools if t.name in allowed]
    dropped = [t.name for t in tools if t.name not in allowed]
    if dropped:
        logger.debug(
            "tool allowlist dropped %d tool(s) for severity=%s: %s",
            len(dropped),
            severity.value,
            dropped,
        )
    return out
