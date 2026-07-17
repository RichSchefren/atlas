"""Idempotent bridge from ledger-approved candidates to the Neo4j graph.

The ledger remains the canonical trust decision.  This module projects that
decision into Neo4j so the open-source ingest -> adjudicate path actually
produces graph beliefs.  A failed graph write never erases ledger approval;
rerunning the materializer safely retries the same candidate without creating
duplicates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from atlas_core.revision.agm import revise
from atlas_core.revision.uri import Kref

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from atlas_core.ripple.engine import RippleEngine
    from atlas_core.trust import QuarantineStore


@dataclass
class MaterializationReport:
    attempted: int = 0
    materialized: int = 0
    failed: int = 0
    ripple_attempted: int = 0
    ripple_completed: int = 0
    ripple_failed: int = 0
    belief_krefs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _MaterializedCandidate:
    belief_kref: str
    previous_confidence: float
    ripple_ledger_event_id: str | None
    is_current: bool


def belief_kref_for_candidate(candidate: dict[str, Any]) -> str:
    """Mint one stable belief root per subject, predicate, and scope.

    Candidate object values deliberately do not participate in this identity:
    a changed value is an AGM revision of the same logical belief.
    """
    subject = Kref.parse(candidate["subject_kref"]).root_kref()
    identity = json.dumps(
        [subject.to_string(), candidate["predicate"], candidate["scope"]],
        sort_keys=True,
        separators=(",", ":"),
    )
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return (
        f"kref://{subject.project}/IngestedBeliefs/"
        f"{subject.item}_{suffix}.belief"
    )


async def materialize_candidate(
    driver: AsyncDriver,
    candidate: dict[str, Any],
) -> str:
    """Project one approved candidate as an immutable AGM belief revision."""
    state = await _materialize_candidate_state(driver, candidate)
    return state.belief_kref


async def _project_current_revision(
    driver: AsyncDriver,
    *,
    candidate: dict[str, Any],
    subject: Kref,
    belief_kref: str,
    revision_kref: str,
    previous_confidence: float,
    evidence_json: str,
    now: str,
) -> str:
    """Update the queryable current-state projection for an AGM revision."""
    cypher = """
    MERGE (subject:AtlasItem {kref: $subject_kref})
      ON CREATE SET subject.created_at = $now,
                    subject.kind = $subject_kind,
                    subject.deprecated = false
    WITH subject
    MATCH (belief:AtlasItem {root_kref: $belief_kref})
    SET belief:Belief,
        belief.kref = $belief_kref,
        belief.materialized_at = coalesce(belief.materialized_at, $now),
        belief.deprecated = false,
        belief.candidate_id = $candidate_id,
        belief.current_revision_kref = $revision_kref,
        belief.predicate = $predicate,
        belief.object_value = $object_value,
        belief.text = $text,
        belief.assertion_type = $assertion_type,
        belief.confidence_score = $confidence,
        belief.trust_score = $trust_score,
        belief.scope = $scope,
        belief.lane = $lane,
        belief.ledger_event_id = $ledger_event_id,
        belief.evidence_refs_json = $evidence_json,
        belief.last_materialized_at = $now
    WITH subject, belief
    MATCH (:AtlasTag {name: 'current', root_kref: $belief_kref})
          -[:POINTS_TO]->(revision:AtlasRevision {kref: $revision_kref})
    SET revision.ledger_event_id = $ledger_event_id,
        revision.candidate_id = $candidate_id,
        revision.confidence_score = $confidence,
        revision.previous_confidence = $previous_confidence
    MERGE (belief)-[about:ABOUT]->(subject)
      ON CREATE SET about.created_at = $now
    RETURN belief.kref AS belief_kref
    """
    async with driver.session() as session:
        result = await session.run(
            cypher,
            subject_kref=subject.root_kref().to_string(),
            subject_kind=subject.kind,
            belief_kref=belief_kref,
            revision_kref=revision_kref,
            candidate_id=candidate["candidate_id"],
            predicate=candidate["predicate"],
            object_value=candidate["object_value"],
            text=f"{candidate['predicate']}: {candidate['object_value']}",
            assertion_type=candidate["assertion_type"],
            confidence=float(candidate["confidence"]),
            trust_score=float(candidate["trust_score"]),
            scope=candidate["scope"],
            lane=candidate["lane"],
            ledger_event_id=candidate["ledger_event_id"],
            evidence_json=evidence_json,
            previous_confidence=previous_confidence,
            now=now,
        )
        record = await result.single()
    if record is None:
        raise RuntimeError(f"Neo4j returned no belief for {candidate['candidate_id']}")
    return str(record["belief_kref"])


async def _materialize_candidate_state(
    driver: AsyncDriver,
    candidate: dict[str, Any],
) -> _MaterializedCandidate:
    """Apply an idempotent AGM revision and return its Ripple transition."""
    if candidate.get("status") != "approved" or not candidate.get("ledger_event_id"):
        raise ValueError("candidate must be ledger-approved before graph materialization")

    subject = Kref.parse(candidate["subject_kref"])
    belief_kref = belief_kref_for_candidate(candidate)
    now = datetime.now(timezone.utc).isoformat()
    evidence_json = candidate.get("evidence_refs_json") or "[]"
    evidence = json.loads(evidence_json)

    ledger_marker = f'"ledger_event_id":{json.dumps(candidate["ledger_event_id"])}'
    state_cypher = """
    OPTIONAL MATCH (existing:AtlasRevision {root_kref: $belief_kref})
    WHERE existing.ledger_event_id = $ledger_event_id
       OR existing.content_json CONTAINS $ledger_marker
    OPTIONAL MATCH (existing)-[:SUPERSEDES]->(prior:AtlasRevision)
    OPTIONAL MATCH (root:AtlasItem {root_kref: $belief_kref})
    OPTIONAL MATCH (:AtlasTag {name: 'current', root_kref: $belief_kref})
                   -[:POINTS_TO]->(current:AtlasRevision)
    RETURN existing.kref AS existing_revision_kref,
           existing.previous_confidence AS existing_previous_confidence,
           prior.content_json AS prior_content_json,
           current.kref AS current_revision_kref,
           current.content_json AS current_content_json,
           root.ripple_ledger_event_id AS ripple_ledger_event_id
    """
    async with driver.session() as session:
        result = await session.run(
            state_cypher,
            belief_kref=belief_kref,
            ledger_event_id=candidate["ledger_event_id"],
            ledger_marker=ledger_marker,
        )
        state_record = await result.single()
    if state_record is None:
        raise RuntimeError(f"Neo4j returned no state for {candidate['candidate_id']}")

    existing_revision_kref = state_record["existing_revision_kref"]
    if existing_revision_kref is not None:
        previous_confidence = state_record["existing_previous_confidence"]
        if previous_confidence is None:
            prior_content_json = state_record["prior_content_json"]
            prior_content = (
                json.loads(prior_content_json) if prior_content_json else {}
            )
            previous_confidence = prior_content.get("confidence", 0.0)
        previous_confidence = float(previous_confidence)
        is_current = (
            existing_revision_kref == state_record["current_revision_kref"]
        )
        if is_current:
            await _project_current_revision(
                driver,
                candidate=candidate,
                subject=subject,
                belief_kref=belief_kref,
                revision_kref=str(existing_revision_kref),
                previous_confidence=previous_confidence,
                evidence_json=evidence_json,
                now=now,
            )
        return _MaterializedCandidate(
            belief_kref=belief_kref,
            previous_confidence=previous_confidence,
            ripple_ledger_event_id=state_record["ripple_ledger_event_id"],
            is_current=is_current,
        )

    current_content_json = state_record["current_content_json"]
    current_content = (
        json.loads(current_content_json) if current_content_json else {}
    )
    previous_confidence = float(current_content.get("confidence", 0.0))
    content = {
        "assertion_type": candidate["assertion_type"],
        "candidate_id": candidate["candidate_id"],
        "confidence": float(candidate["confidence"]),
        "lane": candidate["lane"],
        "ledger_event_id": candidate["ledger_event_id"],
        "object_value": candidate["object_value"],
        "predicate": candidate["predicate"],
        "scope": candidate["scope"],
        "trust_score": float(candidate["trust_score"]),
    }
    outcome = await revise(
        driver,
        Kref.parse(belief_kref),
        content,
        revision_reason=(
            f"ledger promotion {candidate['ledger_event_id']} "
            f"for candidate {candidate['candidate_id']}"
        ),
        evidence={"refs": evidence},
        actor="atlas.materializer",
    )

    projected_kref = await _project_current_revision(
        driver,
        candidate=candidate,
        subject=subject,
        belief_kref=belief_kref,
        revision_kref=outcome.new_revision_kref.to_string(),
        previous_confidence=previous_confidence,
        evidence_json=evidence_json,
        now=now,
    )
    return _MaterializedCandidate(
        belief_kref=projected_kref,
        previous_confidence=previous_confidence,
        ripple_ledger_event_id=state_record["ripple_ledger_event_id"],
        is_current=True,
    )


async def _mark_ripple_completed(
    driver: AsyncDriver,
    *,
    belief_kref: str,
    ledger_event_id: str,
) -> None:
    """Record the ledger version whose Ripple cascade completed."""
    async with driver.session() as session:
        await session.run(
            """
            MATCH (belief:Belief {root_kref: $belief_kref})
            MATCH (:AtlasTag {name: 'current', root_kref: $belief_kref})
                  -[:POINTS_TO]->(revision:AtlasRevision)
            WHERE revision.ledger_event_id = $ledger_event_id
            SET belief.ripple_ledger_event_id = $ledger_event_id,
                belief.ripple_completed_at = $now
            """,
            belief_kref=belief_kref,
            ledger_event_id=ledger_event_id,
            now=datetime.now(timezone.utc).isoformat(),
        )


async def materialize_approved_candidates(
    driver: AsyncDriver,
    quarantine: QuarantineStore,
    *,
    ripple_engine: RippleEngine | None = None,
) -> MaterializationReport:
    """Project approved candidates and run Ripple once per ledger event.

    Graph projection and Ripple are recoverable, at-least-once steps. The graph
    records the ledger event whose cascade completed, so routine materializer
    retries do not emit duplicate cascades.
    """
    report = MaterializationReport()
    for candidate in quarantine.list_approved():
        report.attempted += 1
        try:
            state = await _materialize_candidate_state(driver, candidate)
        except Exception as exc:
            report.failed += 1
            report.errors.append(
                f"{candidate['candidate_id']}: {type(exc).__name__}: {exc}"
            )
            continue
        report.materialized += 1
        report.belief_krefs.append(state.belief_kref)

        ledger_event_id = str(candidate["ledger_event_id"])
        if (
            ripple_engine is None
            or not state.is_current
            or state.ripple_ledger_event_id == ledger_event_id
        ):
            continue

        report.ripple_attempted += 1
        try:
            cascade = await ripple_engine.propagate(
                state.belief_kref,
                old_confidence=state.previous_confidence,
                new_confidence=float(candidate["confidence"]),
                belief_text=(
                    f"{candidate['predicate']}: {candidate['object_value']}"
                ),
            )
            if not cascade.succeeded:
                raise RuntimeError(cascade.error or "Ripple cascade failed")
            await _mark_ripple_completed(
                driver,
                belief_kref=state.belief_kref,
                ledger_event_id=ledger_event_id,
            )
        except Exception as exc:
            report.ripple_failed += 1
            report.errors.append(
                f"{candidate['candidate_id']}: Ripple "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        report.ripple_completed += 1
    return report
