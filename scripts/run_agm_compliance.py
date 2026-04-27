"""Run the 49-scenario AGM compliance suite and write reproducibility artifacts.

Produces:
  - benchmarks/agm_compliance/runs/baseline.json — machine-readable result rows
  - docs/AGM_COMPLIANCE.md — human-readable reproducibility doc

Run:
    PYTHONPATH=. python scripts/run_agm_compliance.py

Requires Neo4j running at $NEO4J_URI (default bolt://localhost:7687).

Spec: 06 - Ripple Algorithm Spec § 5 (AGM postulates).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Repo-relative path for direct invocation
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


_OUT_JSON = ROOT / "benchmarks" / "agm_compliance" / "runs" / "baseline.json"
_OUT_MD = ROOT / "docs" / "AGM_COMPLIANCE.md"


async def _run() -> int:
    from neo4j import AsyncGraphDatabase

    from benchmarks.agm_compliance import run_suite
    from benchmarks.agm_compliance.scenarios import ALL_SCENARIOS

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "atlasdev")

    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    try:
        await driver.verify_connectivity()
    except Exception as exc:
        print(
            f"\n  Atlas needs Neo4j running at {uri}.\n"
            f"  {type(exc).__name__}: {exc}\n\n"
            f"  Start it with: docker compose up -d neo4j\n",
            file=sys.stderr,
        )
        return 2

    started = datetime.now(timezone.utc)
    try:
        report = await run_suite(driver, ALL_SCENARIOS, stop_on_failure=False)
    finally:
        await driver.close()
    finished = datetime.now(timezone.utc)

    # ── machine-readable JSON ───────────────────────────────────────────────
    by_cat = {c.value: {"passed": p, "total": t}
              for c, (p, t) in report.by_category().items()}
    by_post = {p.value: {"passed": pp, "total": tt}
               for p, (pp, tt) in report.by_postulate().items()}

    matrix = {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "neo4j_uri": uri,
        "scenarios_total": report.total,
        "scenarios_passed": report.passed,
        "scenarios_failed": report.failed,
        "pass_rate": report.pass_rate,
        "by_category": by_cat,
        "by_postulate": by_post,
        "results": [
            {
                "scenario_id": r.scenario_id,
                "category": r.category.value,
                "postulate": r.postulate.value,
                "passed": r.passed,
                "detail": r.detail,
                "error": r.error,
            }
            for r in report.results
        ],
    }
    _OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _OUT_JSON.write_text(json.dumps(matrix, indent=2))
    print(f"JSON  -> {_OUT_JSON.relative_to(ROOT)}")

    # ── human-readable Markdown ────────────────────────────────────────────
    md = _render_markdown(report, started, finished, uri)
    _OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    _OUT_MD.write_text(md)
    print(f"Doc   -> {_OUT_MD.relative_to(ROOT)}")

    print()
    print(report.summary())

    return 0 if report.failed == 0 else 1


def _render_markdown(report, started, finished, uri: str) -> str:
    """Render the Markdown reproducibility doc.

    Layout: header → reproduction command → headline scoreboard → category
    table → postulate table → failure detail (if any) → pointer to JSON.
    """
    lines: list[str] = []
    lines.append("# AGM Compliance Suite — Reproducibility Artifact")
    lines.append("")
    lines.append(
        "This is the checked-in result of running Atlas's 49-scenario AGM "
        "compliance suite, the same shape as Kumiho Table 18 (5 categories × "
        "all-applicable postulates). Atlas's headline correctness claim is "
        "100% pass rate across all 49 scenarios. This file is the "
        "auditable artifact behind that claim."
    )
    lines.append("")
    lines.append("## How this file was generated")
    lines.append("")
    lines.append("```bash")
    lines.append("docker compose up -d neo4j")
    lines.append("PYTHONPATH=. python scripts/run_agm_compliance.py")
    lines.append("```")
    lines.append("")
    lines.append(
        f"Run timestamp (UTC): `{started.isoformat()}` → `{finished.isoformat()}`"
    )
    lines.append(f"Neo4j endpoint: `{uri}`")
    lines.append("")
    lines.append("## Headline result")
    lines.append("")
    lines.append(
        f"**{report.passed} / {report.total} scenarios passed "
        f"({100 * report.pass_rate:.1f}%).**"
    )
    if report.failed == 0:
        lines.append("")
        lines.append(
            "All seven AGM postulates are upheld across all five operational "
            "categories. This matches Kumiho's Table 18 result and is the "
            "formal correctness baseline Atlas's Ripple engine extends from."
        )
    lines.append("")

    lines.append("## By category")
    lines.append("")
    lines.append("| Category | Passed | Total |")
    lines.append("|---|---|---|")
    for cat, (p, t) in sorted(report.by_category().items(), key=lambda x: x[0].value):
        lines.append(f"| `{cat.value}` | {p} | {t} |")
    lines.append("")

    lines.append("## By postulate")
    lines.append("")
    lines.append("| Postulate | Passed | Total |")
    lines.append("|---|---|---|")
    for post, (p, t) in sorted(report.by_postulate().items(), key=lambda x: x[0].value):
        lines.append(f"| `{post.value}` | {p} | {t} |")
    lines.append("")

    if report.failed > 0:
        lines.append("## Failures")
        lines.append("")
        for r in report.results:
            if not r.passed:
                lines.append(
                    f"- **`{r.scenario_id}`** "
                    f"[{r.category.value} / {r.postulate.value}] — "
                    f"{r.error or r.detail}"
                )
        lines.append("")
    else:
        lines.append("## Failures")
        lines.append("")
        lines.append("_None._")
        lines.append("")

    lines.append("## Machine-readable output")
    lines.append("")
    lines.append(
        "Per-scenario rows (including detail strings and error messages) are "
        "in `benchmarks/agm_compliance/runs/baseline.json`. Tools that want "
        "to diff runs across commits should read that file, not this one — "
        "Markdown is for humans, JSON is for machines."
    )
    lines.append("")
    lines.append("## Why this matters")
    lines.append("")
    lines.append(
        "Kumiho's central contribution (arxiv 2603.17244) was proving AGM "
        "K*2–K*6 + Hansson Relevance/Core-Retainment can be discharged on a "
        "property graph. They reported 100% across 49 scenarios in their "
        "published table. Atlas re-implements those operators as open-source "
        "local-first infrastructure and runs the same shape suite, so a "
        "reader can verify Atlas hasn't quietly weakened the formal "
        "guarantees that make AGM compliance load-bearing for the rest of "
        "the system. Ripple's downstream re-evaluation (Atlas's headline "
        "extension) sits on top of these operators — if any postulate "
        "weakened, every Ripple-derived confidence would be unsound."
    )
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
