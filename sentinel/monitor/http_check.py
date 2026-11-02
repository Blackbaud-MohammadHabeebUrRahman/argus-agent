from __future__ import annotations

import time
import logging

import httpx

from sentinel.models import CheckResult, CheckStatus
from .base import HealthCheck

logger = logging.getLogger(__name__)


class HttpCheck(HealthCheck):
    """Check that an HTTP endpoint responds with 200."""

    def __init__(
        self,
        name: str,
        service: str,
        host: str,
        port: int = 80,
        path: str = "/",
        scheme: str = "http",
        **kwargs,
    ):
        super().__init__(name=name, service=service, **kwargs)
        self.url = f"{scheme}://{host}:{port}{path}"

    async def execute(self) -> CheckResult:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                resp = await client.get(self.url)
            duration_ms = (time.monotonic() - start) * 1000

            if resp.status_code == 200:
                return self._result(
                    CheckStatus.OK,
                    f"{self.url} responded 200",
                    duration_ms=duration_ms,
                    details={"status_code": resp.status_code},
                )
            else:
                return self._result(
                    CheckStatus.CRITICAL,
                    f"{self.url} returned {resp.status_code}",
                    duration_ms=duration_ms,
                    details={"status_code": resp.status_code},
                )
        except httpx.TimeoutException:
            duration_ms = (time.monotonic() - start) * 1000
            return self._result(
                CheckStatus.CRITICAL,
                f"{self.url} timed out after {self.timeout}s",
                duration_ms=duration_ms,
            )
        except httpx.ConnectError as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return self._result(
                CheckStatus.CRITICAL,
                f"{self.url} connection refused: {exc}",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.exception("Unexpected error checking %s", self.url)
            return self._result(
                CheckStatus.UNKNOWN,
                f"{self.url} check failed: {exc}",
                duration_ms=duration_ms,
            )
