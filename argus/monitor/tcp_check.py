"""Generic TCP port-open check.

Succeeds when a TCP connection to ``host:port`` opens within the timeout.
Useful for anything that doesn't speak HTTP: databases, caches, custom
daemons, etc.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from argus.models import CheckResult, CheckStatus

from .base import HealthCheck

logger = logging.getLogger(__name__)


class TcpCheck(HealthCheck):
    """Open a TCP connection and close it. Status derived from success/latency."""

    def __init__(self, name: str, service: str, host: str, port: int, **kwargs: Any):
        super().__init__(name=name, service=service, **kwargs)
        self.host = host
        self.port = port

    async def execute(self) -> CheckResult:
        start = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            writer.close()
            # wait_closed can raise on some platforms when the peer already
            # dropped the connection; the open succeeded, so the check passed.
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            duration_ms = (time.monotonic() - start) * 1000
            return self._result(
                CheckStatus.OK,
                f"{self.host}:{self.port} reachable",
                duration_ms=duration_ms,
                details={"host": self.host, "port": self.port},
            )
        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - start) * 1000
            return self._result(
                CheckStatus.CRITICAL,
                f"{self.host}:{self.port} timed out after {self.timeout}s",
                duration_ms=duration_ms,
            )
        except (ConnectionRefusedError, OSError) as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return self._result(
                CheckStatus.CRITICAL,
                f"{self.host}:{self.port} refused: {exc}",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.exception("Unexpected error on tcp check %s:%d", self.host, self.port)
            return self._result(
                CheckStatus.UNKNOWN,
                f"{self.host}:{self.port} check failed: {exc}",
                duration_ms=duration_ms,
            )
