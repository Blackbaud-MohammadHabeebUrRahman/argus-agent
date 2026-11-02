"""Per-environment auto-approve policy.

Policy says: "in dev, non-destructive actions run themselves; in
staging, destructive actions wait for a human; in prod, every action
waits for a human." Can be overridden via config.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PolicyDecision(str, Enum):
    AUTO_APPROVE = "auto"
    REQUIRE_HUMAN = "human"


class EnvironmentPolicy(BaseModel):
    """Which environments auto-approve, which require a human.

    Defaults are tuned for the common case: dev experiments freely,
    staging holds destructive moves, production holds everything.
    """

    auto_approve_envs: set[str] = Field(default_factory=lambda: {"dev"})
    always_human_envs: set[str] = Field(default_factory=lambda: {"prd", "prod", "production"})

    def decide(self, environment: str, *, destructive: bool) -> PolicyDecision:
        env = environment.lower()
        if env in self.always_human_envs:
            return PolicyDecision.REQUIRE_HUMAN
        if destructive:
            return PolicyDecision.REQUIRE_HUMAN
        if env in self.auto_approve_envs:
            return PolicyDecision.AUTO_APPROVE
        return PolicyDecision.REQUIRE_HUMAN
