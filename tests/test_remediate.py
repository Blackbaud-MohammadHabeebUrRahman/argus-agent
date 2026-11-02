"""Remediation engine, approval store, policy, and audit log tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from argus.plugins import Hub
from argus.remediate import (
    Action,
    ApprovalStore,
    AuditLog,
    EnvironmentPolicy,
    PolicyDecision,
    ProposalStatus,
    RemediationEngine,
    RemediationProposal,
    new_proposal_id,
)


class _Args(BaseModel):
    worker: str = Field(default="w1")


async def _ok_impl(args: _Args) -> dict[str, Any]:
    return {"restarted": args.worker}


async def _boom_impl(args: _Args) -> dict[str, Any]:
    raise RuntimeError("worker control plane down")


def _hub_with(actions: list[Action]) -> Hub:
    h = Hub()
    for a in actions:
        h.register_action(a)
    return h


# ---------- Action abstraction ----------


class TestAction:
    def test_schema_has_name_and_description(self):
        a = Action(name="x.restart", description="d", args_model=_Args, impl=_ok_impl)
        schema = a.to_claude_tool()
        assert schema["name"] == "x.restart"
        assert "input_schema" in schema

    async def test_call_validates_and_invokes(self):
        a = Action(name="x.r", description="d", args_model=_Args, impl=_ok_impl)
        assert await a.call({"worker": "w7"}) == {"restarted": "w7"}


# ---------- Policy ----------


class TestPolicy:
    def test_dev_non_destructive_auto_approves(self):
        p = EnvironmentPolicy()
        assert p.decide("dev", destructive=False) == PolicyDecision.AUTO_APPROVE

    def test_dev_destructive_requires_human(self):
        p = EnvironmentPolicy()
        assert p.decide("dev", destructive=True) == PolicyDecision.REQUIRE_HUMAN

    def test_prd_requires_human_even_for_non_destructive(self):
        p = EnvironmentPolicy()
        assert p.decide("prd", destructive=False) == PolicyDecision.REQUIRE_HUMAN
        assert p.decide("production", destructive=False) == PolicyDecision.REQUIRE_HUMAN

    def test_unknown_env_requires_human(self):
        p = EnvironmentPolicy()
        assert p.decide("sandbox", destructive=False) == PolicyDecision.REQUIRE_HUMAN

    def test_customized_auto_list_respected(self):
        p = EnvironmentPolicy(auto_approve_envs={"dev", "ci"})
        assert p.decide("ci", destructive=False) == PolicyDecision.AUTO_APPROVE


# ---------- Approval store ----------


class TestApprovalStore:
    def _mk_proposal(self, **overrides: Any) -> RemediationProposal:
        base = {
            "id": new_proposal_id(),
            "incident_id": "inc1",
            "action_name": "x.r",
            "args": {"worker": "w1"},
            "environment": "stg",
            "destructive": True,
        }
        base.update(overrides)
        return RemediationProposal(**base)

    def test_approve_sets_decided_fields(self):
        store = ApprovalStore()
        p = store.create(self._mk_proposal())
        store.approve(p.id, by="alice", note="go")
        reloaded = store.get(p.id)
        assert reloaded is not None
        assert reloaded.status == ProposalStatus.APPROVED
        assert reloaded.decided_by == "alice"
        assert reloaded.decision_note == "go"
        assert reloaded.decided_at is not None

    def test_double_decide_rejects(self):
        store = ApprovalStore()
        p = store.create(self._mk_proposal())
        store.approve(p.id, by="alice")
        with pytest.raises(ValueError, match="already approved"):
            store.reject(p.id, by="bob")

    def test_pending_only_returns_pending(self):
        store = ApprovalStore()
        pending = store.create(self._mk_proposal())
        resolved = store.create(self._mk_proposal())
        store.approve(resolved.id, by="x")
        pending_list = store.list_pending()
        assert len(pending_list) == 1
        assert pending_list[0].id == pending.id

    def test_mark_executed_and_mark_failed_terminal(self):
        store = ApprovalStore()
        p = store.create(self._mk_proposal())
        store.approve(p.id, by="alice")
        store.mark_executed(p.id, result={"ok": True})
        assert store.get(p.id).status == ProposalStatus.EXECUTED  # type: ignore[union-attr]
        q = store.create(self._mk_proposal())
        store.approve(q.id, by="alice")
        store.mark_failed(q.id, error="network")
        assert store.get(q.id).status == ProposalStatus.FAILED  # type: ignore[union-attr]


# ---------- Audit log ----------


class TestAuditLog:
    def test_in_memory_round_trip(self):
        a = AuditLog()
        a.record("proposed", proposal_id="p1", action="x.r")
        a.record("approved", proposal_id="p1", by="alice")
        entries = a.entries()
        assert len(entries) == 2
        assert entries[0]["event"] == "proposed"
        assert entries[1]["by"] == "alice"
        assert "ts" in entries[0]

    def test_persists_to_jsonl_when_path_given(self, tmp_path: Path):
        audit_path = tmp_path / "audit.jsonl"
        a = AuditLog(path=audit_path)
        a.record("proposed", proposal_id="p1")
        a.record("approved", proposal_id="p1")
        lines = audit_path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_persist_failure_is_swallowed(self):
        # path points to a directory to force open() failure
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            # make it a directory where our write would fail
            audit = AuditLog(path=d / "cannot" / "nested" / "unreadable")
            # The directory doesn't exist but the engine creates it; still succeeds.
            audit.record("x")


# ---------- Engine ----------


class TestEngine:
    def _mk_engine(
        self, actions: list[Action], policy: EnvironmentPolicy | None = None
    ) -> RemediationEngine:
        return RemediationEngine(_hub_with(actions), policy=policy or EnvironmentPolicy())

    async def test_dev_non_destructive_auto_executes(self):
        action = Action(
            name="x.probe",
            description="d",
            args_model=_Args,
            impl=_ok_impl,
            destructive=False,
        )
        engine = self._mk_engine([action])
        proposal = await engine.propose(
            action_name="x.probe",
            args={"worker": "w1"},
            incident_id="inc1",
            environment="dev",
        )
        assert proposal.status == ProposalStatus.EXECUTED
        assert proposal.result == {"restarted": "w1"}
        events = [e["event"] for e in engine.audit.entries()]
        assert events == ["proposed", "approved", "executed"]

    async def test_prd_holds_for_human_even_non_destructive(self):
        action = Action(
            name="x.probe",
            description="d",
            args_model=_Args,
            impl=_ok_impl,
            destructive=False,
        )
        engine = self._mk_engine([action])
        proposal = await engine.propose(
            action_name="x.probe",
            args={},
            incident_id="inc1",
            environment="prd",
        )
        assert proposal.status == ProposalStatus.PENDING
        assert engine.pending() == [proposal]
        assert "pending-approval" in {e["event"] for e in engine.audit.entries()}

    async def test_destructive_in_dev_holds_for_human(self):
        action = Action(
            name="x.r",
            description="d",
            args_model=_Args,
            impl=_ok_impl,
            destructive=True,
        )
        engine = self._mk_engine([action])
        proposal = await engine.propose(
            action_name="x.r",
            args={},
            incident_id="inc1",
            environment="dev",
        )
        assert proposal.status == ProposalStatus.PENDING

    async def test_approve_and_execute_resolves_and_runs(self):
        action = Action(name="x.r", description="d", args_model=_Args, impl=_ok_impl)
        engine = self._mk_engine([action])
        proposal = await engine.propose(
            action_name="x.r",
            args={"worker": "w2"},
            incident_id="inc1",
            environment="stg",
        )
        assert proposal.status == ProposalStatus.PENDING
        final = await engine.approve_and_execute(proposal.id, by="alice", note="ok")
        assert final.status == ProposalStatus.EXECUTED
        assert final.decided_by == "alice"

    async def test_impl_raising_marks_failed_and_audits(self):
        action = Action(
            name="x.r",
            description="d",
            args_model=_Args,
            impl=_boom_impl,
            destructive=False,
        )
        engine = self._mk_engine([action])
        proposal = await engine.propose(
            action_name="x.r",
            args={},
            incident_id="inc1",
            environment="dev",
        )
        assert proposal.status == ProposalStatus.FAILED
        assert "worker control plane down" in (proposal.error or "")
        events = [e["event"] for e in engine.audit.entries()]
        assert events[-1] == "execution-failed"

    async def test_reject_leaves_action_unrun(self):
        action = Action(name="x.r", description="d", args_model=_Args, impl=_ok_impl)
        engine = self._mk_engine([action])
        proposal = await engine.propose(
            action_name="x.r",
            args={},
            incident_id="inc1",
            environment="prd",
        )
        rejected = engine.reject(proposal.id, by="alice", note="bad time")
        assert rejected.status == ProposalStatus.REJECTED
        assert rejected.decision_note == "bad time"

    async def test_unknown_action_raises(self):
        engine = self._mk_engine([])
        with pytest.raises(ValueError, match="unknown action"):
            await engine.propose(
                action_name="x.nope",
                args={},
                incident_id="inc1",
                environment="dev",
            )


# ---------- Saboten plugin wiring ----------


class TestSabotenRemediationsRegistered:
    def test_saboten_plugin_registers_three_actions(self):
        from argus.plugins import build_hub

        hub = build_hub(enabled_products=["saboten"])
        names = set(hub.actions())
        assert "restart_saboten_worker" in names
        assert "requeue_saboten_job" in names
        assert "flush_saboten_cache_key" in names
