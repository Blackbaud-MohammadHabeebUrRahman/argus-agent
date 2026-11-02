"""Immutable audit log of every remediation touch.

Writes JSONL to a configurable file. One line per event, structured so
Splunk / Loki / anything that ingests JSON can slice it. Every
proposal, decision, execution, and failure gets an entry; the chain
is what an incident-review board reads a month later.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, path: str | Path | None = None):
        self._path: Path | None = Path(path) if path else None
        self._entries: list[dict[str, Any]] = []

    def record(self, event: str, **fields: Any) -> dict[str, Any]:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        self._entries.append(entry)
        if self._path is not None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a") as f:
                    f.write(json.dumps(entry, default=str) + "\n")
            except Exception:
                logger.exception("failed to persist audit entry")
        logger.info("audit: %s %s", event, {k: v for k, v in fields.items() if k != "args"})
        return entry

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)
