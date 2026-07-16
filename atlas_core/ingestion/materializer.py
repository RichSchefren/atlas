"""Idempotent bridge from ledger-approved candidates to the Neo4j graph.

The ledger remains the canonical trust decision.  This module projects that
decision into Neo4j so the open-source ingest -> adjudicate path actually
produces graph beliefs.  A failed graph write never erases ledger approval;
rerunning the materializer safely retries the same candidate without creating
duplicates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from atlas_core.migrations.schema import ensure_schema
from atlas_core.revision.uri import Kref

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from atlas_core.trust import QuarantineStore


@dataclass
class MaterializationReport:
    attempted: int = 0
    materialized: int = 0
    failed: int = 0
    belief_krefs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def belief_kref_for_candidate(candidate: dict[str, Any]) -> str:
    """Mint one stable belief kref per deduplicated candidate."""
    subject = Kref.parse(candidate["subject_kref"])
    return (
        f"kref://{subject.project}/IngestedBeliefs/"
        f"candidate_{candidate['candidate_id']}.belief"
    )


async def materialize_candidate(
    driver: AsyncDriver,
    candidate: dict[str, Any],
) -> str:
    """Upsert one approved candidate as ``(:Belief)-[:ABOUT]->(:AtlasItem)``."""
    if candidate.get("status") != "approved" or not candidate.get("ledger_event_id"):
        raise ValueError("candidate must be ledger-approved before graph materialization")

    subject = Kref.parse(candidate["subject_kref"])
    belief_kref = belief_kref_for_candidate(candidate)
    now = datetime.now(timezone.utc).isoformat()
    evidence_json = candidate.get("evidence_refs_json") or "[]"
    # Validate before sending the serialized evidence into Neo4j.
    json.loads(evidence_json)

    cypher = """
    MERGE (subject:AtlasItem {kref: $subject_kref})
      ON CREATE SET subject.created_at = $now,
                    subject.kind = $subject_kind,
                    subject.deprecated = false
    MERGE (belief:AtlasItem:Belief {candidate_id: $candidate_id})
      ON CREATE SET belief.kref = $belief_kref,
                    belief.created_at = $now,
                    belief.materialized_at = $now,
                    belief.deprecated = false
    SET belief.predicate = $predicate,
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
            now=now,
        )
        record = await result.single()
    if record is None:
        raise RuntimeError(f"Neo4j returned no belief for {candidate['candidate_id']}")
    return str(record["belief_kref"])


async def materialize_approved_candidates(
    driver: AsyncDriver,
    quarantine: QuarantineStore,
) -> MaterializationReport:
    """Project every approved candidate; continue and report per-item failures."""
    # Guarantee the belief-node uniqueness constraints exist before any MERGE,
    # so concurrent materialization can never mint duplicate belief nodes.
    await ensure_schema(driver)

    report = MaterializationReport()
    for candidate in quarantine.list_approved():
        report.attempted += 1
        try:
            belief_kref = await materialize_candidate(driver, candidate)
        except Exception as exc:
            report.failed += 1
            report.errors.append(
                f"{candidate['candidate_id']}: {type(exc).__name__}: {exc}"
            )
            continue
        report.materialized += 1
        report.belief_krefs.append(belief_kref)
    return report
