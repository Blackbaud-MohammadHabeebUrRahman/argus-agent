from __future__ import annotations

import logging
import time
from typing import Any

from sentinel.models import CheckStatus

from .base import CheckResult, HealthCheck

logger = logging.getLogger(__name__)


class RedisCheck(HealthCheck):
    """Check Redis connectivity, queue depth, and memory usage."""

    def __init__(
        self,
        name: str,
        service: str,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        **kwargs,
    ):
        super().__init__(name=name, service=service, **kwargs)
        self.host = host
        self.port = port
        self.db = db
        self.queue_depth_warning = self.thresholds.get("queue_depth_warning", 100)
        self.queue_depth_critical = self.thresholds.get("queue_depth_critical", 500)
        self.memory_pct_warning = self.thresholds.get("memory_pct_warning", 80)

    async def execute(self) -> CheckResult:
        start = time.monotonic()
        try:
            import redis.asyncio as aioredis

            client = aioredis.Redis(
                host=self.host, port=self.port, db=self.db, socket_timeout=self.timeout
            )
            try:
                pong = await client.ping()
                if not pong:
                    duration_ms = (time.monotonic() - start) * 1000
                    return self._result(
                        CheckStatus.CRITICAL,
                        f"Redis at {self.host}:{self.port} did not respond to PING",
                        duration_ms=duration_ms,
                    )

                info = await client.info("memory")
                used_memory = info.get("used_memory", 0)
                max_memory = info.get("maxmemory", 0)
                memory_pct = (used_memory / max_memory * 100) if max_memory > 0 else 0

                db_info = await client.info("keyspace")
                total_keys = sum(
                    v.get("keys", 0)
                    for k, v in db_info.items()
                    if k.startswith("db") and isinstance(v, dict)
                )

                queue_depth = await client.llen("celery")

                details: dict[str, Any] = {
                    "used_memory_mb": round(used_memory / 1024 / 1024, 2),
                    "max_memory_mb": round(max_memory / 1024 / 1024, 2)
                    if max_memory
                    else "unlimited",
                    "memory_pct": round(memory_pct, 1),
                    "total_keys": total_keys,
                    "celery_queue_depth": queue_depth,
                }

                issues: list[str] = []
                status = CheckStatus.OK

                if queue_depth >= self.queue_depth_critical:
                    status = CheckStatus.CRITICAL
                    issues.append(
                        f"Celery queue depth {queue_depth} >= {self.queue_depth_critical}"
                    )
                elif queue_depth >= self.queue_depth_warning:
                    status = CheckStatus.WARNING
                    issues.append(f"Celery queue depth {queue_depth} >= {self.queue_depth_warning}")

                if memory_pct >= self.memory_pct_warning:
                    if status != CheckStatus.CRITICAL:
                        status = CheckStatus.WARNING
                    issues.append(f"Memory usage {memory_pct:.1f}% >= {self.memory_pct_warning}%")

                duration_ms = (time.monotonic() - start) * 1000

                if status == CheckStatus.OK:
                    return self._result(
                        CheckStatus.OK,
                        f"Redis healthy (queue={queue_depth}, mem={memory_pct:.1f}%)",
                        duration_ms=duration_ms,
                        details=details,
                    )
                else:
                    return self._result(
                        status,
                        "; ".join(issues),
                        duration_ms=duration_ms,
                        details=details,
                    )
            finally:
                await client.aclose()

        except ImportError:
            return self._result(
                CheckStatus.UNKNOWN,
                "redis package not installed",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return self._result(
                CheckStatus.CRITICAL,
                f"Redis connection failed: {exc}",
                duration_ms=duration_ms,
            )
