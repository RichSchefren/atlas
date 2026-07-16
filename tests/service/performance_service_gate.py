"""10k-item/20k-edge, 100-level performance gate for the service core."""

from __future__ import annotations

import argparse
import json
import math
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVICE_DIR = ROOT / "integrations" / "cognitive-service"
sys.path.insert(0, str(SERVICE_DIR))

from service_core import CognitiveServiceCore  # noqa: E402

NODES = 10_000
EDGES = 20_000
IMPACTED = 9_999
SCOPE = "service-performance"
ORIGIN = "kref://Perf/Facts/origin.fact"
NOW = "2026-07-16T20:00:00.000000Z"


def kref(index: int) -> str:
    return f"kref://Perf/Beliefs/node-{index:05d}.belief"


def seed(core: CognitiveServiceCore) -> float:
    started = time.perf_counter()
    with core._transaction():
        item_rows = [(SCOPE, ORIGIN, "fact", 900_000, NOW)]
        item_rows.extend((SCOPE, kref(i), "belief", 800_000, NOW) for i in range(1, NODES))
        core.db.executemany(
            """
            INSERT INTO items(scope_id,root_kref,kind,confidence_ppm,created_at)
            VALUES(?,?,?,?,?)
            """,
            item_rows,
        )
        ids = {
            row["root_kref"]: int(row["item_id"])
            for row in core.db.execute(
                "SELECT item_id,root_kref FROM items WHERE scope_id=?", (SCOPE,)
            )
        }
        origin_id = ids[ORIGIN]
        edge_rows = [
            (
                ids[kref(i)],
                origin_id if i <= 100 else ids[kref(i - 100)],
                1_000_000,
                NOW,
            )
            for i in range(1, NODES)
        ]
        edge_rows.append((origin_id, origin_id, 1_000_000, NOW))
        edge_rows.extend((ids[kref(i)], ids[kref(i)], 1_000_000, NOW) for i in range(1, NODES))
        edge_rows.append((ids[kref(NODES - 1)], origin_id, 1_000_000, NOW))
        assert len(edge_rows) == EDGES
        core.db.executemany(
            """
            INSERT INTO dependencies(
              dependent_item_id,support_item_id,strength_ppm,created_at
            ) VALUES(?,?,?,?)
            """,
            edge_rows,
        )
    return time.perf_counter() - started


def nearest_p95(values: list[float]) -> float:
    return sorted(values)[math.ceil(0.95 * len(values)) - 1]


def run(*, iterations: int, preflight: bool) -> dict[str, Any]:
    if preflight and iterations != 1:
        raise ValueError("preflight is exactly one sample")
    if not preflight and iterations < 20:
        raise ValueError("p95 gate requires at least 20 samples")
    with tempfile.TemporaryDirectory(prefix="atlas-service-perf-") as directory:
        core = CognitiveServiceCore(Path(directory) / "service.sqlite3", scope_id=SCOPE)
        try:
            seed_seconds = seed(core)
            durations = []
            for index in range(iterations):
                started = time.perf_counter()
                result = core.run_cascade(
                    idempotency_key=f"service-perf-{index:03d}",
                    origin_kref=ORIGIN,
                    old_confidence_ppm=900_000,
                    new_confidence_ppm=300_000,
                    max_depth=100,
                    max_nodes=NODES,
                    created_at=NOW,
                )
                durations.append(time.perf_counter() - started)
                if len(result["proposals"]) != IMPACTED:
                    raise AssertionError("service did not return all 9999 proposals")
                persisted = core.db.execute(
                    "SELECT count(*) FROM proposals WHERE cascade_id=?",
                    (result["cascade_id"],),
                ).fetchone()[0]
                if persisted != IMPACTED:
                    raise AssertionError("service did not persist all 9999 proposals")
                with core._transaction():
                    core.db.execute(
                        "DELETE FROM operations WHERE scope_id=? AND idempotency_key=?",
                        (SCOPE, f"service-perf-{index:03d}"),
                    )
                    core.db.execute("DELETE FROM cascades WHERE cascade_id=?", (result["cascade_id"],))
            measured = durations[0] if preflight else nearest_p95(durations)
            output = {
                "gate": "service-preflight" if preflight else "service-p95",
                "passed": measured < 2.0,
                "method": "single sample; not p95" if preflight else "nearest-rank p95",
                "threshold_seconds_exclusive": 2.0,
                "iterations": iterations,
                "durations_seconds": [round(value, 6) for value in durations],
                "mean_seconds": round(statistics.fmean(durations), 6),
                "max_seconds": round(max(durations), 6),
                "seed_seconds": round(seed_seconds, 6),
                "topology": {
                    "items": NODES,
                    "depends_on_edges": EDGES,
                    "proposals": IMPACTED,
                    "max_depth": 100,
                    "layer_width": 100,
                    "includes_convergent_path": True,
                    "includes_self_cycles": True,
                },
                "environment": {
                    "platform": platform.platform(), "python": platform.python_version(),
                    "sqlite": sqlite3.sqlite_version,
                },
            }
            output["preflight_seconds" if preflight else "p95_seconds"] = round(measured, 6)
            return output
        finally:
            core.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(iterations=1 if args.preflight else args.iterations, preflight=args.preflight)
    rendered = json.dumps(result, sort_keys=True, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
