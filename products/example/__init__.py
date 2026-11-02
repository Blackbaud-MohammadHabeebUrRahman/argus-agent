"""Example plugin.

Exists so Argus always has at least two plugins loaded: it proves the
core framework is not tied to Saboten, and gives new plugin authors a
minimal template to copy. Delete this plugin in a real deployment.

See ``docs/writing-a-plugin.md``.
"""

from __future__ import annotations

from argus.plugins import Hub

from .checks import register_checks


def register(hub: Hub) -> None:
    """Entry point called by Argus to install the example plugin."""
    register_checks(hub)
