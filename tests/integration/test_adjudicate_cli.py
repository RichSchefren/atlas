"""Integration tests for scripts/adjudicate.py.

Exercises the three modes (auto-promote, queue, auto-deny) against a
fresh QuarantineStore + HashChainedLedger seeded with synthetic
candidates. Confirms:

  - High-confidence vault candidates are promoted to ledger atomically.
  - Medium-confidence candidates get rendered as Markdown queue entries
    with valid frontmatter.
  - Low-confidence candidates get terminal-denied.
  - --report and --dry-run never mutate state.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from atlas_core.trust.ledger import HashChainedLedger
from atlas_core.trust.promotion_policy import PromotionPolicy
from atlas_core.trust.quarantine import QuarantineStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "adjudicate.py"


def _load_adjudicate():
    """Import scripts/adjudicate.py as a module.

    Register in sys.modules before exec'ing so @dataclass can resolve the
    module name (Python 3.14's dataclasses.py needs sys.modules[cls.__module__]
    to look up annotations).
    """
    import sys
    spec = importlib.util.spec_from_file_location("adjudicate_cli", _SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_candidate(
    quarantine: QuarantineStore,
    *,
    candidate_id: str,
    lane: str,
    confidence: float,
    subject: str = "kref://Atlas/Test/widget",
    predicate: str = "color",
    value: str = "blue",
) -> None:
    """Insert one requires_approval candidate directly via SQL.

    Bypasses the upsert pipeline — we want exact control over confidence
    + lane + status to drive each branch of the CLI.
    """
    payload = {
        "candidate_id": candidate_id,
        "fingerprint": f"fp_{candidate_id}",
        "status": "requires_approval",
        "risk_level": "low",
        "policy_version": "v1",
        "trust_score": 0.6,
        "lane": lane,
        "assertion_type": "factual_assertion",
        "subject_kref": subject,
        "predicate": predicate,
        "object_value": value,
        "scope": "global",
        "evidence_refs_json": json.dumps(
            [{"source": "test", "source_family": "test", "kref": subject,
              "timestamp": "2026-04-29T00:00:00Z"}]
        ),
        "evidence_stats_json": json.dumps({"n_sources": 1}),
        "confidence": confidence,
        "policy_trace_json": json.dumps({"recommendation": "requires_approval"}),
    }
    cols = ", ".join(payload.keys())
    placeholders = ", ".join("?" * len(payload))
    now = "2026-04-29T00:00:00Z"
    with quarantine._connect() as conn:
        conn.execute(
            f"INSERT INTO candidates ({cols}, created_at, updated_at) "
            f"VALUES ({placeholders}, ?, ?)",
            (*payload.values(), now, now),
        )


@pytest.fixture()
def stores(tmp_path):
    candidates_db = tmp_path / "candidates.db"
    ledger_db = tmp_path / "ledger.db"
    quarantine = QuarantineStore(db_path=candidates_db)
    ledger = HashChainedLedger(db_path=ledger_db)
    policy = PromotionPolicy(quarantine=quarantine, ledger=ledger)
    return {
        "quarantine": quarantine,
        "ledger": ledger,
        "policy": policy,
        "data_dir": tmp_path,
    }


def test_auto_promote_high_confidence_vault(stores):
    """0.85 confidence on atlas_vault → goes to ledger."""
    adj = _load_adjudicate()
    _seed_candidate(stores["quarantine"], candidate_id="HIGH1",
                    lane="atlas_vault", confidence=0.85)
    _seed_candidate(stores["quarantine"], candidate_id="HIGH2",
                    lane="atlas_vault", confidence=0.95)

    counts = adj.auto_promote(
        quarantine=stores["quarantine"], policy=stores["policy"],
        lanes=("atlas_vault",), floor=0.80, dry_run=False,
    )
    assert counts.promoted == 2
    assert counts.promoted_failed == 0


def test_auto_promote_skips_wrong_lane(stores):
    """0.85 on atlas_chat_history is NOT promoted (lane filter)."""
    adj = _load_adjudicate()
    _seed_candidate(stores["quarantine"], candidate_id="WRONG",
                    lane="atlas_chat_history", confidence=0.85)

    counts = adj.auto_promote(
        quarantine=stores["quarantine"], policy=stores["policy"],
        lanes=("atlas_vault",), floor=0.80, dry_run=False,
    )
    assert counts.promoted == 0


def test_auto_promote_skips_below_floor(stores):
    """0.79 on atlas_vault is NOT promoted even on a trusted lane."""
    adj = _load_adjudicate()
    _seed_candidate(stores["quarantine"], candidate_id="LOW",
                    lane="atlas_vault", confidence=0.79)

    counts = adj.auto_promote(
        quarantine=stores["quarantine"], policy=stores["policy"],
        lanes=("atlas_vault",), floor=0.80, dry_run=False,
    )
    assert counts.promoted == 0


def test_auto_promote_dry_run_mutates_nothing(stores):
    adj = _load_adjudicate()
    _seed_candidate(stores["quarantine"], candidate_id="DRY",
                    lane="atlas_vault", confidence=0.95)

    counts = adj.auto_promote(
        quarantine=stores["quarantine"], policy=stores["policy"],
        lanes=("atlas_vault",), floor=0.80, dry_run=True,
    )
    assert counts.promoted == 1
    # Status must still be requires_approval after dry-run
    candidate = stores["quarantine"].get_candidate("DRY")
    assert candidate is not None
    assert candidate["status"] == "requires_approval"


def test_queue_writes_markdown_file(stores, tmp_path):
    adj = _load_adjudicate()
    _seed_candidate(
        stores["quarantine"], candidate_id="MED",
        lane="atlas_observational", confidence=0.65,
    )
    queue_dir = tmp_path / "queue"

    counts = adj.queue_for_review(
        quarantine=stores["quarantine"], queue_dir=queue_dir,
        floor=0.80, noise_floor=0.50, dry_run=False,
    )
    assert counts.queued == 1
    files = list(queue_dir.rglob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    # Frontmatter must have the decision-pending field for user to edit
    assert "decision: \"pending\"" in text
    assert "atlas_candidate_id: \"MED\"" in text
    assert "## Decision" in text


def test_queue_skips_above_floor_and_below_noise(stores, tmp_path):
    """Only candidates strictly between noise_floor and floor get queued."""
    adj = _load_adjudicate()
    _seed_candidate(stores["quarantine"], candidate_id="HI",
                    lane="atlas_observational", confidence=0.85)
    _seed_candidate(stores["quarantine"], candidate_id="LO",
                    lane="atlas_observational", confidence=0.30)
    _seed_candidate(stores["quarantine"], candidate_id="MID",
                    lane="atlas_observational", confidence=0.65)
    queue_dir = tmp_path / "queue"

    counts = adj.queue_for_review(
        quarantine=stores["quarantine"], queue_dir=queue_dir,
        floor=0.80, noise_floor=0.50, dry_run=False,
    )
    assert counts.queued == 1
    files = list(queue_dir.rglob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "atlas_candidate_id: \"MID\"" in text


def test_queue_idempotent_on_rerun(stores, tmp_path):
    adj = _load_adjudicate()
    _seed_candidate(stores["quarantine"], candidate_id="REPEAT",
                    lane="atlas_observational", confidence=0.65)
    queue_dir = tmp_path / "queue"

    first = adj.queue_for_review(
        quarantine=stores["quarantine"], queue_dir=queue_dir,
        floor=0.80, noise_floor=0.50, dry_run=False,
    )
    second = adj.queue_for_review(
        quarantine=stores["quarantine"], queue_dir=queue_dir,
        floor=0.80, noise_floor=0.50, dry_run=False,
    )
    assert first.queued == 1
    assert second.queued == 0
    assert second.skipped == 1


def test_auto_deny_only_below_noise_floor(stores):
    adj = _load_adjudicate()
    _seed_candidate(stores["quarantine"], candidate_id="NOISE",
                    lane="atlas_observational", confidence=0.30)
    _seed_candidate(stores["quarantine"], candidate_id="MID",
                    lane="atlas_observational", confidence=0.65)

    counts = adj.auto_deny(
        quarantine=stores["quarantine"], noise_floor=0.50, dry_run=False,
    )
    assert counts.denied == 1
    noise = stores["quarantine"].get_candidate("NOISE")
    mid = stores["quarantine"].get_candidate("MID")
    assert noise is not None and noise["status"] == "denied"
    assert mid is not None and mid["status"] == "requires_approval"


def test_bucket_report_shape(stores):
    adj = _load_adjudicate()
    _seed_candidate(stores["quarantine"], candidate_id="A",
                    lane="atlas_vault", confidence=0.90)
    _seed_candidate(stores["quarantine"], candidate_id="B",
                    lane="atlas_observational", confidence=0.65)
    _seed_candidate(stores["quarantine"], candidate_id="C",
                    lane="atlas_observational", confidence=0.30)

    buckets = adj._bucket_report(stores["quarantine"])
    assert buckets["atlas_vault"][">=0.80"] == 1
    assert buckets["atlas_observational"]["0.50-0.79"] == 1
    assert buckets["atlas_observational"]["<0.50"] == 1
