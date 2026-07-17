"""End-to-end tests for the `atlas` CLI against the REAL shipped surfaces.

Unlike tests/unit/test_cli.py (which mocks the delegated functions to isolate
parsing/dispatch), these drive the CLI against real QuarantineStore and
HealthLogger instances backed by real files, plus a real subprocess for the
demo wrapper. They prove the thin dispatch layer actually reaches the shipped
functions. No Neo4j and no vault-search daemon are required.
"""

from __future__ import annotations

import json
import stat

from atlas_core import cli
from atlas_core.daemon.health import HealthLogger, HealthRow
from atlas_core.trust.quarantine import QuarantineStore


def _seed_pending(quarantine: QuarantineStore, *, candidate_id: str, lane: str) -> None:
    """Insert one PENDING candidate directly (matches list_pending's status filter)."""
    payload = {
        "candidate_id": candidate_id,
        "fingerprint": f"fp_{candidate_id}",
        "status": "pending",
        "risk_level": "low",
        "policy_version": "v1",
        "trust_score": 0.6,
        "lane": lane,
        "assertion_type": "factual_assertion",
        "subject_kref": "kref://Atlas/Test/widget",
        "predicate": "color",
        "object_value": "blue",
        "scope": "global",
        "evidence_refs_json": json.dumps([{"source": "test", "source_family": "test"}]),
        "evidence_stats_json": json.dumps({"n_sources": 1}),
        "confidence": 0.62,
        "policy_trace_json": json.dumps({"recommendation": "review"}),
    }
    cols = ", ".join(payload.keys())
    placeholders = ", ".join("?" * len(payload))
    now = "2026-07-16T00:00:00Z"
    with quarantine._connection() as conn:
        conn.execute(
            f"INSERT INTO candidates ({cols}, created_at, updated_at) "
            f"VALUES ({placeholders}, ?, ?)",
            (*payload.values(), now, now),
        )


def test_queue_lists_real_pending_candidates(monkeypatch, tmp_path, capsys):
    db = tmp_path / "candidates.db"
    store = QuarantineStore(db_path=db)
    _seed_pending(store, candidate_id="alpha", lane="atlas_vault")
    _seed_pending(store, candidate_id="beta", lane="atlas_meeting")

    monkeypatch.setenv("ATLAS_QUARANTINE_DB", str(db))

    rc = cli.main(["queue", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    ids = {r["candidate_id"] for r in payload}
    assert ids == {"alpha", "beta"}

    # Lane filter flows through to the real query.
    rc = cli.main(["queue", "--lane", "atlas_vault", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [r["candidate_id"] for r in payload] == ["alpha"]


def test_status_reads_real_health_row(monkeypatch, tmp_path, capsys):
    # HealthLogger defaults to ~/.atlas/health; point HOME at a temp dir so the
    # CLI's own HealthLogger("com.atlas.ingestion") resolves to our seeded file.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    logger = HealthLogger("com.atlas.ingestion")
    logger.append(HealthRow(
        daemon="com.atlas.ingestion",
        started_at="2026-07-16T00:00:00Z",
        finished_at="2026-07-16T00:00:05Z",
        success=True,
        elapsed_sec=5.0,
        summary={"ingested": 4},
    ))

    rc = cli.main(["status", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["success"] is True
    assert payload["summary"] == {"ingested": 4}


def test_demo_runs_a_real_script(monkeypatch, tmp_path):
    script = tmp_path / "demo.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ATLAS_DEMO_SCRIPT", str(script))

    assert cli.main(["demo"]) == 0


def test_demo_propagates_real_nonzero_exit(monkeypatch, tmp_path):
    script = tmp_path / "demo.sh"
    script.write_text("#!/bin/sh\nexit 4\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ATLAS_DEMO_SCRIPT", str(script))

    assert cli.main(["demo"]) == 4
