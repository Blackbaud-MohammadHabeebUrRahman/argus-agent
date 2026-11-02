"""Saboten remediation actions.

Three actions ship: restart a stuck worker, requeue a failed job, and
flush a specific Redis cache key. Impls are production-shaped stubs
pending wire-up to Saboten's orchestrator API and worker control
endpoints — the engine and approval flow are fully live, so the
operator-facing experience is the final one even while the hands-on
side is still a stub.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from argus.remediate.action import Action

if TYPE_CHECKING:
    from argus.plugins import Hub

logger = logging.getLogger(__name__)


class _RestartWorkerArgs(BaseModel):
    worker: str = Field(
        description=(
            "Worker service name: saboten-ikari-3, saboten-tomi-3, "
            "saboten-racha-worker-3, saboten-mock-worker-3."
        )
    )
    reason: str = Field(
        default="",
        description="Short free-text reason the operator / agent is restarting.",
    )


async def _restart_worker_stub(args: _RestartWorkerArgs) -> dict[str, Any]:
    logger.info("STUB: restart worker %s (reason: %s)", args.worker, args.reason)
    return {
        "configured": False,
        "action": "restart_saboten_worker",
        "worker": args.worker,
        "reason": args.reason,
        "note": (
            "Stubbed. Wire to the deploy system's restart hook "
            "(supervisorctl via ssh, ECS stop-task, Nomad restart, etc.)."
        ),
    }


class _RequeueJobArgs(BaseModel):
    external_job_id: str = Field(description="The Saboten external_job_id (UUID).")
    reason: str = Field(default="", description="Why requeue.")


async def _requeue_job_stub(args: _RequeueJobArgs) -> dict[str, Any]:
    logger.info("STUB: requeue job %s (reason: %s)", args.external_job_id, args.reason)
    return {
        "configured": False,
        "action": "requeue_saboten_job",
        "external_job_id": args.external_job_id,
        "reason": args.reason,
        "note": (
            "Stubbed. Wire to saboten-service-3's job-requeue endpoint "
            "(POST /api/1.0/jobs/{uuid}/requeue)."
        ),
    }


class _FlushCacheKeyArgs(BaseModel):
    cache_key: str = Field(description="Exact Redis key to delete.")
    reason: str = Field(default="", description="Why flush.")


async def _flush_cache_key_stub(args: _FlushCacheKeyArgs) -> dict[str, Any]:
    logger.info("STUB: flush cache key %s (reason: %s)", args.cache_key, args.reason)
    return {
        "configured": False,
        "action": "flush_saboten_cache_key",
        "cache_key": args.cache_key,
        "reason": args.reason,
        "note": "Stubbed. Wire to the Redis admin connection.",
    }


def register_remediations(hub: Hub) -> None:
    hub.register_action(
        Action(
            name="restart_saboten_worker",
            description=(
                "Restart a specific Saboten worker service. Destructive: in-flight "
                "job chunks on that worker will error and need requeue. Use when "
                "a worker is stuck or memory-saturated and a soft restart will "
                "clear it."
            ),
            args_model=_RestartWorkerArgs,
            impl=_restart_worker_stub,
            destructive=True,
        )
    )
    hub.register_action(
        Action(
            name="requeue_saboten_job",
            description=(
                "Requeue a failed Saboten job by external_job_id. The job returns "
                "to QUEUED and will be dispatched to a worker again. Use when a "
                "transient vendor error caused a job to fail."
            ),
            args_model=_RequeueJobArgs,
            impl=_requeue_job_stub,
            destructive=True,
        )
    )
    hub.register_action(
        Action(
            name="flush_saboten_cache_key",
            description=(
                "Delete a specific Redis cache key. Useful when a cached vendor "
                "response went stale. Narrowly scoped to one key — never flush "
                "all; call the action per-key with named keys."
            ),
            args_model=_FlushCacheKeyArgs,
            impl=_flush_cache_key_stub,
            destructive=True,
        )
    )
