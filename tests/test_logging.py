"""Structured-logging smoke tests."""

from __future__ import annotations

import json
import logging

from sentinel.logging import configure_logging


def test_json_formatter_round_trips(capsys):
    configure_logging(level="INFO", json_output=True)
    logging.getLogger("test.json").info("hello", extra={"job_id": "abc-123"})
    captured = capsys.readouterr().out.strip().splitlines()
    assert captured, "expected at least one log line"
    payload = json.loads(captured[-1])
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.json"
    assert payload["job_id"] == "abc-123"
    assert "ts" in payload


def test_configure_logging_is_idempotent(capsys):
    configure_logging(level="INFO")
    configure_logging(level="INFO")
    logging.getLogger("test.idemp").info("once")
    captured = capsys.readouterr().out.strip().splitlines()
    assert len(captured) == 1


def test_text_mode_falls_back_to_plain_format(capsys):
    configure_logging(level="INFO", json_output=False)
    logging.getLogger("test.text").info("plain-mode")
    out = capsys.readouterr().out
    assert "plain-mode" in out
    # Not JSON — should fail to parse
    import pytest

    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip().splitlines()[-1])
