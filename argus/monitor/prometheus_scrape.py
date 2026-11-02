"""Prometheus/OpenMetrics scrape check.

Scrapes a target's ``/metrics`` endpoint, finds a named metric, and
compares its latest sample against configured warning/critical
thresholds. If the metric isn't found, returns UNKNOWN rather than OK —
a missing metric usually means something broke in exposition, not that
things are fine.

Config:

    - type: prometheus_scrape
      path: /metrics
      port: 9090
      thresholds:
        metric: "http_request_errors_total"
        warning: 10
        critical: 50
        # Optional: use a label matcher to pick one series out of many
        labels: {code: "500"}
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from argus.models import CheckResult, CheckStatus

from .base import HealthCheck

logger = logging.getLogger(__name__)


def _parse_metrics(text: str, metric_name: str) -> list[tuple[dict[str, str], float]]:
    """Minimal OpenMetrics-text parser.

    Returns list of (labels, value) for every sample whose metric name
    matches. Avoids the ``prometheus_client`` parser dep so core stays
    light.
    """
    samples: list[tuple[dict[str, str], float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Format: metric_name{labels} value [timestamp]
        name_end = len(line)
        for i, ch in enumerate(line):
            if ch in "{ ":
                name_end = i
                break
        name = line[:name_end]
        if name != metric_name:
            continue
        rest = line[name_end:].lstrip()
        labels: dict[str, str] = {}
        if rest.startswith("{"):
            close = rest.index("}")
            label_part = rest[1:close]
            rest = rest[close + 1 :].lstrip()
            for pair in _split_labels(label_part):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    labels[k.strip()] = v.strip().strip('"')
        value_str = rest.split()[0] if rest else ""
        try:
            value = float(value_str)
        except ValueError:
            continue
        samples.append((labels, value))
    return samples


def _split_labels(label_part: str) -> list[str]:
    """Split a label block on commas, respecting quoted commas."""
    parts: list[str] = []
    buf = ""
    in_quote = False
    for ch in label_part:
        if ch == '"':
            in_quote = not in_quote
            buf += ch
        elif ch == "," and not in_quote:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf:
        parts.append(buf)
    return parts


def _labels_match(sample_labels: dict[str, str], filter_labels: dict[str, str]) -> bool:
    return all(sample_labels.get(k) == v for k, v in filter_labels.items())


class PrometheusScrapeCheck(HealthCheck):
    """Fetch a Prometheus metrics endpoint and threshold a named metric."""

    def __init__(
        self,
        name: str,
        service: str,
        host: str,
        port: int = 9090,
        path: str = "/metrics",
        scheme: str = "http",
        **kwargs: Any,
    ):
        super().__init__(name=name, service=service, **kwargs)
        self.url = f"{scheme}://{host}:{port}{path}"
        self.metric_name = self.thresholds.get("metric", "")
        self.warning_level = self.thresholds.get("warning")
        self.critical_level = self.thresholds.get("critical")
        self.label_filter = self.thresholds.get("labels", {}) or {}

    async def execute(self) -> CheckResult:
        start = time.monotonic()
        if not self.metric_name:
            return self._result(
                CheckStatus.UNKNOWN,
                "prometheus_scrape missing thresholds.metric",
                duration_ms=0,
            )
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                resp = await client.get(self.url)
            duration_ms = (time.monotonic() - start) * 1000
            if resp.status_code != 200:
                return self._result(
                    CheckStatus.CRITICAL,
                    f"{self.url} returned {resp.status_code}",
                    duration_ms=duration_ms,
                    details={"status_code": resp.status_code},
                )
            samples = _parse_metrics(resp.text, self.metric_name)
            matching = [
                (labels, value)
                for labels, value in samples
                if _labels_match(labels, self.label_filter)
            ]
            if not matching:
                return self._result(
                    CheckStatus.UNKNOWN,
                    f"metric {self.metric_name!r} not found at {self.url}",
                    duration_ms=duration_ms,
                    details={"metric": self.metric_name, "label_filter": self.label_filter},
                )
            # If multiple series match, take the max — most conservative.
            value = max(value for _, value in matching)
            details = {
                "metric": self.metric_name,
                "value": value,
                "label_filter": self.label_filter,
                "matched_series": len(matching),
            }
            if self.critical_level is not None and value >= self.critical_level:
                return self._result(
                    CheckStatus.CRITICAL,
                    f"{self.metric_name}={value} >= critical {self.critical_level}",
                    duration_ms=duration_ms,
                    details=details,
                )
            if self.warning_level is not None and value >= self.warning_level:
                return self._result(
                    CheckStatus.WARNING,
                    f"{self.metric_name}={value} >= warning {self.warning_level}",
                    duration_ms=duration_ms,
                    details=details,
                )
            return self._result(
                CheckStatus.OK,
                f"{self.metric_name}={value} within thresholds",
                duration_ms=duration_ms,
                details=details,
            )
        except httpx.TimeoutException:
            duration_ms = (time.monotonic() - start) * 1000
            return self._result(
                CheckStatus.CRITICAL,
                f"{self.url} timed out after {self.timeout}s",
                duration_ms=duration_ms,
            )
        except (httpx.ConnectError, httpx.RequestError) as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return self._result(
                CheckStatus.CRITICAL,
                f"{self.url} unreachable: {exc}",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.exception("Unexpected error scraping %s", self.url)
            return self._result(
                CheckStatus.UNKNOWN,
                f"{self.url} scrape failed: {exc}",
                duration_ms=duration_ms,
            )
