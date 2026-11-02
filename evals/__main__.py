"""Run the eval sweep from the command line.

    python -m evals                                 # all fixtures, Opus 5.5
    python -m evals --models claude-opus-5-5,claude-sonnet-5-5,claude-haiku-5-5
    python -m evals --scenario stuck-jobs-vendor-outage
    python -m evals --threshold 0.75                # exit nonzero if pass_rate < 75%

Writes a report + JSON to evals/results/<timestamp>/ and symlinks
evals/results/latest/ to it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from argus.logging import configure_logging

from .harness.grader import DEFAULT_JUDGE_MODEL
from .harness.report import render_markdown_summary, write_report
from .harness.runner import run_sweep
from .harness.scenario import load_scenarios

DEFAULT_FIXTURES = Path(__file__).parent / "fixtures"
DEFAULT_OUT = Path(__file__).parent / "results"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the Argus eval sweep.")
    p.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_FIXTURES,
        help="Directory of scenario YAML files.",
    )
    p.add_argument(
        "--models",
        default="claude-opus-5-5",
        help="Comma-separated list of agent models to sweep.",
    )
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Scenario name to run (repeatable). Default: every fixture.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Base output directory. A timestamped subdir is created inside it.",
    )
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Exit nonzero if overall pass rate falls below this (0.0-1.0).",
    )
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    configure_logging(level=args.log_level, json_output=False)
    log = logging.getLogger("argus.evals")

    scenarios = load_scenarios(args.fixtures)
    if args.scenario:
        wanted = set(args.scenario)
        scenarios = [s for s in scenarios if s.name in wanted]
    if not scenarios:
        log.error("no scenarios to run")
        return 2

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    log.info(
        "running %d scenarios x %d models = %d runs",
        len(scenarios),
        len(models),
        len(scenarios) * len(models),
    )
    log.info("each run spends real tokens; see evals/results/<ts>/report.html for output")

    sweep = await run_sweep(
        scenarios,
        agent_models=models,
        judge_model=args.judge_model,
        max_steps=args.max_steps,
        concurrency=args.concurrency,
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.out / ts
    paths = write_report(sweep, run_dir)
    log.info("report: %s", paths["html"])
    _update_latest_symlink(args.out, ts)

    print()
    print(render_markdown_summary(sweep))

    passed = sum(1 for r in sweep.results if r.passed)
    total = len(sweep.results)
    rate = passed / total if total else 0.0
    log.info("pass rate: %d/%d = %.1f%%", passed, total, rate * 100)
    if rate < args.threshold:
        log.error("pass rate %.2f below threshold %.2f", rate, args.threshold)
        return 1
    return 0


def _update_latest_symlink(base: Path, ts: str) -> None:
    latest = base / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        os.symlink(ts, latest)
    except OSError:
        # Windows / some filesystems may refuse symlinks; the timestamped dir
        # is still there, operators can navigate to it directly.
        pass


def main() -> None:
    sys.exit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
