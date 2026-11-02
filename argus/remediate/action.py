"""Action abstraction: the thing the agent proposes and the operator approves.

Deliberately mirrors ``argus/plugins.py:Tool`` so plugin authors who've
already written tools have an obvious analog. The one new field is
``destructive``: an action with ``destructive=True`` can only run after
explicit human approval, no matter what the environment policy says.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Action:
    """A remediation step a plugin exposes to the engine.

    ``name`` is the stable id the agent asks for (dotted convention,
    e.g. ``saboten.restart_worker``).
    ``args_model`` carries the args schema the agent must satisfy —
    same pydantic pattern as ``Tool``.
    ``impl`` is the async callable that actually performs the action.
    ``destructive`` is ``True`` for anything that mutates production
    state in a way the operator wants eyes on even in auto-approve
    environments.
    """

    name: str
    description: str
    args_model: type[BaseModel]
    impl: Callable[[Any], Awaitable[Any]]
    destructive: bool = True

    def to_claude_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args_model.model_json_schema(),
        }

    async def call(self, raw_input: dict[str, Any]) -> Any:
        args = self.args_model(**raw_input)
        return await self.impl(args)
