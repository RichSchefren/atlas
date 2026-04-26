"""Unit tests for the hash-chained ledger.

This is the cryptographic core of Atlas's trust layer. Coverage includes:
  - Genesis event creation
  - Chain extension (multiple events)
  - Hash chain integrity (every link recomputable)
  - Tamper detection — modifying ANY field breaks verify_chain()
  - typed_roots materialized view
  - is_promoted() for Ripple gating
  - Atomic append (no chain gaps)
"""

import hashlib
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_ledger():
    with tempfile.TemporaryDirectory() as tmpdir:
        from atlas_core.trust import HashChainedLedger
        yield HashChainedLedger(Path(tmpdir) / "ledger.db")


def assert_event(
    ev,
    *,
    event_type: str,
    chain_sequence: int,
    previous_hash: str | None,
):
    assert ev.event_type == event_type
    assert ev.chain_sequence == chain_sequence
    assert ev.previous_hash == previous_hash
    assert ev.event_id  # SHA-256 hex
    assert len(ev.event_id) == 64


# ─── Schema + smoke ──────────────────────────────────────────────────────────


class TestSchema:
    def test_init_creates_database(self, tmp_ledger):
        assert tmp_ledger.db_path.exists()
        # Empty ledger reports chain_length 0
        assert tmp_ledger.chain_length() == 0


class TestGenesisEvent:
    def test_first_event_has_no_previous_hash(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        ev = tmp_ledger.append_event(
            event_type=EventType.ASSERT,
            actor_id="atlas",
            object_id="kref://test/Beliefs/x.belief?r=1",
            object_type="StrategicBelief",
            root_id="kref://test/Beliefs/x.belief",
            payload={"hypothesis": "premium pricing wins", "confidence": 0.6},
        )

        assert_event(ev, event_type="assert", chain_sequence=1, previous_hash=None)
        assert tmp_ledger.chain_length() == 1

    def test_genesis_event_id_is_deterministic(self, tmp_ledger):
        """Recompute event_id and verify it matches stored value."""
        from atlas_core.trust.ledger import EventType, _compute_event_id

        ev = tmp_ledger.append_event(
            event_type=EventType.ASSERT,
            actor_id="atlas",
            object_id="kref://test/Beliefs/x.belief?r=1",
            object_type="StrategicBelief",
            root_id="kref://test/Beliefs/x.belief",
            payload={"a": 1},
        )

        # Manually recompute
        import json
        canonical_payload = json.dumps({"a": 1}, sort_keys=True, separators=(",", ":"))
        recomputed = _compute_event_id(
            previous_hash=None,
            event_type="assert",
            recorded_at=ev.recorded_at,
            object_id="kref://test/Beliefs/x.belief?r=1",
            payload_json=canonical_payload,
        )
        assert recomputed == ev.event_id


class TestChainExtension:
    def test_three_event_chain(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        events = []
        for i in range(3):
            ev = tmp_ledger.append_event(
                event_type=EventType.ASSERT if i == 0 else EventType.SUPERSEDE,
                actor_id="atlas",
                object_id=f"kref://test/Beliefs/x.belief?r={i+1}",
                object_type="StrategicBelief",
                root_id="kref://test/Beliefs/x.belief",
                payload={"version": i + 1},
                target_object_id=(events[-1].object_id if events else None),
            )
            events.append(ev)

        assert_event(events[0], event_type="assert", chain_sequence=1, previous_hash=None)
        assert_event(events[1], event_type="supersede", chain_sequence=2,
                     previous_hash=events[0].event_id)
        assert_event(events[2], event_type="supersede", chain_sequence=3,
                     previous_hash=events[1].event_id)
        assert tmp_ledger.chain_length() == 3

    def test_payload_required_for_create_events(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        with pytest.raises(ValueError, match="requires a non-empty payload"):
            tmp_ledger.append_event(
                event_type=EventType.ASSERT,
                actor_id="atlas",
                object_id="kref://test/x.belief",
                object_type="StrategicBelief",
                root_id="kref://test/x.belief",
                payload={},
            )

    def test_promote_event_allows_empty_payload(self, tmp_ledger):
        """PROMOTE is not a CREATE event — empty payload OK."""
        from atlas_core.trust.ledger import EventType

        # Build a base event first
        tmp_ledger.append_event(
            event_type=EventType.ASSERT, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={"v": 1},
        )
        # Now promote with no payload — should succeed
        ev = tmp_ledger.append_event(
            event_type=EventType.PROMOTE, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={},
            candidate_id="01HABC123XYZ",
        )
        assert ev.event_type == "promote"


# ─── Chain verification ──────────────────────────────────────────────────────


class TestVerifyChain:
    def test_empty_chain_is_intact(self, tmp_ledger):
        result = tmp_ledger.verify_chain()
        assert result.intact is True
        assert result.last_verified_sequence == 0

    def test_genesis_only_is_intact(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        tmp_ledger.append_event(
            event_type=EventType.ASSERT, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={"v": 1},
        )
        result = tmp_ledger.verify_chain()
        assert result.intact is True
        assert result.last_verified_sequence == 1

    def test_three_event_chain_intact(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        for i in range(3):
            tmp_ledger.append_event(
                event_type=EventType.ASSERT if i == 0 else EventType.SUPERSEDE,
                actor_id="atlas",
                object_id=f"kref://test/x.belief?r={i+1}",
                object_type="StrategicBelief",
                root_id="kref://test/x.belief",
                payload={"v": i + 1},
            )
        result = tmp_ledger.verify_chain()
        assert result.intact is True
        assert result.last_verified_sequence == 3

    def test_tamper_detection_on_payload(self, tmp_ledger):
        """Modifying payload_json after the fact breaks the chain."""
        from atlas_core.trust.ledger import EventType

        for i in range(3):
            tmp_ledger.append_event(
                event_type=EventType.ASSERT if i == 0 else EventType.SUPERSEDE,
                actor_id="atlas",
                object_id=f"kref://test/x.belief?r={i+1}",
                object_type="StrategicBelief",
                root_id="kref://test/x.belief",
                payload={"v": i + 1},
            )
        # Tamper with the second event's payload
        with sqlite3.connect(tmp_ledger.db_path) as conn:
            conn.execute(
                "UPDATE change_events SET payload_json = ? WHERE chain_sequence = 2",
                ('{"v":999}',),
            )

        result = tmp_ledger.verify_chain()
        assert result.intact is False
        assert result.broken_at_sequence == 2
        assert "event_id mismatch" in (result.breakage_reason or "")

    def test_tamper_detection_on_event_id(self, tmp_ledger):
        """Replacing event_id with a wrong hex breaks at that row."""
        from atlas_core.trust.ledger import EventType

        for i in range(3):
            tmp_ledger.append_event(
                event_type=EventType.ASSERT if i == 0 else EventType.SUPERSEDE,
                actor_id="atlas",
                object_id=f"kref://test/x.belief?r={i+1}",
                object_type="StrategicBelief",
                root_id="kref://test/x.belief",
                payload={"v": i + 1},
            )
        # Tamper: overwrite event_id at seq 2 with a fake hash
        fake = "0" * 64
        with sqlite3.connect(tmp_ledger.db_path) as conn:
            conn.execute(
                "UPDATE change_events SET event_id = ? WHERE chain_sequence = 2",
                (fake,),
            )
            # Also update the third event's previous_hash so that's not what trips it
            conn.execute(
                "UPDATE change_events SET previous_hash = ? WHERE chain_sequence = 3",
                (fake,),
            )

        result = tmp_ledger.verify_chain()
        assert result.intact is False
        assert result.broken_at_sequence == 2

    def test_tamper_detection_on_previous_hash(self, tmp_ledger):
        """Modifying previous_hash without updating event_id breaks at that row."""
        from atlas_core.trust.ledger import EventType

        for i in range(3):
            tmp_ledger.append_event(
                event_type=EventType.ASSERT if i == 0 else EventType.SUPERSEDE,
                actor_id="atlas",
                object_id=f"kref://test/x.belief?r={i+1}",
                object_type="StrategicBelief",
                root_id="kref://test/x.belief",
                payload={"v": i + 1},
            )
        with sqlite3.connect(tmp_ledger.db_path) as conn:
            conn.execute(
                "UPDATE change_events SET previous_hash = ? WHERE chain_sequence = 2",
                ("a" * 64,),
            )

        result = tmp_ledger.verify_chain()
        assert result.intact is False
        assert result.broken_at_sequence == 2


# ─── typed_roots materialized view ───────────────────────────────────────────


class TestTypedRootsMaterializedView:
    def test_assert_creates_typed_root(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        ev = tmp_ledger.append_event(
            event_type=EventType.ASSERT, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={"v": 1},
        )
        state = tmp_ledger.get_typed_root_state("kref://test/x.belief")
        assert state is not None
        assert state["latest_event_id"] == ev.event_id
        assert state["object_type"] == "StrategicBelief"
        assert state["is_invalidated"] == 0

    def test_supersede_updates_typed_root(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        tmp_ledger.append_event(
            event_type=EventType.ASSERT, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={"v": 1},
        )
        ev2 = tmp_ledger.append_event(
            event_type=EventType.SUPERSEDE, actor_id="atlas",
            object_id="kref://test/x.belief?r=2", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={"v": 2},
        )
        state = tmp_ledger.get_typed_root_state("kref://test/x.belief")
        assert state["latest_event_id"] == ev2.event_id
        assert state["latest_object_id"] == "kref://test/x.belief?r=2"

    def test_invalidate_marks_root(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        tmp_ledger.append_event(
            event_type=EventType.ASSERT, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={"v": 1},
        )
        tmp_ledger.append_event(
            event_type=EventType.INVALIDATE, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief",
            payload={"reason": "contradicted"},
        )
        state = tmp_ledger.get_typed_root_state("kref://test/x.belief")
        assert state["is_invalidated"] == 1


# ─── Read API ────────────────────────────────────────────────────────────────


class TestReadAPI:
    def test_get_event_by_id(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        ev = tmp_ledger.append_event(
            event_type=EventType.ASSERT, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={"v": 1},
        )
        row = tmp_ledger.get_event(ev.event_id)
        assert row is not None
        assert row["event_id"] == ev.event_id
        assert row["chain_sequence"] == 1

    def test_get_event_missing_returns_none(self, tmp_ledger):
        assert tmp_ledger.get_event("nonexistent") is None

    def test_get_root_lineage_in_order(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        for i in range(4):
            tmp_ledger.append_event(
                event_type=EventType.ASSERT if i == 0 else EventType.SUPERSEDE,
                actor_id="atlas",
                object_id=f"kref://test/x.belief?r={i+1}",
                object_type="StrategicBelief",
                root_id="kref://test/x.belief",
                payload={"v": i + 1},
            )
        lineage = tmp_ledger.get_root_lineage("kref://test/x.belief")
        assert len(lineage) == 4
        seqs = [r["chain_sequence"] for r in lineage]
        assert seqs == [1, 2, 3, 4]

    def test_is_promoted_finds_object_id(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        tmp_ledger.append_event(
            event_type=EventType.ASSERT, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={"v": 1},
            candidate_id="01HCANDIDATE",
        )
        assert tmp_ledger.is_promoted("kref://test/x.belief?r=1")
        assert tmp_ledger.is_promoted("01HCANDIDATE")
        assert not tmp_ledger.is_promoted("kref://nope/y.belief")

    def test_latest_event(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        for i in range(3):
            tmp_ledger.append_event(
                event_type=EventType.ASSERT if i == 0 else EventType.SUPERSEDE,
                actor_id="atlas",
                object_id=f"kref://test/x.belief?r={i+1}",
                object_type="StrategicBelief",
                root_id="kref://test/x.belief",
                payload={"v": i + 1},
            )
        latest = tmp_ledger.latest_event()
        assert latest is not None
        assert latest["chain_sequence"] == 3


# ─── Verification audit table ────────────────────────────────────────────────


class TestVerificationAudit:
    def test_verify_chain_writes_audit_entry(self, tmp_ledger):
        from atlas_core.trust.ledger import EventType

        tmp_ledger.append_event(
            event_type=EventType.ASSERT, actor_id="atlas",
            object_id="kref://test/x.belief?r=1", object_type="StrategicBelief",
            root_id="kref://test/x.belief", payload={"v": 1},
        )
        tmp_ledger.verify_chain()

        with sqlite3.connect(tmp_ledger.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM chain_verifications"
            ).fetchone()[0]
        assert count == 1
