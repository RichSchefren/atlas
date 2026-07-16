from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / "integrations" / "cognitive-service"
)
sys.path.insert(0, str(SERVICE_DIR))

from service_core import (  # noqa: E402
    CognitiveServiceCore,
    IdempotencyConflict,
    NotFoundError,
    ServiceError,
    StaleWriteConflict,
)

A = "kref://Test/Facts/a.fact"
B = "kref://Test/Beliefs/b.belief"
C = "kref://Test/Beliefs/c.belief"
NOW = "2026-07-16T20:00:00.000000Z"


def core(tmp_path: Path, scope: str = "profile-a") -> CognitiveServiceCore:
    return CognitiveServiceCore(tmp_path / "service.sqlite3", scope_id=scope)


def create(
    service: CognitiveServiceCore,
    root: str,
    kind: str,
    confidence: int,
    *,
    key: str,
    content: object | None = None,
    core_conviction: bool = False,
) -> dict:
    return service.create_item(
        idempotency_key=key,
        root_kref=root,
        kind=kind,
        content=content if content is not None else {"root": root},
        confidence_ppm=confidence,
        is_core_conviction=core_conviction,
        created_at=NOW,
    )


def seed_chain(service: CognitiveServiceCore) -> None:
    create(service, A, "fact", 900_000, key="create-a", content={"price": 2995})
    create(service, B, "belief", 800_000, key="create-b", content={"claim": "B uses A"})
    create(service, C, "belief", 700_000, key="create-c", content={"claim": "C uses B"})
    service.declare_dependency(B, A, strength_ppm=1_000_000, created_at=NOW)
    service.declare_dependency(C, B, strength_ppm=1_000_000, created_at=NOW)


def test_health_declares_exact_single_scope(tmp_path: Path) -> None:
    service = core(tmp_path, "profile-rich")
    health = service.health()
    assert health["status"] == "ok"
    assert health["scope_id"] == "profile-rich"
    assert health["service_version"] == "0.1.0"
    assert health["cognitive_owner"] == "python-service"


def test_create_is_atomic_idempotent_and_preserves_revision_fields(tmp_path: Path) -> None:
    service = core(tmp_path)
    first = service.create_item(
        idempotency_key="create-a", root_kref=A, kind="fact",
        content={"price": 2995}, confidence_ppm=920_000,
        last_evidence_days=4, evidence={"source": "meeting"},
        actor="source-agent", created_at=NOW,
    )
    retry = service.create_item(
        idempotency_key="create-a", root_kref=A, kind="fact",
        content={"price": 2995}, confidence_ppm=920_000,
        last_evidence_days=4, evidence={"source": "meeting"},
        actor="source-agent", created_at=NOW,
    )
    assert retry == first
    assert first["revision"]["kind"] == "fact"
    assert first["revision"]["actor"] == "source-agent"
    assert first["revision"]["revision_reason"] == "initial"
    assert first["revision"]["last_evidence_days"] == 4
    assert service.get_item(A)["lineage"] == [first["revision"]]
    with pytest.raises(IdempotencyConflict):
        service.create_item(
            idempotency_key="create-a", root_kref=A, kind="fact",
            content={"price": 3495}, confidence_ppm=920_000, created_at=NOW,
        )


def test_atomic_revision_cascade_uses_immediate_upstream_and_persists_hashes(
    tmp_path: Path,
) -> None:
    service = core(tmp_path)
    seed_chain(service)
    result = service.revise_item(
        idempotency_key="revise-a", root_kref=A,
        content={"price": 3495}, revision_reason="price contradicted",
        old_confidence_ppm=900_000, new_confidence_ppm=100_000,
        contradicts_prior=True, contradiction_reason="new source",
        actor="review-agent",
        created_at=NOW,
    )
    assert result["revision"]["actor"] == "review-agent"
    assert result["revision"]["revision_reason"] == "price contradicted"
    assert service.audit_item(A)["lineage"][-1]["actor"] == "review-agent"
    assert service.audit_item(A)["lineage"][-1]["revision_reason"] == "price contradicted"
    proposals = {p["target_kref"]: p for p in result["cascade"]["proposals"]}
    assert proposals[B]["new_confidence_ppm"] == 642_500
    assert proposals[C]["upstream_kref"] == B
    assert proposals[C]["new_confidence_ppm"] == 664_563
    assert proposals[C]["components_ppm"]["beta"] == -47_250
    assert proposals[C]["llm_delta_ppm"] == -157_500
    assert all(p["contradiction_detected"] for p in proposals.values())
    assert all(p["route"] == "strategic_review" for p in proposals.values())
    for proposal in proposals.values():
        assert len(proposal["proposal_id"]) == 64
        assert json.loads(proposal["canonical_output"])["target_kref"] == proposal["target_kref"]
    persisted = service.get_item(B)["proposals"][0]
    assert persisted["proposal_id"] == proposals[B]["proposal_id"]


def test_revise_retry_cannot_duplicate_or_mutate_original(tmp_path: Path) -> None:
    service = core(tmp_path)
    seed_chain(service)
    kwargs = dict(
        idempotency_key="revision-once", root_kref=A, content={"price": 3495},
        revision_reason="change", old_confidence_ppm=900_000,
        new_confidence_ppm=300_000, created_at=NOW,
    )
    first = service.revise_item(**kwargs)
    retry = service.revise_item(**kwargs)
    assert retry == first
    retry_after_commit = service.revise_item(
        **{**kwargs, "old_confidence_ppm": kwargs["new_confidence_ppm"]}
    )
    assert retry_after_commit == first
    assert len(service.get_item(A)["lineage"]) == 2
    with pytest.raises(IdempotencyConflict):
        service.revise_item(**{**kwargs, "content": {"price": 9999}})


def test_diamond_convergence_is_not_reported_as_cycle(tmp_path: Path) -> None:
    service = core(tmp_path)
    d = "kref://Test/Beliefs/d.belief"
    create(service, A, "fact", 900_000, key="create-a")
    create(service, B, "belief", 800_000, key="create-b")
    create(service, C, "belief", 700_000, key="create-c")
    create(service, d, "belief", 600_000, key="create-d")
    service.declare_dependency(B, A, strength_ppm=900_000, created_at=NOW)
    service.declare_dependency(C, A, strength_ppm=900_000, created_at=NOW)
    service.declare_dependency(d, B, strength_ppm=900_000, created_at=NOW)
    service.declare_dependency(d, C, strength_ppm=900_000, created_at=NOW)
    cascade = service.run_cascade(
        idempotency_key="diamond", origin_kref=A,
        old_confidence_ppm=900_000, new_confidence_ppm=500_000,
        created_at=NOW,
    )
    assert cascade["cycles"] == []
    assert [proposal["target_kref"] for proposal in cascade["proposals"]] == [B, C, d]
    assert sum(proposal["target_kref"] == d for proposal in cascade["proposals"]) == 1


def test_actual_back_edge_is_reported_as_cycle(tmp_path: Path) -> None:
    service = core(tmp_path)
    seed_chain(service)
    service.declare_dependency(B, C, strength_ppm=1_000_000, created_at=NOW)
    cascade = service.run_cascade(
        idempotency_key="actual-cycle", origin_kref=A,
        old_confidence_ppm=900_000, new_confidence_ppm=500_000,
        created_at=NOW,
    )
    assert cascade["cycles"] == [{"from": C, "to": B}]
    assert [proposal["target_kref"] for proposal in cascade["proposals"]] == [B, C]


def test_cascade_excludes_forgotten_dependent_and_support_endpoints(
    tmp_path: Path,
) -> None:
    dependent_case = CognitiveServiceCore(
        tmp_path / "dependent.sqlite3", scope_id="dependent-case"
    )
    create(dependent_case, A, "fact", 900_000, key="dep-a")
    create(dependent_case, B, "belief", 800_000, key="dep-b")
    dependent_case.declare_dependency(B, A, strength_ppm=1_000_000, created_at=NOW)
    dependent_case.forget_item(B, "root", reason="deprecated dependent", created_at=NOW)
    dependent_result = dependent_case.run_cascade(
        idempotency_key="after-dependent-forget", origin_kref=A,
        old_confidence_ppm=900_000, new_confidence_ppm=500_000,
        created_at=NOW,
    )
    assert dependent_result["nodes_visited"] == 1
    assert dependent_result["impacted_count"] == 0
    assert dependent_result["proposals"] == []

    support_case = CognitiveServiceCore(
        tmp_path / "support.sqlite3", scope_id="support-case"
    )
    create(support_case, A, "fact", 900_000, key="support-a")
    create(support_case, B, "belief", 800_000, key="support-b")
    support_case.declare_dependency(B, A, strength_ppm=1_000_000, created_at=NOW)
    support_case.forget_item(A, "root", reason="deprecated support", created_at=NOW)
    support_result = support_case.run_cascade(
        idempotency_key="after-support-forget", origin_kref=B,
        old_confidence_ppm=800_000, new_confidence_ppm=500_000,
        created_at=NOW,
    )
    assert support_result["nodes_visited"] == 1
    assert support_result["impacted_count"] == 0
    assert support_result["proposals"] == []


def test_deprecated_item_cannot_be_revised(tmp_path: Path) -> None:
    service = core(tmp_path)
    create(service, A, "fact", 900_000, key="create-a")
    service.forget_item(A, "root", reason="retired", created_at=NOW)
    before = service.audit_item(A)
    with pytest.raises(NotFoundError):
        service.revise_item(
            idempotency_key="revise-deprecated", root_kref=A,
            content={"price": 997}, revision_reason="must not restore",
            old_confidence_ppm=900_000, new_confidence_ppm=500_000,
            created_at=NOW,
        )
    assert service.audit_item(A) == before


def test_revision_and_cascade_roll_back_together_on_invalid_llm_input(tmp_path: Path) -> None:
    service = core(tmp_path)
    seed_chain(service)
    before = service.get_item(A)
    with pytest.raises(ServiceError, match="llm_delta_ppm"):
        service.revise_item(
            idempotency_key="rollback", root_kref=A, content={"price": 3495},
            revision_reason="bad input", old_confidence_ppm=900_000,
            new_confidence_ppm=300_000,
            llm_inputs=[{"target_kref": B, "llm_delta_ppm": 2_000_000}],
            created_at=NOW,
        )
    after = service.get_item(A)
    assert after["lineage"] == before["lineage"]
    assert after["item"]["confidence_ppm"] == before["item"]["confidence_ppm"]


def test_restart_preserves_item_revision_and_proposal_identity(tmp_path: Path) -> None:
    db = tmp_path / "restart.sqlite3"
    first = CognitiveServiceCore(db, scope_id="profile-a")
    seed_chain(first)
    revision = first.revise_item(
        idempotency_key="restart-revision", root_kref=A,
        content={"price": 3495}, revision_reason="change",
        old_confidence_ppm=900_000, new_confidence_ppm=300_000,
        created_at=NOW,
    )
    expected_revision = revision["revision"]["revision_id"]
    expected_proposal = revision["cascade"]["proposals"][0]["proposal_id"]
    first.close()

    restarted = CognitiveServiceCore(db, scope_id="profile-a")
    item_a = restarted.get_item(A)
    item_b = restarted.get_item(B)
    assert item_a["current_revision"]["revision_id"] == expected_revision
    assert item_b["proposals"][0]["proposal_id"] == expected_proposal


def test_scope_isolation_on_shared_database(tmp_path: Path) -> None:
    db = tmp_path / "shared.sqlite3"
    one = CognitiveServiceCore(db, scope_id="one")
    two = CognitiveServiceCore(db, scope_id="two")
    create(one, A, "fact", 900_000, key="same-key", content={"profile": "one"})
    create(two, A, "fact", 300_000, key="same-key", content={"profile": "two"})
    assert one.get_item(A)["current_revision"]["content"] == {"profile": "one"}
    assert two.get_item(A)["current_revision"]["content"] == {"profile": "two"}


def test_get_search_list_forget_and_conservative_contract(tmp_path: Path) -> None:
    service = core(tmp_path)
    create(
        service, A, "fact", 800_000, key="create-price",
        content={"topic": "Zenith premium price"},
    )
    search_result = service.search_items("zenith price")[0]
    assert search_result["root_kref"] == A
    assert search_result["content"] == {"topic": "Zenith premium price"}
    listed = service.list_items()
    assert listed[0]["root_kref"] == A
    assert listed[0]["content"] == {"topic": "Zenith premium price"}
    forgotten = service.forget_item(
        A, "nonexistent proposition", reason="explicit contraction", created_at=NOW,
    )
    assert forgotten["deprecated"] is True
    assert forgotten["tags_removed"] == []
    retry = service.forget_item(
        A, "Zenith premium price", reason="different retry input", created_at=NOW,
    )
    assert retry == forgotten
    with pytest.raises(NotFoundError):
        service.get_item(A)
    audit = service.audit_item(A)
    assert audit["item"]["deprecated"] is True
    assert [event["event_type"] for event in audit["audit_events"]] == [
        "item_created", "item_forgotten",
    ]


def test_search_limit_and_revision_reason_are_validated(tmp_path: Path) -> None:
    service = core(tmp_path)
    create(service, A, "fact", 900_000, key="a")
    for invalid in (0, -1, 10_001, True):
        with pytest.raises(ServiceError, match="limit"):
            service.search_items("fact", limit=invalid)
    with pytest.raises(ServiceError, match="revision_reason is required"):
        service.revise_item(
            idempotency_key="missing-reason", root_kref=A,
            content={"price": 997}, revision_reason=" ",
            old_confidence_ppm=900_000, new_confidence_ppm=800_000,
            created_at=NOW,
        )


def test_database_and_parent_permissions_are_restrictive(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX permission bits are not available on Windows")
    database = tmp_path / "private-service" / "service.sqlite3"
    service = CognitiveServiceCore(database, scope_id="secure")
    assert database.parent.stat().st_mode & 0o777 == 0o700
    assert database.stat().st_mode & 0o777 == 0o600
    service.close()


def test_stale_revision_kind_and_cascade_bounds_are_rejected(tmp_path: Path) -> None:
    service = core(tmp_path)
    with pytest.raises(ServiceError, match="kind must be"):
        create(service, A, "note", 900_000, key="invalid-kind")
    create(service, A, "fact", 900_000, key="a")
    with pytest.raises(StaleWriteConflict):
        service.revise_item(
            idempotency_key="stale", root_kref=A, content={"price": 3495},
            revision_reason="stale client", old_confidence_ppm=800_000,
            new_confidence_ppm=300_000, created_at=NOW,
        )
    assert len(service.get_item(A)["lineage"]) == 1
    with pytest.raises(ServiceError, match="max_depth"):
        service.run_cascade(
            idempotency_key="depth", origin_kref=A,
            old_confidence_ppm=900_000, new_confidence_ppm=800_000,
            max_depth=101, created_at=NOW,
        )
    with pytest.raises(ServiceError, match="max_nodes"):
        service.run_cascade(
            idempotency_key="nodes", origin_kref=A,
            old_confidence_ppm=900_000, new_confidence_ppm=800_000,
            max_nodes=0, created_at=NOW,
        )


def test_audit_events_are_transactional_and_cover_mutations(tmp_path: Path) -> None:
    service = core(tmp_path)
    seed_chain(service)
    service.revise_item(
        idempotency_key="audit-revise", root_kref=A,
        content={"price": 3495}, revision_reason="new source",
        old_confidence_ppm=900_000, new_confidence_ppm=300_000,
        created_at=NOW,
    )
    events_a = [
        event["event_type"] for event in service.audit_item(A)["audit_events"]
    ]
    assert events_a == ["item_created", "cascade_created", "item_revised"]
    audit_a = service.audit_item(A)
    revised_event = audit_a["audit_events"][-1]
    assert revised_event["details"]["idempotency_key"] == "audit-revise"
    assert revised_event["details"]["revision_id"] == audit_a["lineage"][-1][
        "revision_id"
    ]
    events_b = [
        event["event_type"] for event in service.audit_item(B)["audit_events"]
    ]
    assert events_b == ["item_created", "dependency_declared"]


def test_dependency_exact_replay_is_response_and_audit_idempotent(
    tmp_path: Path,
) -> None:
    service = core(tmp_path)
    create(service, A, "fact", 900_000, key="a")
    create(service, B, "belief", 800_000, key="b")
    first = service.declare_dependency(
        B, A, strength_ppm=900_000, created_at=NOW
    )
    retry = service.declare_dependency(
        B, A, strength_ppm=900_000, created_at=NOW
    )
    assert retry == first
    assert [
        event["event_type"] for event in service.audit_item(B)["audit_events"]
    ].count("dependency_declared") == 1

    changed = service.declare_dependency(
        B, A, strength_ppm=700_000, created_at=NOW
    )
    assert changed["strength_ppm"] == 700_000
    assert [
        event["event_type"] for event in service.audit_item(B)["audit_events"]
    ].count("dependency_declared") == 2


def test_core_conviction_routing_precedes_delta(tmp_path: Path) -> None:
    service = core(tmp_path)
    create(service, A, "fact", 900_000, key="a")
    create(service, B, "belief", 800_000, key="b", core_conviction=True)
    service.declare_dependency(B, A, strength_ppm=1_000_000, created_at=NOW)
    cascade = service.run_cascade(
        idempotency_key="core-route", origin_kref=A,
        old_confidence_ppm=900_000, new_confidence_ppm=100_000,
        created_at=NOW,
    )
    assert cascade["proposals"][0]["route"] == "core_protected"


def test_reset_deletes_only_active_scope(tmp_path: Path) -> None:
    db = tmp_path / "reset.sqlite3"
    one = CognitiveServiceCore(db, scope_id="one")
    two = CognitiveServiceCore(db, scope_id="two")
    create(one, A, "fact", 900_000, key="a-one")
    create(two, A, "fact", 900_000, key="a-two")
    assert one.reset_scope()["items_deleted"] == 1
    with pytest.raises(NotFoundError):
        one.get_item(A)
    assert two.get_item(A)["item"]["root_kref"] == A
