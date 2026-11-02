"""RemediationEngine: ties action registry, approval store, and audit together.

Flow:
  1. The investigation agent (or an operator via MCP) calls ``propose``
     with a plugin-registered action, args, and reasoning. The engine
     records the proposal, runs it through the environment policy, and
     either auto-approves (dev, non-destructive) or holds for human
     approval (stg/prd, or anything destructive).
  2. If auto-approved, the engine executes immediately and returns the
     result along with the final proposal state.
  3. If not auto-approved, the engine returns a pending proposal. An
     operator calls ``approve_and_execute`` (via CLI, MCP, Teams
     callback) to resolve it.
  4. Every state transition writes a line to the audit log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .approval import (
    ApprovalStore,
    ProposalStatus,
    RemediationProposal,
    new_proposal_id,
)
from .audit import AuditLog
from .policy import EnvironmentPolicy, PolicyDecision

if TYPE_CHECKING:
    from argus.plugins import Hub

logger = logging.getLogger(__name__)


class RemediationEngine:
    def __init__(
        self,
        hub: Hub,
        *,
        policy: EnvironmentPolicy | None = None,
        approvals: ApprovalStore | None = None,
        audit: AuditLog | None = None,
    ):
        self._hub = hub
        self._policy = policy or EnvironmentPolicy()
        self._approvals = approvals or ApprovalStore()
        self._audit = audit or AuditLog()

    @property
    def approvals(self) -> ApprovalStore:
        return self._approvals

    @property
    def audit(self) -> AuditLog:
        return self._audit

    async def propose(
        self,
        *,
        action_name: str,
        args: dict[str, Any],
        incident_id: str,
        environment: str,
        reasoning: str = "",
        proposed_by: str = "agent",
    ) -> RemediationProposal:
        action = self._hub.actions().get(action_name)
        if action is None:
            raise ValueError(f"unknown action {action_name!r}")

        proposal = RemediationProposal(
            id=new_proposal_id(),
            incident_id=incident_id,
            action_name=action_name,
            args=args,
            reasoning=reasoning,
            environment=environment,
            destructive=getattr(action, "destructive", True),
        )
        self._approvals.create(proposal)
        self._audit.record(
            "proposed",
            proposal_id=proposal.id,
            action=action_name,
            incident_id=incident_id,
            environment=environment,
            destructive=proposal.destructive,
            proposed_by=proposed_by,
            args=args,
        )

        decision = self._policy.decide(environment, destructive=proposal.destructive)
        if decision == PolicyDecision.AUTO_APPROVE:
            self._approvals.approve(proposal.id, by="policy:auto", note="auto-approved")
            self._audit.record(
                "approved",
                proposal_id=proposal.id,
                by="policy:auto",
                note=f"env={environment} non-destructive",
            )
            await self._execute(proposal)
        else:
            self._audit.record(
                "pending-approval",
                proposal_id=proposal.id,
                reason=f"env={environment} destructive={proposal.destructive}",
            )
        return self._approvals.get(proposal.id)  # type: ignore[return-value]

    async def approve_and_execute(
        self, proposal_id: str, *, by: str, note: str = ""
    ) -> RemediationProposal:
        proposal = self._approvals.approve(proposal_id, by=by, note=note)
        self._audit.record("approved", proposal_id=proposal_id, by=by, note=note)
        await self._execute(proposal)
        return self._approvals.get(proposal_id)  # type: ignore[return-value]

    def reject(self, proposal_id: str, *, by: str, note: str = "") -> RemediationProposal:
        proposal = self._approvals.reject(proposal_id, by=by, note=note)
        self._audit.record("rejected", proposal_id=proposal_id, by=by, note=note)
        return proposal

    async def _execute(self, proposal: RemediationProposal) -> None:
        action = self._hub.actions().get(proposal.action_name)
        if action is None:
            self._approvals.mark_failed(
                proposal.id, error=f"action {proposal.action_name!r} vanished before execution"
            )
            self._audit.record("execution-failed", proposal_id=proposal.id, error="action vanished")
            return
        try:
            result = await action.call(proposal.args)
        except Exception as exc:
            logger.exception("remediation action %s raised", proposal.action_name)
            self._approvals.mark_failed(proposal.id, error=f"{type(exc).__name__}: {exc}")
            self._audit.record(
                "execution-failed",
                proposal_id=proposal.id,
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self._approvals.mark_executed(proposal.id, result=result)
        self._audit.record("executed", proposal_id=proposal.id, result=result)

    def pending(self) -> list[RemediationProposal]:
        return self._approvals.list_pending()

    def status_of(self, proposal_id: str) -> ProposalStatus | None:
        p = self._approvals.get(proposal_id)
        return p.status if p else None
