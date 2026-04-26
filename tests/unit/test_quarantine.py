"""Unit tests for QuarantineStore — uses temp SQLite databases, no Neo4j."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "candidates.db"


@pytest.fixture
def store(tmp_db):
    from atlas_core.trust import QuarantineStore
    return QuarantineStore(tmp_db)


def make_claim(
    *,
    lane: str = "atlas_sessions",
    subject: str = "kref://test/People/ashley.person",
    predicate: str = "role",
    object_value: str = "operations",
    confidence: float = 0.85,
    source: str = "session_2026-04-25",
    source_family: str = "session",
    source_kref: str = "kref://test/Sessions/abc.session",
):
    from atlas_core.trust import CandidateClaim, EvidenceRef

    return CandidateClaim(
        lane=lane,
        assertion_type="factual_assertion",
        subject_kref=subject,
        predicate=predicate,
        object_value=object_value,
        confidence=confidence,
        evidence_ref=EvidenceRef(
            source=source,
            source_family=source_family,
            kref=source_kref,
            timestamp="2026-04-25T20:00:00+00:00",
        ),
    )


# ─── Schema + smoke ──────────────────────────────────────────────────────────


class TestSchema:
    def test_initializes_clean(self, store, tmp_db):
        # Should not error and the file should exist
        assert tmp_db.exists()

    def test_idempotent_init(self, tmp_db):
        from atlas_core.trust import QuarantineStore
        s1 = QuarantineStore(tmp_db)
        s2 = QuarantineStore(tmp_db)
        assert s1 is not s2  # different instances OK
        # No errors

    def test_lane_constants_consistent(self):
        from atlas_core.trust import (
            LANE_CANDIDATES_ELIGIBLE,
            LANE_CORROBORATION_ONLY,
            LANE_RETRIEVAL_ELIGIBLE_GLOBAL,
        )

        # corroboration-only lane is in candidate-eligible (it generates)
        assert "atlas_imported_day1" in LANE_CANDIDATES_ELIGIBLE
        # curated/self-audit are retrieval-eligible but NOT candidate-generating
        assert "atlas_curated" in LANE_RETRIEVAL_ELIGIBLE_GLOBAL
        assert "atlas_curated" not in LANE_CANDIDATES_ELIGIBLE
        assert "atlas_self_audit" not in LANE_CANDIDATES_ELIGIBLE


# ─── Upsert lifecycle ────────────────────────────────────────────────────────


class TestUpsertNew:
    def test_first_upsert_returns_is_new(self, store):
        result = store.upsert_candidate(make_claim())
        assert result.is_new is True
        assert result.candidate_id  # ULID
        assert result.is_corroborated is False  # single source

    def test_low_risk_pref_high_conf_auto_promotes(self, store):
        from atlas_core.trust import CandidateStatus, TRUST_LEDGER

        claim = make_claim(
            predicate="pref.color",
            object_value="cool tones",
            confidence=0.95,
        )
        result = store.upsert_candidate(claim)
        assert result.is_auto_promoted is True
        assert result.status == CandidateStatus.AUTO_PROMOTED
        assert result.trust_score == TRUST_LEDGER

    def test_low_risk_below_threshold_does_not_auto_promote(self, store):
        from atlas_core.trust import CandidateStatus

        claim = make_claim(
            predicate="pref.color",
            object_value="warm tones",
            confidence=0.85,  # below 0.90 threshold
        )
        result = store.upsert_candidate(claim)
        assert result.is_auto_promoted is False
        assert result.status == CandidateStatus.PENDING

    def test_high_risk_never_auto_promotes(self, store):
        from atlas_core.trust import CandidateStatus

        claim = make_claim(
            predicate="finance.salary",
            object_value="$150k",
            confidence=0.99,
        )
        result = store.upsert_candidate(claim)
        assert result.is_auto_promoted is False
        assert result.status == CandidateStatus.REQUIRES_APPROVAL

    def test_sensitive_content_escalates_to_high(self, store):
        from atlas_core.trust import CandidateStatus

        claim = make_claim(
            predicate="security.password",  # also has high prefix
            object_value="hunter2",
            confidence=0.99,
        )
        result = store.upsert_candidate(claim)
        assert result.is_auto_promoted is False
        assert result.status == CandidateStatus.REQUIRES_APPROVAL

    def test_invalid_lane_raises(self, store):
        with pytest.raises(ValueError, match="not in candidate-eligible"):
            store.upsert_candidate(make_claim(lane="atlas_curated"))


# ─── Dedup + corroboration ───────────────────────────────────────────────────


class TestUpsertCorroboration:
    def test_same_claim_dedups_to_same_candidate_id(self, store):
        result1 = store.upsert_candidate(make_claim())
        result2 = store.upsert_candidate(make_claim())  # identical
        assert result1.candidate_id == result2.candidate_id
        assert result2.is_new is False

    def test_two_sources_corroborate(self, store):
        # Same claim from session source
        c1 = make_claim(source="session", source_family="session")
        store.upsert_candidate(c1)
        # Same claim from a meeting (different source family)
        c2 = make_claim(source="fireflies", source_family="meeting")
        result = store.upsert_candidate(c2)

        assert result.is_corroborated is True
        # Trust score elevates above quarantine
        from atlas_core.trust import TRUST_QUARANTINED
        assert result.trust_score > TRUST_QUARANTINED

    def test_two_sources_same_family_does_not_corroborate(self, store):
        c1 = make_claim(source="session_a", source_family="session")
        store.upsert_candidate(c1)
        c2 = make_claim(source="session_b", source_family="session")
        result = store.upsert_candidate(c2)
        assert result.is_corroborated is False

    def test_medium_risk_corroborated_high_conf_auto_promotes(self, store):
        # Medium-risk claim — needs ≥2 independent source families AND ≥0.90
        c1 = make_claim(
            predicate="role",  # medium-risk default
            object_value="ops_lead",
            confidence=0.95,
            source_family="session",
        )
        result1 = store.upsert_candidate(c1)
        assert result1.is_auto_promoted is False  # 1 source family

        c2 = make_claim(
            predicate="role",
            object_value="ops_lead",
            confidence=0.95,
            source="meeting_1",
            source_family="meeting",
        )
        result2 = store.upsert_candidate(c2)
        assert result2.is_corroborated is True
        # Two source families + ≥0.90 confidence → auto-promote
        assert result2.is_auto_promoted is True


# ─── Promote / deny / list ───────────────────────────────────────────────────


class TestLifecycle:
    def test_promote_candidate_marks_approved(self, store):
        from atlas_core.trust import CandidateStatus, TRUST_LEDGER

        result = store.upsert_candidate(make_claim())
        store.promote_candidate(
            result.candidate_id,
            ledger_event_id="evt_abc123",
            decision_id="auto_promoted",
        )
        row = store.get_candidate(result.candidate_id)
        assert row["status"] == CandidateStatus.APPROVED.value
        assert row["ledger_event_id"] == "evt_abc123"
        assert row["trust_score"] == TRUST_LEDGER

    def test_deny_candidate_marks_denied(self, store):
        from atlas_core.trust import CandidateStatus

        result = store.upsert_candidate(make_claim(confidence=0.5))
        store.deny_candidate(
            result.candidate_id,
            reason="contradicted by other source",
            decision_id="rich_2026-04-25",
        )
        row = store.get_candidate(result.candidate_id)
        assert row["status"] == CandidateStatus.DENIED.value
        assert row["denied_at"] is not None

    def test_list_pending_returns_only_pending(self, store):
        # Create one pending + one denied
        c1 = make_claim(predicate="pref.theme", object_value="dark", confidence=0.5)
        result1 = store.upsert_candidate(c1)
        c2 = make_claim(predicate="pref.font", object_value="mono", confidence=0.5)
        result2 = store.upsert_candidate(c2)
        store.deny_candidate(result2.candidate_id, reason="x", decision_id="x")

        pending = store.list_pending()
        ids = {p["candidate_id"] for p in pending}
        assert result1.candidate_id in ids
        assert result2.candidate_id not in ids

    def test_list_requires_approval_filters_correctly(self, store):
        # high-risk goes to requires_approval
        c1 = make_claim(predicate="finance.revenue", object_value="$1M", confidence=0.95)
        result1 = store.upsert_candidate(c1)
        # low-risk → pending or auto_promoted, NOT requires_approval
        c2 = make_claim(predicate="pref.dark_mode", object_value="true", confidence=0.5)
        result2 = store.upsert_candidate(c2)

        approval = store.list_requires_approval()
        ids = {p["candidate_id"] for p in approval}
        assert result1.candidate_id in ids
        assert result2.candidate_id not in ids


# ─── Dead letter queue ───────────────────────────────────────────────────────


class TestDeadLetter:
    def test_dlq_entry_created(self, store):
        dlq_id = store.upsert_dead_letter(
            source_lane="atlas_observational",
            payload={"raw": "garbled extraction failure"},
            attempts=3,
            last_error="LLM timeout",
        )
        assert dlq_id  # ULID returned
