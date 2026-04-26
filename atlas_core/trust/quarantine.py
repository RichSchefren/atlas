"""Quarantine store — Atlas's first-tier trust layer.

Ported from Bicameral truth/candidates.py with Atlas lane names. SQLite-backed
candidates queue with SHA-256 fingerprinting, ULID primary keys, evidence
merging, three-tier trust scoring (0.25 / 0.6 / 1.0), and a clean
upsert/promote/deny/auto-promote lifecycle.

Spec: 05 - Atlas Architecture & Schema § 6
      03 - Atlas Technical Foundation § 4.4
Bicameral provenance: truth/candidates.py (~95% direct port, lane-renamed)
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from ulid import ULID


log = logging.getLogger(__name__)


# ─── Trust tier constants (Bicameral semantics, Atlas lane naming) ───────────

TRUST_QUARANTINED: float = 0.25
"""Single-source observation. In semantic graph only, NOT in canonical ledger."""

TRUST_CORROBORATED: float = 0.60
"""≥2 independent source families confirm the same claim. Eligible for promotion."""

TRUST_LEDGER: float = 1.00
"""Promoted to hash-chained canonical ledger. Required for Ripple to fire."""


# ─── Lane matrix (renamed from Bicameral for Atlas) ──────────────────────────

LANE_RETRIEVAL_ELIGIBLE_GLOBAL: frozenset[str] = frozenset({
    "atlas_sessions",          # Claude Code session captures
    "atlas_observational",     # Limitless / Screenpipe / iMessage ambient
    "atlas_chat_history",      # ChatGPT / external assistant exports
    "atlas_curated",           # Hand-curated reference material
    "atlas_self_audit",        # Atlas's own learning logs
})

LANE_CORROBORATION_ONLY: frozenset[str] = frozenset({
    "atlas_imported_day1",     # Bootstrap-only, never auto-promotes
})

LANE_CANDIDATES_ELIGIBLE: frozenset[str] = (
    LANE_RETRIEVAL_ELIGIBLE_GLOBAL
    - {"atlas_curated", "atlas_self_audit"}
    | {"atlas_imported_day1"}
)
"""Lanes from which candidates can ENTER the queue (vs. retrieval-only ones)."""


# ─── Promotion thresholds (Bicameral defaults, Phase 3 calibration target) ───

RECOMMEND_THRESHOLD: float = 0.80
"""Below this confidence, do not even surface for review — deny silently."""

AUTO_PROMOTE_THRESHOLD: float = 0.90
"""Required confidence for auto-promotion of low-risk facts."""

CORROBORATION_BOOST_PER_SOURCE_FAMILY: float = 0.02
"""Each additional independent source family bumps trust score by this."""

CORROBORATION_CAPS: dict[str, float] = {
    "low": 0.06,
    "medium": 0.04,
    "high": 0.00,            # high-risk receives no corroboration boost
}
"""Per-risk-level cap on cumulative corroboration boost."""


# ─── Risk classification ─────────────────────────────────────────────────────

LOW_RISK_NAMESPACE_PREFIXES: tuple[str, ...] = ("pref.", "style.")
HIGH_RISK_NAMESPACE_PREFIXES: tuple[str, ...] = (
    "identity.", "relationship.", "legal.", "finance.", "security.", "health.",
)
SENSITIVE_CONTENT_CUES: tuple[str, ...] = (
    "ssn", "social security", "password", "private key",
    "medical", "diagnosis", "credit card",
)
ELIGIBLE_ASSERTION_TYPES: frozenset[str] = frozenset({
    "decision", "preference", "factual_assertion", "episode", "procedure",
})


# ─── Status enum ─────────────────────────────────────────────────────────────


class CandidateStatus(str, Enum):
    PENDING = "pending"
    REQUIRES_APPROVAL = "requires_approval"
    AUTO_PROMOTED = "auto_promoted"
    APPROVED = "approved"               # promoted into ledger
    DENIED = "denied"


# ─── Result + claim types ────────────────────────────────────────────────────


@dataclass
class EvidenceRef:
    """One evidence pointer for a candidate claim."""

    source: str                          # e.g., 'limitless', 'fireflies', 'session'
    source_family: str                   # 'capture' | 'meeting' | 'session' | 'vault'
    kref: str                            # kref:// URI of the source episode
    timestamp: str                       # ISO 8601 UTC

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "source_family": self.source_family,
            "kref": self.kref,
            "timestamp": self.timestamp,
        }


@dataclass
class CandidateClaim:
    """A claim arriving from an extractor, awaiting upsert into the queue."""

    lane: str
    assertion_type: str                 # one of ELIGIBLE_ASSERTION_TYPES
    subject_kref: str
    predicate: str                      # e.g., 'role', 'pricing_belief'
    object_value: str
    confidence: float                   # extractor's per-source confidence
    evidence_ref: EvidenceRef
    scope: str = "global"               # private | group_safe | global


@dataclass
class UpsertResult:
    """Outcome of an upsert_candidate call."""

    candidate_id: str
    is_new: bool                        # True = first time we've seen this fingerprint
    is_corroborated: bool               # True = ≥2 independent source families now
    is_auto_promoted: bool              # True = jumped straight to ledger
    trust_score: float
    status: CandidateStatus


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_ulid() -> str:
    """Time-sortable identifier with cryptographic random suffix."""
    return str(ULID())


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _candidate_fingerprint(claim: CandidateClaim) -> str:
    """Deterministic fingerprint over the canonical claim shape.

    Two claims with the same (subject, predicate, object, scope, lane) collapse
    to one candidate row — preventing duplicate explosions from streams.
    """
    canonical = _canonical_json([
        claim.lane,
        claim.subject_kref,
        claim.predicate,
        claim.object_value,
        claim.scope,
    ])
    return hashlib.sha256(canonical.encode()).hexdigest()


def _classify_risk(claim: CandidateClaim) -> str:
    """Return 'low' | 'medium' | 'high' based on namespace + content cues."""
    pred_lower = claim.predicate.lower()
    obj_lower = claim.object_value.lower()

    # Sensitive content cues escalate to high regardless of predicate
    for cue in SENSITIVE_CONTENT_CUES:
        if cue in pred_lower or cue in obj_lower:
            return "high"

    if any(claim.predicate.startswith(p) for p in HIGH_RISK_NAMESPACE_PREFIXES):
        return "high"
    if any(claim.predicate.startswith(p) for p in LOW_RISK_NAMESPACE_PREFIXES):
        return "low"
    return "medium"


def _merge_evidence_refs(
    existing_refs: list[dict[str, str]],
    new_ref: EvidenceRef,
) -> list[dict[str, str]]:
    """Add new ref if not already present (dedup by source+kref)."""
    seen = {(r["source"], r["kref"]) for r in existing_refs}
    new_dict = new_ref.to_dict()
    if (new_dict["source"], new_dict["kref"]) not in seen:
        existing_refs.append(new_dict)
    return existing_refs


def _compute_evidence_stats(refs: list[dict[str, str]]) -> dict[str, int]:
    """Compute corroboration metadata from evidence list."""
    families = {r["source_family"] for r in refs}
    return {
        "n_sources": len(refs),
        "independent_source_families": len(families),
    }


def _compute_trust_score(
    base_confidence: float,
    risk_level: str,
    evidence_stats: dict[str, int],
) -> float:
    """Apply corroboration boost capped per risk level."""
    independent_families = evidence_stats.get("independent_source_families", 1)
    boost = (independent_families - 1) * CORROBORATION_BOOST_PER_SOURCE_FAMILY
    cap = CORROBORATION_CAPS.get(risk_level, 0.04)
    boosted = min(boost, cap)
    score = base_confidence + boosted

    # Discretize to the three-tier model
    if score >= AUTO_PROMOTE_THRESHOLD:
        return TRUST_LEDGER if independent_families >= 2 or risk_level == "low" else TRUST_CORROBORATED
    if independent_families >= 2:
        return TRUST_CORROBORATED
    return TRUST_QUARANTINED


def _decide_auto_promote(
    claim: CandidateClaim,
    risk_level: str,
    confidence: float,
    evidence_stats: dict[str, int],
    *,
    auto_promote_enabled: bool = True,
) -> tuple[bool, str]:
    """Returns (eligible, reason)."""
    if not auto_promote_enabled:
        return False, "auto_promote_disabled"
    if claim.assertion_type not in ELIGIBLE_ASSERTION_TYPES:
        return False, f"ineligible_assertion_type:{claim.assertion_type}"
    if confidence < AUTO_PROMOTE_THRESHOLD:
        return False, f"confidence_below_threshold:{confidence:.2f}"

    independent_families = evidence_stats.get("independent_source_families", 0)

    if risk_level == "low":
        # Low-risk + pref/style namespace → auto-promote at ≥0.90
        if any(claim.predicate.startswith(p) for p in LOW_RISK_NAMESPACE_PREFIXES):
            return True, "low_risk_auto_promote"
        return False, "low_risk_outside_pref_namespace"

    if risk_level == "medium":
        if independent_families >= 2:
            return True, "medium_risk_corroborated"
        return False, "medium_risk_needs_corroboration"

    # high risk never auto-promotes
    return False, "high_risk_requires_human"


# ─── QuarantineStore ─────────────────────────────────────────────────────────


class QuarantineStore:
    """Atlas's first-tier trust layer — SQLite-backed candidates queue.

    Lifecycle: upsert (claim arrives) → corroborate (more sources confirm)
    → promote (cross threshold + policy gates) OR deny (review rejects).

    All operations are async; SQLite operations run in a thread executor to
    keep the event loop free.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        schema_path = Path(__file__).parent / "schemas" / "candidates.schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema_sql)

    # ── Public API ──────────────────────────────────────────────────────────

    def upsert_candidate(
        self,
        claim: CandidateClaim,
        *,
        auto_promote_enabled: bool = True,
    ) -> UpsertResult:
        """Insert or merge a candidate. Returns UpsertResult.

        Idempotent on (lane, subject, predicate, object, scope) fingerprint.
        Repeated calls with new evidence merge refs and recompute trust score.
        """
        if claim.lane not in LANE_CANDIDATES_ELIGIBLE:
            raise ValueError(
                f"Lane {claim.lane!r} not in candidate-eligible lanes "
                f"{sorted(LANE_CANDIDATES_ELIGIBLE)}"
            )

        fingerprint = _candidate_fingerprint(claim)
        risk_level = _classify_risk(claim)
        now = _utc_now()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM candidates WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()

            if existing is None:
                # New candidate
                evidence_refs = [claim.evidence_ref.to_dict()]
                evidence_stats = _compute_evidence_stats(evidence_refs)
                trust_score = _compute_trust_score(
                    claim.confidence, risk_level, evidence_stats
                )
                auto_promote, ap_reason = _decide_auto_promote(
                    claim, risk_level, claim.confidence, evidence_stats,
                    auto_promote_enabled=auto_promote_enabled,
                )
                status = (
                    CandidateStatus.AUTO_PROMOTED
                    if auto_promote
                    else (
                        CandidateStatus.REQUIRES_APPROVAL
                        if risk_level in ("high", "medium")
                        else CandidateStatus.PENDING
                    )
                )

                policy_trace = {
                    "recommendation": "auto_promote" if auto_promote else "review",
                    "auto_promote_reason": ap_reason,
                    "evaluated_at": now,
                    "policy_version": "v1",
                }

                cid = _new_ulid()
                conn.execute(
                    """
                    INSERT INTO candidates (
                        candidate_id, fingerprint, status, risk_level, policy_version,
                        trust_score, lane, assertion_type, subject_kref, predicate,
                        object_value, scope, evidence_refs_json, evidence_stats_json,
                        confidence, policy_trace_json,
                        created_at, updated_at,
                        promoted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid, fingerprint, status.value, risk_level, "v1",
                        trust_score, claim.lane, claim.assertion_type,
                        claim.subject_kref, claim.predicate, claim.object_value,
                        claim.scope,
                        _canonical_json(evidence_refs),
                        _canonical_json(evidence_stats),
                        claim.confidence,
                        _canonical_json(policy_trace),
                        now, now,
                        now if auto_promote else None,
                    ),
                )

                return UpsertResult(
                    candidate_id=cid,
                    is_new=True,
                    is_corroborated=evidence_stats["independent_source_families"] >= 2,
                    is_auto_promoted=auto_promote,
                    trust_score=trust_score,
                    status=status,
                )

            # Merge into existing
            existing_refs = json.loads(existing["evidence_refs_json"])
            evidence_refs = _merge_evidence_refs(existing_refs, claim.evidence_ref)
            evidence_stats = _compute_evidence_stats(evidence_refs)

            # Re-evaluate trust with new evidence
            new_trust = _compute_trust_score(
                claim.confidence, risk_level, evidence_stats
            )

            # Re-check auto-promote with new evidence
            auto_promote, ap_reason = _decide_auto_promote(
                claim, risk_level, claim.confidence, evidence_stats,
                auto_promote_enabled=auto_promote_enabled,
            )
            new_status = existing["status"]
            if auto_promote and existing["status"] != CandidateStatus.AUTO_PROMOTED.value:
                new_status = CandidateStatus.AUTO_PROMOTED.value

            policy_trace = json.loads(existing["policy_trace_json"])
            policy_trace["last_corroboration_at"] = now
            policy_trace["auto_promote_reason"] = ap_reason

            conn.execute(
                """
                UPDATE candidates
                SET evidence_refs_json = ?,
                    evidence_stats_json = ?,
                    trust_score = ?,
                    status = ?,
                    policy_trace_json = ?,
                    updated_at = ?,
                    promoted_at = COALESCE(promoted_at, ?)
                WHERE fingerprint = ?
                """,
                (
                    _canonical_json(evidence_refs),
                    _canonical_json(evidence_stats),
                    new_trust,
                    new_status,
                    _canonical_json(policy_trace),
                    now,
                    now if auto_promote else None,
                    fingerprint,
                ),
            )

            return UpsertResult(
                candidate_id=existing["candidate_id"],
                is_new=False,
                is_corroborated=evidence_stats["independent_source_families"] >= 2,
                is_auto_promoted=(new_status == CandidateStatus.AUTO_PROMOTED.value),
                trust_score=new_trust,
                status=CandidateStatus(new_status),
            )

    def promote_candidate(
        self,
        candidate_id: str,
        *,
        ledger_event_id: str,
        decision_id: Optional[str] = None,
    ) -> None:
        """Mark candidate as promoted to ledger. Atomic.

        Caller (promotion_policy in Task #28) is responsible for actually
        writing the ledger event first; this just updates the candidate row.
        """
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE candidates
                SET status = ?, ledger_event_id = ?, decision_id = ?,
                    trust_score = ?, promoted_at = COALESCE(promoted_at, ?),
                    updated_at = ?
                WHERE candidate_id = ?
                """,
                (
                    CandidateStatus.APPROVED.value,
                    ledger_event_id,
                    decision_id or "auto_promoted",
                    TRUST_LEDGER,
                    now,
                    now,
                    candidate_id,
                ),
            )

    def deny_candidate(
        self,
        candidate_id: str,
        *,
        reason: str,
        decision_id: str,
    ) -> None:
        """Mark candidate as denied (terminal)."""
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE candidates
                SET status = ?, decision_id = ?, denied_at = ?, updated_at = ?,
                    policy_trace_json = json_patch(
                        policy_trace_json,
                        json_object('denied_reason', ?)
                    )
                WHERE candidate_id = ?
                """,
                (
                    CandidateStatus.DENIED.value,
                    decision_id,
                    now, now,
                    reason,
                    candidate_id,
                ),
            )

    def get_candidate(self, candidate_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_pending(self, *, lane: Optional[str] = None) -> list[dict[str, Any]]:
        """Return pending candidates, optionally filtered by lane."""
        sql = "SELECT * FROM candidates WHERE status = ?"
        params: list[Any] = [CandidateStatus.PENDING.value]
        if lane is not None:
            sql += " AND lane = ?"
            params.append(lane)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def list_requires_approval(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM candidates WHERE status = ? ORDER BY created_at ASC",
                (CandidateStatus.REQUIRES_APPROVAL.value,),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_dead_letter(
        self,
        *,
        source_lane: str,
        payload: dict[str, Any],
        attempts: int,
        last_error: Optional[str] = None,
    ) -> str:
        """Push a failed extraction into the dead letter queue. Returns DLQ id."""
        now = _utc_now()
        dlq_id = _new_ulid()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO om_dead_letter_queue (
                    dead_letter_id, source_lane, payload_json,
                    attempts, last_error,
                    first_seen_at, last_attempted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dlq_id, source_lane, _canonical_json(payload),
                    attempts, last_error,
                    now, now,
                ),
            )
        return dlq_id
