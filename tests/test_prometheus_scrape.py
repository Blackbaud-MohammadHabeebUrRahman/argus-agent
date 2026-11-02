"""Tests for the Prometheus scrape check."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from argus.models import CheckStatus
from argus.monitor.prometheus_scrape import (
    PrometheusScrapeCheck,
    _labels_match,
    _parse_metrics,
)

SAMPLE_METRICS = """\
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{code="200",method="GET"} 1024
http_requests_total{code="500",method="GET"} 7
# HELP app_memory_bytes Resident memory
# TYPE app_memory_bytes gauge
app_memory_bytes 83886080
"""


class TestParser:
    def test_parses_simple_counter(self):
        samples = _parse_metrics(SAMPLE_METRICS, "http_requests_total")
        assert len(samples) == 2
        labels_200 = next(labels for labels, _ in samples if labels.get("code") == "200")
        value_200 = next(v for labels, v in samples if labels.get("code") == "200")
        assert labels_200 == {"code": "200", "method": "GET"}
        assert value_200 == 1024.0

    def test_parses_unlabeled_gauge(self):
        samples = _parse_metrics(SAMPLE_METRICS, "app_memory_bytes")
        assert samples == [({}, 83886080.0)]

    def test_missing_metric_returns_empty(self):
        assert _parse_metrics(SAMPLE_METRICS, "nope") == []

    def test_label_matcher(self):
        assert _labels_match({"code": "500", "m": "GET"}, {"code": "500"})
        assert not _labels_match({"code": "200"}, {"code": "500"})
        assert _labels_match({"code": "500"}, {})


@pytest.fixture
def check_factory():
    def _make(**thresholds):
        return PrometheusScrapeCheck(
            name="scrape",
            service="svc",
            host="localhost",
            port=9090,
            path="/metrics",
            timeout=2,
            thresholds=thresholds,
        )

    return _make


class TestCheck:
    async def test_ok_when_value_below_warning(self, httpx_mock: HTTPXMock, check_factory):
        httpx_mock.add_response(url="http://localhost:9090/metrics", text=SAMPLE_METRICS)
        check = check_factory(
            metric="http_requests_total",
            labels={"code": "500"},
            warning=10,
            critical=100,
        )
        result = await check.execute()
        assert result.status == CheckStatus.OK
        assert result.details["value"] == 7

    async def test_warning_when_value_exceeds_warning(self, httpx_mock: HTTPXMock, check_factory):
        httpx_mock.add_response(url="http://localhost:9090/metrics", text=SAMPLE_METRICS)
        check = check_factory(
            metric="http_requests_total",
            labels={"code": "500"},
            warning=5,
            critical=100,
        )
        result = await check.execute()
        assert result.status == CheckStatus.WARNING

    async def test_critical_when_value_exceeds_critical(self, httpx_mock: HTTPXMock, check_factory):
        httpx_mock.add_response(url="http://localhost:9090/metrics", text=SAMPLE_METRICS)
        check = check_factory(
            metric="http_requests_total",
            labels={"code": "500"},
            warning=1,
            critical=5,
        )
        result = await check.execute()
        assert result.status == CheckStatus.CRITICAL

    async def test_unknown_when_metric_missing(self, httpx_mock: HTTPXMock, check_factory):
        httpx_mock.add_response(url="http://localhost:9090/metrics", text=SAMPLE_METRICS)
        check = check_factory(metric="never_defined", warning=1, critical=5)
        result = await check.execute()
        assert result.status == CheckStatus.UNKNOWN

    async def test_unknown_when_metric_config_missing(self, check_factory):
        check = check_factory()  # no metric: key
        result = await check.execute()
        assert result.status == CheckStatus.UNKNOWN

    async def test_critical_on_non_200(self, httpx_mock: HTTPXMock, check_factory):
        httpx_mock.add_response(url="http://localhost:9090/metrics", status_code=503, text="down")
        check = check_factory(metric="http_requests_total", warning=1, critical=5)
        result = await check.execute()
        assert result.status == CheckStatus.CRITICAL
