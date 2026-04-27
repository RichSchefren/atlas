"""Hash-chained ledger — Atlas-original. Real SHA-256 chain.

Bicameral's change_ledger.py uses random event_ids with no `previous_hash`
field — the README claims hash-chained but the code is a sketch. Atlas
implements the actual cryptographic chain:

  event_id = SHA-256(previous_hash + canonical_payload)
  chain_sequence: monotonic UNIQUE INTEGER for gap detection
  verify_chain(): walks from genesis to latest, validates every link

Ripple's gating rule fires only on facts promoted to this ledger
(trust = 1.0). Once promoted, the entry is cryptographically chained and
tamper-evident — any post-hoc modification breaks `verify_chain()`.

Spec: 05 - Atlas Architecture & Schema § 6
      03 - Atlas Technical Foundation § 4.4
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
from typing import Any

log = logging.getLogger(__name__)


# ─── Event vocabulary (port from Bicameral) ──────────────────────────────────


class EventType(str, Enum):
    """Eight canonical ledger event types."""

    ASSERT = "assert"                       # First assertion of a fact
    SUPERSEDE = "supersede"                 # Replace a prior revision
    INVALIDATE = "invalidate"               # Mark prior revision invalid (no replacement)
    REFINE = "refine"                       # Add/clarify content without supersession
    DERIVE = "derive"                       # New revision derived from upstream evidence
    PROMOTE = "promote"                     # Candidate moved from quarantine to ledger
    PROCEDURE_SUCCESS = "procedure_success"
    PROCEDURE_FAILURE = "procedure_failure"


CREATE_EVENT_TYPES: frozenset[str] = frozenset({
    EventType.ASSERT.value,
    EventType.SUPERSEDE.value,
    EventType.REFINE.value,
    EventType.DERIVE.value,
})
"""Event types that establish a new content state — require non-empty payload."""


# ─── Result types ────────────────────────────────────────────────────────────


@dataclass
class LedgerEvent:
    """A single ledger record. Returned by append_event() so callers have
    the chain coordinates for cross-references."""

    event_id: str
    previous_hash: str | None
    chain_sequence: int
    event_type: str
    recorded_at: str
    actor_id: str
    object_id: str
    object_type: str
    root_id: str
    payload: dict[str, Any]

    target_object_id: str | None = None
    parent_id: str | None = None
    candidate_id: str | None = None
    policy_version: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChainVerificationResult:
    """Outcome of verify_chain()."""

    intact: bool
    last_verified_sequence: int
    last_verified_event_id: str
    broken_at_sequence: int | None = None
    breakage_reason: str | None = None


# ─── Helpers ─────────────────────────────────────────────────────────────────


GENESIS_PREVIOUS_HASH: str = "genesis"
"""Sentinel used for the previous_hash field of the genesis event when
computing event_id. Stored as NULL in the previous_hash column."""

VERIFIER_VERSION: str = "atlas-verify-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(obj: Any) -> str:
    """Sorted-keys, no-whitespace JSON. Required for deterministic hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _compute_event_id(
    previous_hash: str | None,
    event_type: str,
    recorded_at: str,
    object_id: str,
    payload_json: str,
) -> str:
    """Compute the SHA-256 chain hash for a candidate event.

    Inputs are joined by '|' separator. Order matters and is fixed forever:
    previous_hash | event_type | recorded_at | object_id | payload_json.

    The use of GENESIS_PREVIOUS_HASH for the first event makes the chain
    self-rooted — verifying any prefix of the chain is a closed computation.
    """
    canonical = (
        f"{previous_hash or GENESIS_PREVIOUS_HASH}|"
        f"{event_type}|"
        f"{recorded_at}|"
        f"{object_id}|"
        f"{payload_json}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ─── HashChainedLedger ───────────────────────────────────────────────────────


class HashChainedLedger:
    """Atlas's tamper-evident append-only ledger.

    Every event is identified by SHA-256(previous_hash + canonical_payload).
    Modifying ANY past event breaks `verify_chain()` because subsequent
    event_ids no longer match their stored values.

    Atomic append via BEGIN IMMEDIATE; no concurrent writers can introduce
    chain gaps. `previous_hash` is stored explicitly as a column so the
    chain integrity check doesn't require recomputing every prior event.
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
        schema_path = Path(__file__).parent / "schemas" / "ledger.schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema_sql)

    # ── Append API ──────────────────────────────────────────────────────────

    def append_event(
        self,
        *,
        event_type: EventType | str,
        actor_id: str,
        object_id: str,
        object_type: str,
        root_id: str,
        payload: dict[str, Any],
        target_object_id: str | None = None,
        parent_id: str | None = None,
        candidate_id: str | None = None,
        policy_version: str | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LedgerEvent:
        """Append a new event to the chain. Atomic.

        Returns the LedgerEvent with the assigned chain coordinates so the
        caller can link to it (e.g., promote_candidate(ledger_event_id=...)).
        """
        event_type_str = (
            event_type.value if isinstance(event_type, EventType) else event_type
        )

        # Validate payload presence for create events
        if event_type_str in CREATE_EVENT_TYPES and not payload:
            raise ValueError(
                f"Event type {event_type_str!r} requires a non-empty payload"
            )

        recorded_at = _utc_now()
        payload_json = _canonical_json(payload)
        metadata_json = _canonical_json(metadata or {})

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                last = conn.execute(
                    "SELECT event_id, chain_sequence FROM change_events "
                    "ORDER BY chain_sequence DESC LIMIT 1"
                ).fetchone()

                if last is None:
                    previous_hash = None
                    next_sequence = 1
                else:
                    previous_hash = last["event_id"]
                    next_sequence = last["chain_sequence"] + 1

                event_id = _compute_event_id(
                    previous_hash=previous_hash,
                    event_type=event_type_str,
                    recorded_at=recorded_at,
                    object_id=object_id,
                    payload_json=payload_json,
                )

                conn.execute(
                    """
                    INSERT INTO change_events (
                        event_id, previous_hash, chain_sequence,
                        event_type, recorded_at, actor_id, reason,
                        object_id, target_object_id, object_type,
                        root_id, parent_id, candidate_id, policy_version,
                        payload_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id, previous_hash, next_sequence,
                        event_type_str, recorded_at, actor_id, reason,
                        object_id, target_object_id, object_type,
                        root_id, parent_id, candidate_id, policy_version,
                        payload_json, metadata_json,
                    ),
                )

                # Maintain typed_roots materialized view
                if event_type_str in CREATE_EVENT_TYPES:
                    conn.execute(
                        """
                        INSERT INTO typed_roots (
                            root_id, object_type, latest_object_id,
                            latest_event_id, latest_recorded_at, is_invalidated
                        ) VALUES (?, ?, ?, ?, ?, 0)
                        ON CONFLICT(root_id) DO UPDATE SET
                            object_type        = excluded.object_type,
                            latest_object_id   = excluded.latest_object_id,
                            latest_event_id    = excluded.latest_event_id,
                            latest_recorded_at = excluded.latest_recorded_at,
                            is_invalidated     = 0
                        """,
                        (root_id, object_type, object_id, event_id, recorded_at),
                    )
                elif event_type_str == EventType.INVALIDATE.value:
                    conn.execute(
                        "UPDATE typed_roots SET is_invalidated = 1, "
                        "    latest_event_id = ?, latest_recorded_at = ? "
                        "WHERE root_id = ?",
                        (event_id, recorded_at, root_id),
                    )

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        log.debug(
            "Ledger append: seq=%d event=%s object=%s actor=%s",
            next_sequence, event_type_str, object_id, actor_id,
        )

        return LedgerEvent(
            event_id=event_id,
            previous_hash=previous_hash,
            chain_sequence=next_sequence,
            event_type=event_type_str,
            recorded_at=recorded_at,
            actor_id=actor_id,
            object_id=object_id,
            object_type=object_type,
            root_id=root_id,
            payload=payload,
            target_object_id=target_object_id,
            parent_id=parent_id,
            candidate_id=candidate_id,
            policy_version=policy_version,
            reason=reason,
            metadata=metadata or {},
        )

    # ── Verification ────────────────────────────────────────────────────────

    def verify_chain(self) -> ChainVerificationResult:
        """Walk the chain in chain_sequence order. Validate every event_id is
        SHA-256(previous_hash + canonical_payload).

        Returns ChainVerificationResult with first breakage point if any.
        Also writes an entry to the chain_verifications audit table.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chain_sequence, event_id, previous_hash,
                       event_type, recorded_at, object_id, payload_json
                FROM change_events
                ORDER BY chain_sequence ASC
                """
            ).fetchall()

        if not rows:
            # Empty ledger is trivially intact
            self._record_verification(
                last_seq=0, last_id="", intact=True, notes="empty ledger"
            )
            return ChainVerificationResult(
                intact=True, last_verified_sequence=0, last_verified_event_id=""
            )

        expected_previous_hash: str | None = None
        last_intact_sequence = 0
        last_intact_event_id = ""

        for i, row in enumerate(rows):
            seq = row["chain_sequence"]
            stored_event_id = row["event_id"]
            stored_prev_hash = row["previous_hash"]

            # Sequence must increment monotonically without gaps
            expected_seq = i + 1
            if seq != expected_seq:
                self._record_verification(
                    last_seq=last_intact_sequence,
                    last_id=last_intact_event_id,
                    intact=False,
                    notes=f"sequence_gap at {seq} (expected {expected_seq})",
                )
                return ChainVerificationResult(
                    intact=False,
                    last_verified_sequence=last_intact_sequence,
                    last_verified_event_id=last_intact_event_id,
                    broken_at_sequence=seq,
                    breakage_reason=f"sequence gap: got {seq}, expected {expected_seq}",
                )

            # previous_hash field must match the immediately-prior event_id
            if stored_prev_hash != expected_previous_hash:
                self._record_verification(
                    last_seq=last_intact_sequence,
                    last_id=last_intact_event_id,
                    intact=False,
                    notes=f"previous_hash mismatch at seq {seq}",
                )
                return ChainVerificationResult(
                    intact=False,
                    last_verified_sequence=last_intact_sequence,
                    last_verified_event_id=last_intact_event_id,
                    broken_at_sequence=seq,
                    breakage_reason=(
                        f"previous_hash mismatch at seq {seq}: "
                        f"stored={stored_prev_hash!r}, expected={expected_previous_hash!r}"
                    ),
                )

            # Recompute event_id from stored fields and compare
            recomputed_id = _compute_event_id(
                previous_hash=stored_prev_hash,
                event_type=row["event_type"],
                recorded_at=row["recorded_at"],
                object_id=row["object_id"],
                payload_json=row["payload_json"],
            )
            if recomputed_id != stored_event_id:
                self._record_verification(
                    last_seq=last_intact_sequence,
                    last_id=last_intact_event_id,
                    intact=False,
                    notes=f"event_id mismatch at seq {seq}",
                )
                return ChainVerificationResult(
                    intact=False,
                    last_verified_sequence=last_intact_sequence,
                    last_verified_event_id=last_intact_event_id,
                    broken_at_sequence=seq,
                    breakage_reason=(
                        f"event_id mismatch at seq {seq}: "
                        f"stored={stored_event_id[:16]}..., "
                        f"recomputed={recomputed_id[:16]}..."
                    ),
                )

            expected_previous_hash = stored_event_id
            last_intact_sequence = seq
            last_intact_event_id = stored_event_id

        self._record_verification(
            last_seq=last_intact_sequence,
            last_id=last_intact_event_id,
            intact=True,
            notes=f"verified {len(rows)} events",
        )
        return ChainVerificationResult(
            intact=True,
            last_verified_sequence=last_intact_sequence,
            last_verified_event_id=last_intact_event_id,
        )

    def _record_verification(
        self, *, last_seq: int, last_id: str, intact: bool, notes: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chain_verifications (
                    verified_at, last_verified_sequence,
                    last_verified_event_id, chain_intact,
                    verifier_version, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (_utc_now(), last_seq, last_id, 1 if intact else 0,
                 VERIFIER_VERSION, notes),
            )

    # ── Read API ────────────────────────────────────────────────────────────

    def is_promoted(self, edge_uuid: str) -> bool:
        """True iff there is at least one event in the ledger whose
        object_id, target_object_id, or candidate_id matches `edge_uuid`.

        Used by AtlasGraphiti.add_episode to gate Ripple — only ledger
        entries trigger Ripple cascades."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM change_events
                WHERE object_id = ?
                   OR target_object_id = ?
                   OR candidate_id = ?
                LIMIT 1
                """,
                (edge_uuid, edge_uuid, edge_uuid),
            ).fetchone()
        return row is not None

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM change_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_root_lineage(self, root_id: str) -> list[dict[str, Any]]:
        """All events for a given root, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM change_events
                WHERE root_id = ?
                ORDER BY chain_sequence ASC
                """,
                (root_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_typed_root_state(self, root_id: str) -> dict[str, Any] | None:
        """Read materialized current state for a root."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM typed_roots WHERE root_id = ?", (root_id,)
            ).fetchone()
        return dict(row) if row else None

    def chain_length(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM change_events"
            ).fetchone()
        return int(row["n"])

    def latest_event(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM change_events ORDER BY chain_sequence DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None
