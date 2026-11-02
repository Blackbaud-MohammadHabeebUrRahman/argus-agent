"""Approval store: the handshake between the agent proposing an action
and the operator saying go/no-go.

Each proposal gets an id. The engine ``propose`` writes a pending row;
``approve`` and ``reject`` resolve it. The MCP server, a Teams
Workflow callback, or an engineer running a CLI can all drive
``approve`` the same way.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


class RemediationProposal(BaseModel):
    id: str
    incident_id: str
    action_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    environment: str
    destructive: bool
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str = ""
    result: Any | None = None
    error: str | None = None


class ApprovalStore:
    """In-memory proposal store.

    Persisting to Redis is a one-method swap; the engine code uses only
    the public interface here. In-memory is enough for Phase 5 tests
    and local demos.
    """

    def __init__(self) -> None:
        self._proposals: dict[str, RemediationProposal] = {}

    def create(self, proposal: RemediationProposal) -> RemediationProposal:
        self._proposals[proposal.id] = proposal
        return proposal

    def get(self, proposal_id: str) -> RemediationProposal | None:
        return self._proposals.get(proposal_id)

    def list_pending(self) -> list[RemediationProposal]:
        return [p for p in self._proposals.values() if p.status == ProposalStatus.PENDING]

    def approve(self, proposal_id: str, *, by: str, note: str = "") -> RemediationProposal:
        return self._decide(proposal_id, ProposalStatus.APPROVED, by=by, note=note)

    def reject(self, proposal_id: str, *, by: str, note: str = "") -> RemediationProposal:
        return self._decide(proposal_id, ProposalStatus.REJECTED, by=by, note=note)

    def mark_executed(self, proposal_id: str, *, result: Any = None) -> RemediationProposal:
        p = self._require(proposal_id)
        p.status = ProposalStatus.EXECUTED
        p.result = result
        return p

    def mark_failed(self, proposal_id: str, *, error: str) -> RemediationProposal:
        p = self._require(proposal_id)
        p.status = ProposalStatus.FAILED
        p.error = error
        return p

    def _decide(
        self,
        proposal_id: str,
        new_status: ProposalStatus,
        *,
        by: str,
        note: str,
    ) -> RemediationProposal:
        p = self._require(proposal_id)
        if p.status != ProposalStatus.PENDING:
            raise ValueError(f"proposal {proposal_id} is already {p.status.value}")
        p.status = new_status
        p.decided_at = datetime.now(timezone.utc)
        p.decided_by = by
        p.decision_note = note
        return p

    def _require(self, proposal_id: str) -> RemediationProposal:
        p = self._proposals.get(proposal_id)
        if p is None:
            raise KeyError(f"proposal {proposal_id} not found")
        return p


def new_proposal_id() -> str:
    return "prop-" + uuid.uuid4().hex[:12]
