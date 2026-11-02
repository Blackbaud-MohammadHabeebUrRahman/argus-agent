"""Render a sweep as a human-readable report.

Two outputs: a Markdown table for ``make evals`` stdout, and a static
HTML page checked into the repo as ``evals/report.html``. The HTML is
intentionally one file with inline CSS and no JS runtime — it opens
cleanly from a file:// URL and from GitHub's raw-page preview.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .runner import EvalResult, SweepResult


def render_markdown_summary(sweep: SweepResult) -> str:
    passes = sweep.passes_per_model()
    totals = sweep.totals_per_model()
    rows = [
        "| Model | Pass rate | Avg tool calls | Avg cost | Avg duration |",
        "|---|---|---|---|---|",
    ]
    for model in sorted(passes):
        p, t = passes[model]
        agg = totals[model]
        runs = max(agg["runs"], 1)
        rows.append(
            f"| `{model}` | {p}/{t} ({_pct(p, t)}%) | "
            f"{agg['tool_calls'] / runs:.1f} | "
            f"${agg['cost_usd'] / runs:.4f} | "
            f"{agg['duration_s'] / runs:.1f}s |"
        )
    header = (
        f"# Argus eval sweep\n\n"
        f"- Started: {sweep.started_at.isoformat()}\n"
        f"- Ended: {sweep.ended_at.isoformat() if sweep.ended_at else '(in progress)'}\n"
        f"- Scenarios: {len({r.scenario_name for r in sweep.results})}\n"
        f"- Runs: {len(sweep.results)}\n\n"
    )
    detail_rows = [
        "",
        "## Per-scenario detail",
        "",
        "| Scenario | Model | Pass | Verdict | Tools | Cost |",
        "|---|---|---|---|---|---|",
    ]
    for r in sweep.results:
        detail_rows.append(
            f"| {r.scenario_name} | `{r.agent_model}` | "
            f"{'✓' if r.passed else '✗'} | {r.judge.verdict} | "
            f"{r.trajectory.tool_call_count} | "
            f"${r.trajectory.estimated_cost_usd:.4f} |"
        )
    return header + "\n".join(rows) + "\n" + "\n".join(detail_rows) + "\n"


def _pct(numer: int, denom: int) -> int:
    return int(round(100 * numer / denom)) if denom else 0


_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Argus eval report</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
         margin: 2rem; max-width: 1100px; line-height: 1.5; }}
  h1, h2 {{ margin-top: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ccc; padding: 0.5rem 0.75rem; text-align: left;
           vertical-align: top; }}
  th {{ background: #f3f4f6; }}
  .pass {{ color: #047857; font-weight: 600; }}
  .fail {{ color: #b91c1c; font-weight: 600; }}
  .model {{ font-family: ui-monospace, monospace; font-size: 0.9em; }}
  details {{ margin: 0.5rem 0; }}
  details > summary {{ cursor: pointer; font-weight: 600; }}
  pre.markdown {{ white-space: pre-wrap; background: #f9fafb;
                 padding: 0.75rem; border-radius: 4px; font-size: 0.85em; }}
  .meta {{ color: #6b7280; font-size: 0.9em; }}
  @media (prefers-color-scheme: dark) {{
    th {{ background: #1f2937; }}
    pre.markdown {{ background: #111827; }}
    .meta {{ color: #9ca3af; }}
  }}
</style>
</head>
<body>
<h1>Argus eval report</h1>
<p class="meta">Started {started} — ended {ended} — {total} runs across {n_scenarios} scenarios.</p>

<h2>Summary</h2>
<table>
<thead>
<tr><th>Model</th><th>Pass rate</th><th>Avg tool calls</th><th>Avg cost</th><th>Avg duration</th></tr>
</thead>
<tbody>
{summary_rows}
</tbody>
</table>

<h2>Per-scenario detail</h2>
{detail_blocks}
</body>
</html>"""


def _render_summary_row(model: str, passed: int, total: int, agg: dict[str, float]) -> str:
    runs = max(agg["runs"], 1)
    return (
        f"<tr><td class=model>{html.escape(model)}</td>"
        f"<td>{passed}/{total} ({_pct(passed, total)}%)</td>"
        f"<td>{agg['tool_calls'] / runs:.1f}</td>"
        f"<td>${agg['cost_usd'] / runs:.4f}</td>"
        f"<td>{agg['duration_s'] / runs:.1f}s</td></tr>"
    )


def _render_detail_block(result: EvalResult) -> str:
    status_cls = "pass" if result.passed else "fail"
    status_label = "PASS" if result.passed else "FAIL"
    det = result.deterministic
    deterministic_json = html.escape(json.dumps(det.model_dump(), indent=2, default=str))
    report_md = html.escape(result.report_markdown or "(empty)")
    judge_reason = html.escape(result.judge.reasoning or "")
    return f"""
<details>
<summary><span class="{status_cls}">{status_label}</span>
  — {html.escape(result.scenario_name)} on
  <span class="model">{html.escape(result.agent_model)}</span>
  — judge: {html.escape(result.judge.verdict)}
  — {result.trajectory.tool_call_count} tool calls,
  ${result.trajectory.estimated_cost_usd:.4f}</summary>
<p><strong>Judge reasoning:</strong> {judge_reason}</p>
<p><strong>Deterministic checks:</strong></p>
<pre class="markdown">{deterministic_json}</pre>
<p><strong>Agent report:</strong></p>
<pre class="markdown">{report_md}</pre>
</details>
"""


def render_html(sweep: SweepResult) -> str:
    passes = sweep.passes_per_model()
    totals = sweep.totals_per_model()
    summary_rows = "\n".join(
        _render_summary_row(m, passes[m][0], passes[m][1], totals[m]) for m in sorted(passes)
    )
    detail_blocks = "\n".join(_render_detail_block(r) for r in sweep.results)
    return _HTML_TEMPLATE.format(
        started=html.escape(sweep.started_at.isoformat()),
        ended=html.escape(sweep.ended_at.isoformat() if sweep.ended_at else "n/a"),
        total=len(sweep.results),
        n_scenarios=len({r.scenario_name for r in sweep.results}),
        summary_rows=summary_rows,
        detail_blocks=detail_blocks,
    )


def write_report(sweep: SweepResult, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "report.html"
    md_path = out_dir / "report.md"
    json_path = out_dir / "sweep.json"
    html_path.write_text(render_html(sweep))
    md_path.write_text(render_markdown_summary(sweep))
    json_path.write_text(sweep.model_dump_json(indent=2))
    return {"html": html_path, "md": md_path, "json": json_path}
