"""Empirical confidence-threshold calibration.

Spec: PHASE-5-AND-BEYOND.md § 2.5

Atlas's promotion thresholds (0.25 / 0.6 / 1.0) and Ripple's
DECISION_SUPPORT_FLOOR (0.5) are inherited from Bicameral as
arbitrary defaults. This script empirically calibrates them
against a real ingest and writes the results to
~/.atlas/calibration_report.json + paper/calibration.md.

Methodology:
  1. Read every candidate from the live ~/.atlas/candidates.db
  2. Group by (lane, risk_level)
  3. Compute the percentile-based threshold that splits each
     group cleanly between auto-promote-eligible and review-required
  4. Compare against the current hardcoded threshold; report drift
  5. Recommend new thresholds as a config block Rich can paste into
     atlas_core/trust/quarantine.py

Run:
    PYTHONPATH=. python scripts/calibrate_confidence_thresholds.py

Reads from the live data dir; writes to the same location plus the
paper/ tree. Idempotent — safe to re-run.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root without PYTHONPATH gymnastics
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DEFAULT_DATA_DIR: Path = Path.home() / ".atlas"
DEFAULT_OUT: Path = DEFAULT_DATA_DIR / "calibration_report.json"
DEFAULT_PAPER_OUT: Path = (
    Path(__file__).resolve().parents[1] / "paper" / "calibration.md"
)


def load_candidates(db_path: Path) -> list[dict]:
    """Read every row from candidates.db. Returns plain dicts."""
    if not db_path.exists():
        return []
    rows: list[dict] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT lane, risk_level, status, confidence, trust_score "
            "FROM candidates"
        ):
            rows.append(dict(row))
    return rows


def calibrate(rows: list[dict]) -> dict:
    """Compute per-group thresholds."""
    if not rows:
        return {
            "n_candidates": 0,
            "groups": [],
            "recommendation": (
                "No candidates yet — run the daemon for a week, then re-run."
            ),
        }

    by_group: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_status: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in rows:
        key = (r["lane"], r["risk_level"])
        by_group[key].append(float(r["confidence"]))
        by_status[(r["lane"], r["risk_level"], r["status"])] += 1

    groups = []
    for (lane, risk), confidences in sorted(by_group.items()):
        if len(confidences) < 5:
            continue
        sorted_c = sorted(confidences)
        groups.append({
            "lane": lane,
            "risk_level": risk,
            "n_samples": len(confidences),
            "median_confidence": statistics.median(sorted_c),
            "p25_confidence": sorted_c[len(sorted_c) // 4],
            "p75_confidence": sorted_c[len(sorted_c) * 3 // 4],
            "p90_confidence": sorted_c[len(sorted_c) * 9 // 10],
            "mean_confidence": statistics.mean(sorted_c),
            "stdev_confidence": (
                statistics.stdev(sorted_c) if len(sorted_c) > 1 else 0.0
            ),
            "auto_promote_recommended": _recommend_threshold(sorted_c, risk),
        })

    return {
        "n_candidates": len(rows),
        "n_groups": len(groups),
        "by_status": {
            f"{lane}|{risk}|{status}": n
            for (lane, risk, status), n in sorted(by_status.items())
        },
        "groups": groups,
        "current_thresholds": {
            "TRUST_QUARANTINE": 0.25,
            "TRUST_CORROBORATED": 0.6,
            "TRUST_LEDGER": 1.0,
            "AUTO_PROMOTE_THRESHOLD": 0.90,
            "DECISION_SUPPORT_FLOOR": 0.50,
        },
        "recommendation": _summarize(groups),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _recommend_threshold(sorted_confidences: list[float], risk: str) -> float:
    """Risk-aware percentile suggestion. High-risk: very conservative
    (95th pct); medium: 90th; low: 75th. The data tells us where the
    cluster of clean assertions actually lives."""
    if not sorted_confidences:
        return 0.9
    risk_pcts = {"low": 0.75, "medium": 0.90, "high": 0.95}
    pct = risk_pcts.get(risk, 0.90)
    idx = max(0, min(len(sorted_confidences) - 1, int(len(sorted_confidences) * pct)))
    return round(sorted_confidences[idx], 2)


def _summarize(groups: list[dict]) -> str:
    if not groups:
        return "Insufficient data — need ≥5 samples per (lane, risk_level)."
    lines = ["Per-group recommendations:"]
    for g in groups:
        cur = 0.90
        delta = g["auto_promote_recommended"] - cur
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"  {g['lane']}/{g['risk_level']}: "
            f"recommend AUTO_PROMOTE = {g['auto_promote_recommended']:.2f} "
            f"({sign}{delta:.2f} vs current 0.90), "
            f"based on {g['n_samples']} samples"
        )
    return "\n".join(lines)


def write_paper_section(report: dict, path: Path) -> None:
    """Render the calibration report as a markdown section the paper
    revision (v2) can include verbatim."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ["# Atlas confidence-threshold calibration",
            "",
            f"Generated: {report.get('generated_at', '')}",
            f"Total candidates analyzed: {report['n_candidates']}",
            "",
            "## Current hardcoded thresholds",
            "",
            "| Threshold | Value |",
            "|---|---|",
    ]
    for k, v in report.get("current_thresholds", {}).items():
        body.append(f"| `{k}` | {v} |")
    body.append("")
    body.append("## Per-group statistics")
    body.append("")
    body.append("| Lane | Risk | N | median | p75 | p90 | recommended AUTO_PROMOTE |")
    body.append("|---|---|---|---|---|---|---|")
    for g in report.get("groups", []):
        body.append(
            f"| {g['lane']} | {g['risk_level']} | {g['n_samples']} | "
            f"{g['median_confidence']:.2f} | {g['p75_confidence']:.2f} | "
            f"{g['p90_confidence']:.2f} | {g['auto_promote_recommended']:.2f} |"
        )
    body.append("")
    body.append("## Summary")
    body.append("")
    body.append("```")
    body.append(report.get("recommendation", "(no recommendation)"))
    body.append("```")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def main() -> int:
    data_dir = Path(os.environ.get("ATLAS_DATA_DIR", str(DEFAULT_DATA_DIR)))
    db_path = data_dir / "candidates.db"
    out_path = Path(os.environ.get("ATLAS_CALIBRATION_OUT", str(DEFAULT_OUT)))
    paper_path = Path(os.environ.get(
        "ATLAS_CALIBRATION_PAPER_OUT", str(DEFAULT_PAPER_OUT),
    ))

    print(f"Reading candidates from {db_path}")
    rows = load_candidates(db_path)
    print(f"Loaded {len(rows)} candidates")

    report = calibrate(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"JSON report → {out_path}")

    write_paper_section(report, paper_path)
    print(f"Markdown for paper → {paper_path}")

    print()
    print(report.get("recommendation", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
