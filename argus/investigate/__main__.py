"""CLI: run one investigation from the command line.

    python -m argus.investigate --incident-json path/to/incident.json
    python -m argus.investigate --incident-json path/to/incident.json \\
        --model claude-sonnet-5-5 --max-steps 10 \\
        --report-out /tmp/report.md --trajectory-out /tmp/trajectory.json

The ``--incident-json`` path contains a serialized ``Incident`` (as
produced by ``incident.model_dump_json()``). An operator looking up a
live incident goes through the incident store directly; this CLI is for
replays, demos, and development.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from argus.logging import configure_logging
from argus.models import Incident
from argus.plugins import build_hub

from .agent import DEFAULT_MAX_STEPS, DEFAULT_MODEL, InvestigationAgent

logger = logging.getLogger("argus.investigate.cli")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one Argus investigation.")
    p.add_argument(
        "--incident-json",
        type=Path,
        required=True,
        help="Path to a JSON file containing a serialized Incident.",
    )
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    p.add_argument(
        "--report-out",
        type=Path,
        help="Where to write the markdown report (default: stdout).",
    )
    p.add_argument(
        "--trajectory-out",
        type=Path,
        help="Where to write the trajectory JSON (default: alongside report).",
    )
    p.add_argument("--log-level", default="WARNING")
    return p.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    configure_logging(level=args.log_level, json_output=False)
    try:
        incident_data = json.loads(args.incident_json.read_text())
    except Exception as exc:
        logger.error("failed to read incident JSON: %s", exc)
        return 2
    incident = Incident.model_validate(incident_data)

    hub = build_hub()
    agent = InvestigationAgent(hub, model=args.model, max_steps=args.max_steps)
    report = await agent.investigate(incident)

    if args.report_out:
        args.report_out.write_text(report.markdown)
        logger.info("report written to %s", args.report_out)
    else:
        sys.stdout.write(report.markdown)
        sys.stdout.write("\n")

    traj_path = args.trajectory_out or (
        args.report_out.with_suffix(".trajectory.json") if args.report_out else None
    )
    if traj_path:
        traj_path.write_text(report.trajectory.model_dump_json(indent=2))
        logger.info("trajectory written to %s", traj_path)

    sys.stderr.write(report.to_summary() + "\n")
    return 0 if report.status in ("completed", "stopped_at_limit") else 1


def main() -> None:
    sys.exit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
