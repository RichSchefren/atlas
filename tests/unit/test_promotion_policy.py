"""Unit tests for the 4-gate promotion policy pipeline.

Wires QuarantineStore + HashChainedLedger together. Verifies each gate's
pass/fail conditions and the atomic ledger-write + candidate-update.
"""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def quarantine(tmp_dir):
    from atlas_core.trust import QuarantineStore
    return QuarantineStore(tmp_dir / "candidates.db")


@pytest.fixture
def ledger(tmp_dir):
    from atlas_core.trust import HashChainedLedger
    return HashChainedLedger(tmp_dir / "ledger.db")


@pytest.fixture
def policy(quarantine, ledger):
    from atlas_core.trust import PromotionPolicy, clear_hard_blocks

    clear_hard_blocks()  # reset registry between tests
    return PromotionPolicy(quarantine=quarantine, ledger=ledger)


def make_claim(
    *,
    predicate: str = "pref.theme",
    object_value: str = "dark",
    confidence: float = 0.95,
    source_family: str = "session",
):
    from atlas_core.trust import CandidateClaim, EvidenceRef

    return CandidateClaim(
        lane="atlas_sessions",
        assertion_type="preference",
        subject_kref="kref://test/People/rich.person",
        predicate=predicate,
        object_value=object_value,
        confidence=confidence,
        evidence_ref=EvidenceRef(
            source="session_x",
            source_family=source_family,
            kref="kref://test/Sessions/x.session",
            timestamp="2026-04-25T20:00:00+00:00",
        ),
    )


# ─── Gate 1: Policy ──────────────────────────────────────────────────────────


class TestGate1Policy:
    def test_auto_promoted_passes_gate1(self, quarantine, policy):
        from atlas_core.trust import GateOutcome

        upsert = quarantine.upsert_candidate(make_claim())
        assert upsert.is_auto_promoted is True

        result = policy.promote(upsert.candidate_id)
        gate1 = next(g for g in result.gates if g.gate == "policy")
        assert gate1.outcome == GateOutcome.PASS

    def test_pending_blocks_at_gate1(self, quarantine, policy):

        # pref/style + low confidence → PENDING (not auto-promoted)
        upsert = quarantine.upsert_candidate(
            make_claim(confidence=0.5),
        )

        result = policy.promote(upsert.candidate_id)
        assert result.promoted is False
        assert result.blocked_at_gate == "policy"

    def test_unknown_candidate_blocks(self, policy):
        result = policy.promote("nonexistent_ulid")
        assert result.promoted is False
        assert result.blocked_at_gate == "lookup"


# ─── Gate 2: Verification floor ──────────────────────────────────────────────


class TestGate2Verification:
    def test_above_floor_passes(self, quarantine, policy):
        from atlas_core.trust import GateOutcome

        upsert = quarantine.upsert_candidate(make_claim(confidence=0.95))
        result = policy.promote(upsert.candidate_id)
        gate2 = next(g for g in result.gates if g.gate == "verification")
        assert gate2.outcome == GateOutcome.PASS

    def test_below_floor_blocks(self, quarantine, policy):
        # High-risk claim (finance.) at 0.99 → reaches gate1 (REQUIRES_APPROVAL)
        # but if confidence drops below 0.80 verification floor it'd block at gate2
        upsert = quarantine.upsert_candidate(
            make_claim(predicate="finance.salary", object_value="$x", confidence=0.79),
        )
        # Auto-promote disabled for high-risk; status=REQUIRES_APPROVAL
        # → Gate1 passes (we explicitly approve), Gate2 fails
        result = policy.promote(upsert.candidate_id)
        assert result.promoted is False
        assert result.blocked_at_gate == "verification"


# ─── Gate 3: Hard-block predicates ───────────────────────────────────────────


class TestGate3HardBlock:
    def test_no_predicates_passes_by_default(self, quarantine, policy):
        from atlas_core.trust import GateOutcome

        upsert = quarantine.upsert_candidate(make_claim())
        result = policy.promote(upsert.candidate_id)
        gate3 = next(g for g in result.gates if g.gate == "hard_block")
        assert gate3.outcome == GateOutcome.PASS

    def test_registered_predicate_can_block(self, quarantine, policy):
        from atlas_core.trust import register_hard_block

        def deny_secret(c: dict) -> str | None:
            if "secret" in c.get("object_value", "").lower():
                return "object_value contains 'secret' (test deny-list)"
            return None

        register_hard_block(deny_secret)

        upsert = quarantine.upsert_candidate(
            make_claim(object_value="my secret password"),
        )
        result = policy.promote(upsert.candidate_id)
        assert result.promoted is False
        assert result.blocked_at_gate == "hard_block"
        assert "secret" in result.blocked_reason.lower()


# ─── Gate 4: Ledger write + atomicity ────────────────────────────────────────


class TestGate4LedgerWrite:
    def test_successful_promotion_writes_ledger_event(
        self, quarantine, ledger, policy
    ):
        from atlas_core.trust import CandidateStatus

        upsert = quarantine.upsert_candidate(make_claim())
        result = policy.promote(upsert.candidate_id)

        assert result.promoted is True
        assert result.ledger_event is not None
        assert result.ledger_event.event_type == "promote"
        assert result.ledger_event.candidate_id == upsert.candidate_id
        assert result.ledger_event.chain_sequence == 1

        # Candidate row updated to APPROVED
        row = quarantine.get_candidate(upsert.candidate_id)
        assert row["status"] == CandidateStatus.APPROVED.value
        assert row["ledger_event_id"] == result.ledger_event.event_id

    def test_ledger_chain_extends_correctly(self, quarantine, ledger, policy):
        # Promote two candidates → chain of length 2
        upsert1 = quarantine.upsert_candidate(
            make_claim(predicate="pref.theme", object_value="dark"),
        )
        upsert2 = quarantine.upsert_candidate(
            make_claim(predicate="pref.font", object_value="mono"),
        )

        r1 = policy.promote(upsert1.candidate_id)
        r2 = policy.promote(upsert2.candidate_id)

        assert r1.ledger_event.chain_sequence == 1
        assert r2.ledger_event.chain_sequence == 2
        assert r2.ledger_event.previous_hash == r1.ledger_event.event_id

        # Chain remains intact
        verify = ledger.verify_chain()
        assert verify.intact is True
        assert verify.last_verified_sequence == 2

    def test_failed_promotion_writes_no_ledger_event(
        self, quarantine, ledger, policy
    ):
        # A pending candidate fails Gate 1 — ledger should remain empty
        upsert = quarantine.upsert_candidate(make_claim(confidence=0.5))
        assert upsert.is_auto_promoted is False  # pending

        result = policy.promote(upsert.candidate_id)
        assert result.promoted is False
        assert result.ledger_event is None

        # Ledger has no events
        assert ledger.chain_length() == 0


# ─── End-to-end ──────────────────────────────────────────────────────────────


class TestEndToEnd:
    def test_promotion_makes_is_promoted_true(self, quarantine, ledger, policy):
        upsert = quarantine.upsert_candidate(make_claim())
        result = policy.promote(upsert.candidate_id)

        # Ripple gate: ledger.is_promoted() returns True for the promoted kref
        assert ledger.is_promoted(result.ledger_event.object_id)
        assert ledger.is_promoted(upsert.candidate_id)

    def test_full_gate_trace_recorded(self, quarantine, policy):
        upsert = quarantine.upsert_candidate(make_claim())
        result = policy.promote(upsert.candidate_id)

        gate_names = [g.gate for g in result.gates]
        # All four gates ran
        assert "policy" in gate_names
        assert "verification" in gate_names
        assert "hard_block" in gate_names
        assert "ledger_write" in gate_names
