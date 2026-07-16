"""Approved ingestion candidates must become idempotent Neo4j beliefs."""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def driver():
    from neo4j import AsyncGraphDatabase

    drv = AsyncGraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "atlasdev"),
        ),
    )
    try:
        await drv.verify_connectivity()
        yield drv
    finally:
        await drv.close()


async def test_approved_candidate_materializes_once_with_about_edge(driver, tmp_path):
    from atlas_core.ingestion import materialize_approved_candidates
    from atlas_core.trust import (
        CandidateClaim,
        EvidenceRef,
        HashChainedLedger,
        PromotionPolicy,
        QuarantineStore,
    )

    project = f"AtlasMaterialize_{uuid.uuid4().hex[:8]}"
    subject_kref = f"kref://{project}/Programs/zenith.program"
    quarantine = QuarantineStore(tmp_path / "candidates.db")
    ledger = HashChainedLedger(tmp_path / "ledger.db")
    upsert = quarantine.upsert_candidate(CandidateClaim(
        lane="atlas_vault",
        assertion_type="factual_assertion",
        subject_kref=subject_kref,
        predicate="pricing_belief",
        object_value="$3,495",
        confidence=0.95,
        evidence_ref=EvidenceRef(
            source="test",
            source_family="vault",
            kref=f"kref://{project}/Vault/pricing.note",
            timestamp="2026-07-16T00:00:00+00:00",
        ),
    ), auto_promote_enabled=False)
    promoted = PromotionPolicy(quarantine=quarantine, ledger=ledger).promote(
        upsert.candidate_id,
        actor_id="test.materializer",
    )
    assert promoted.promoted is True
    assert len(quarantine.list_approved()) == 1

    try:
        first = await materialize_approved_candidates(driver, quarantine)
        second = await materialize_approved_candidates(driver, quarantine)
        assert first.materialized == 1 and first.failed == 0
        assert second.materialized == 1 and second.failed == 0
        assert first.belief_krefs == second.belief_krefs

        async with driver.session() as session:
            result = await session.run(
                "MATCH (b:Belief {candidate_id: $cid})-[r:ABOUT]->"
                "(s:AtlasItem {kref: $subject}) "
                "RETURN count(b) AS beliefs, count(r) AS edges, "
                "b.ledger_event_id AS ledger_event_id, "
                "b.object_value AS object_value",
                cid=upsert.candidate_id,
                subject=subject_kref,
            )
            row = await result.single()
        assert row is not None
        assert row["beliefs"] == 1
        assert row["edges"] == 1
        assert row["ledger_event_id"] == promoted.ledger_event.event_id
        assert row["object_value"] == "$3,495"
    finally:
        async with driver.session() as session:
            await session.run(
                "MATCH (n) WHERE n.kref STARTS WITH $prefix DETACH DELETE n",
                prefix=f"kref://{project}/",
            )
