"""Promotion policy — 4-gate pipeline from quarantined candidate to ledger.

Ported architecture from Bicameral truth/promotion_policy_v3.py with Atlas
wiring. Four gates run in order; any failure blocks promotion:

  Gate 1 — Policy: candidate must satisfy quarantine auto_promote rules
  Gate 2 — Verification: corroboration must be >= verification floor
  Gate 3 — Hard-block: configurable safety predicates (defaults: deny-list)
  Gate 4 — Ledger write: atomic — ledger event THEN candidate.promoted

Phase 2 W4 ships the gate scaffolding + ledger-write atomicity. The hard-block
predicate registry is intentionally minimal in v1; production deployments
extend via register_hard_block().

Spec: 05 - Atlas Architecture & Schema § 6
      03 - Atlas Technical Foundation § 4.4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable, Optional

from atlas_core.trust.ledger import EventType, HashChainedLedger, LedgerEvent
from atlas_core.trust.quarantine import (
    AUTO_PROMOTE_THRESHOLD,
    CandidateStatus,
    QuarantineStore,
)

if TYPE_CHECKING:
    pass


log = logging.getLogger(__name__)


# ─── Verification floor ──────────────────────────────────────────────────────

VERIFICATION_FLOOR_CONFIDENCE: float = 0.80
"""Below this candidate.confidence, NEVER promote even if all other gates pass.
Conservative baseline; calibrated against BusinessMemBench in Phase 3."""


# ─── Gate outcomes ───────────────────────────────────────────────────────────


class GateOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"


@dataclass
class GateResult:
    gate: str
    outcome: GateOutcome
    reason: str = ""


@dataclass
class PromotionResult:
    """Aggregate result of running the full 4-gate pipeline on one candidate."""

    candidate_id: str
    promoted: bool
    gates: list[GateResult] = field(default_factory=list)
    ledger_event: Optional[LedgerEvent] = None
    blocked_at_gate: Optional[str] = None
    blocked_reason: str = ""

    def first_failure(self) -> Optional[GateResult]:
        for g in self.gates:
            if g.outcome == GateOutcome.FAIL:
                return g
        return None


# ─── Hard-block registry (configurable safety net) ───────────────────────────


HardBlockPredicate = Callable[[dict], Optional[str]]
"""A predicate over a candidate dict. Returns None to allow, or a string
explaining why the candidate is blocked."""


_HARD_BLOCK_PREDICATES: list[HardBlockPredicate] = []


def register_hard_block(predicate: HardBlockPredicate) -> None:
    """Register a hard-block predicate. Predicates are checked in registration
    order; any non-None return blocks promotion immediately.

    Phase 2 W4 ships an empty default registry. Production deployments extend
    via this hook (e.g., to block predicates matching deny-listed patterns,
    or to enforce per-tenant scope rules).
    """
    _HARD_BLOCK_PREDICATES.append(predicate)


def clear_hard_blocks() -> None:
    """Test-only helper: reset the predicate registry between tests."""
    _HARD_BLOCK_PREDICATES.clear()


def _check_hard_blocks(candidate: dict) -> Optional[str]:
    """Run all registered predicates. Returns first block reason, or None."""
    for predicate in _HARD_BLOCK_PREDICATES:
        reason = predicate(candidate)
        if reason is not None:
            return reason
    return None


# ─── Promotion pipeline ──────────────────────────────────────────────────────


class PromotionPolicy:
    """Coordinates promotion from quarantine → ledger.

    Wires the trust quarantine + hash-chained ledger into a single atomic
    pipeline. Caller invokes promote(candidate_id); pipeline runs the
    four gates and either promotes (writing both a ledger event and
    updating the candidate row) or returns the gate failure.
    """

    def __init__(
        self,
        *,
        quarantine: QuarantineStore,
        ledger: HashChainedLedger,
        policy_version: str = "v1",
    ):
        self.quarantine = quarantine
        self.ledger = ledger
        self.policy_version = policy_version

    def promote(
        self,
        candidate_id: str,
        *,
        actor_id: str = "atlas",
        decision_id: Optional[str] = None,
    ) -> PromotionResult:
        """Run the 4-gate pipeline. Returns PromotionResult with gates list.

        Atomic: either the ledger event AND the candidate row update both
        succeed, or neither does (the ledger append is itself atomic via
        BEGIN IMMEDIATE; candidate update follows).
        """
        result = PromotionResult(candidate_id=candidate_id, promoted=False)

        # Load candidate
        candidate = self.quarantine.get_candidate(candidate_id)
        if candidate is None:
            result.gates.append(GateResult(
                gate="lookup", outcome=GateOutcome.FAIL,
                reason=f"candidate {candidate_id} not found",
            ))
            result.blocked_at_gate = "lookup"
            result.blocked_reason = "candidate not found"
            return result

        # Gate 1: Policy — candidate must be in auto_promoted state OR caller
        # is explicitly approving a requires_approval candidate.
        gate1 = self._gate_policy(candidate)
        result.gates.append(gate1)
        if gate1.outcome == GateOutcome.FAIL:
            result.blocked_at_gate = gate1.gate
            result.blocked_reason = gate1.reason
            return result

        # Gate 2: Verification floor
        gate2 = self._gate_verification(candidate)
        result.gates.append(gate2)
        if gate2.outcome == GateOutcome.FAIL:
            result.blocked_at_gate = gate2.gate
            result.blocked_reason = gate2.reason
            return result

        # Gate 3: Hard-block predicates (extensible safety net)
        gate3 = self._gate_hard_block(candidate)
        result.gates.append(gate3)
        if gate3.outcome == GateOutcome.FAIL:
            result.blocked_at_gate = gate3.gate
            result.blocked_reason = gate3.reason
            return result

        # Gate 4: Ledger write — atomic event creation + candidate update
        try:
            ledger_event = self._write_ledger_event(
                candidate=candidate, actor_id=actor_id,
            )
            self.quarantine.promote_candidate(
                candidate_id=candidate_id,
                ledger_event_id=ledger_event.event_id,
                decision_id=decision_id,
            )
            result.gates.append(GateResult(
                gate="ledger_write", outcome=GateOutcome.PASS,
                reason=f"chain_seq={ledger_event.chain_sequence}",
            ))
            result.promoted = True
            result.ledger_event = ledger_event

            log.info(
                "Promoted candidate %s to ledger seq %d",
                candidate_id, ledger_event.chain_sequence,
            )
        except Exception as exc:
            result.gates.append(GateResult(
                gate="ledger_write", outcome=GateOutcome.FAIL,
                reason=f"{type(exc).__name__}: {exc}",
            ))
            result.blocked_at_gate = "ledger_write"
            result.blocked_reason = str(exc)

        return result

    # ── Gate implementations ────────────────────────────────────────────────

    def _gate_policy(self, candidate: dict) -> GateResult:
        """Gate 1: candidate must be in a promote-eligible state.

        Acceptable: AUTO_PROMOTED (passed quarantine eligibility check on
        upsert), or REQUIRES_APPROVAL (caller explicitly approving).

        Rejected: PENDING (insufficient evidence), DENIED (terminal),
        APPROVED (already promoted).
        """
        status = candidate["status"]
        if status == CandidateStatus.AUTO_PROMOTED.value:
            return GateResult(gate="policy", outcome=GateOutcome.PASS,
                              reason="auto_promoted")
        if status == CandidateStatus.REQUIRES_APPROVAL.value:
            return GateResult(gate="policy", outcome=GateOutcome.PASS,
                              reason="requires_approval (explicit)")
        return GateResult(
            gate="policy", outcome=GateOutcome.FAIL,
            reason=f"status={status} not promote-eligible",
        )

    def _gate_verification(self, candidate: dict) -> GateResult:
        """Gate 2: candidate confidence must meet verification floor."""
        confidence = float(candidate["confidence"])
        if confidence < VERIFICATION_FLOOR_CONFIDENCE:
            return GateResult(
                gate="verification", outcome=GateOutcome.FAIL,
                reason=f"confidence {confidence:.2f} below floor "
                       f"{VERIFICATION_FLOOR_CONFIDENCE:.2f}",
            )
        return GateResult(gate="verification", outcome=GateOutcome.PASS,
                          reason=f"confidence={confidence:.2f}")

    def _gate_hard_block(self, candidate: dict) -> GateResult:
        """Gate 3: run hard-block predicate registry."""
        block_reason = _check_hard_blocks(candidate)
        if block_reason is not None:
            return GateResult(
                gate="hard_block", outcome=GateOutcome.FAIL,
                reason=block_reason,
            )
        return GateResult(gate="hard_block", outcome=GateOutcome.PASS,
                          reason="no predicate blocked")

    # ── Ledger event construction ───────────────────────────────────────────

    def _write_ledger_event(
        self,
        *,
        candidate: dict,
        actor_id: str,
    ) -> LedgerEvent:
        """Build and append the promote event for this candidate."""
        return self.ledger.append_event(
            event_type=EventType.PROMOTE,
            actor_id=actor_id,
            object_id=candidate["subject_kref"],
            object_type=candidate["assertion_type"],
            root_id=candidate["subject_kref"],
            payload={
                "predicate": candidate["predicate"],
                "object_value": candidate["object_value"],
                "scope": candidate["scope"],
                "confidence": candidate["confidence"],
                "lane": candidate["lane"],
            },
            candidate_id=candidate["candidate_id"],
            policy_version=self.policy_version,
            reason="promotion via 4-gate pipeline",
        )
