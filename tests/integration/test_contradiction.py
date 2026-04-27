"""Integration tests for type-aware contradiction detection.

Per Ripple Spec § 5: each entity type has its own contradiction rules.
Tests cover all four detectors against real Neo4j graph state.
"""

import os
import uuid

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def neo4j_uri() -> str:
    return os.environ.get("NEO4J_URI", "bolt://localhost:7687")


@pytest.fixture(scope="module")
def neo4j_auth() -> tuple[str, str]:
    return (
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "atlasdev"),
    )


@pytest.fixture
async def driver(neo4j_uri, neo4j_auth):
    pytest.importorskip("neo4j")
    from neo4j import AsyncGraphDatabase

    user, password = neo4j_auth
    drv = AsyncGraphDatabase.driver(neo4j_uri, auth=(user, password))
    try:
        await drv.verify_connectivity()
        yield drv
    finally:
        await drv.close()


@pytest.fixture
def ns() -> str:
    return f"AtlasContraTest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def cleanup(driver, ns):
    cypher = "MATCH (n) WHERE n.kref STARTS WITH $prefix DETACH DELETE n"
    prefix = f"kref://{ns}/"
    async with driver.session() as session:
        await session.run(cypher, prefix=prefix)
    yield
    async with driver.session() as session:
        await session.run(cypher, prefix=prefix)


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def make_belief(driver, ns: str, item: str, confidence: float, hypothesis: str = "") -> str:
    kref = f"kref://{ns}/Beliefs/{item}.belief"
    cypher = """
    MERGE (n:AtlasItem {kref: $kref})
    SET n.deprecated = false,
        n.confidence_score = $conf,
        n.hypothesis = $hyp
    """
    async with driver.session() as session:
        await session.run(cypher, kref=kref, conf=confidence, hyp=hypothesis)
    return kref


async def make_decision(driver, ns: str, item: str) -> str:
    kref = f"kref://{ns}/Decisions/{item}.decision"
    cypher = """
    MERGE (n:AtlasItem {kref: $kref})
    SET n.deprecated = false
    """
    async with driver.session() as session:
        await session.run(cypher, kref=kref)
    return kref


async def make_commitment(
    driver, ns: str, item: str, owner: str, description: str, deadline: str
) -> str:
    kref = f"kref://{ns}/Commitments/{item}.commitment"
    cypher = """
    MERGE (n:AtlasItem {kref: $kref})
    SET n.deprecated = false,
        n.status = 'open',
        n.owner_kref = $owner,
        n.description = $desc,
        n.deadline = $deadline
    """
    async with driver.session() as session:
        await session.run(
            cypher, kref=kref, owner=owner, desc=description, deadline=deadline
        )
    return kref


async def link(driver, source: str, edge_type: str, target: str) -> None:
    cypher = (
        "MATCH (s {kref: $source}) "
        "MATCH (t {kref: $target}) "
        f"MERGE (s)-[:{edge_type}]->(t)"
    )
    async with driver.session() as session:
        await session.run(cypher, source=source, target=target)


def make_proposal(target_kref: str, new_conf: float, old_conf: float = 0.5):
    """Build a fake proposal pointing at a node — we only need the target_kref
    and the new confidence for contradiction detection."""
    from atlas_core.ripple import ReassessmentProposal

    return ReassessmentProposal(
        target_kref=target_kref,
        old_confidence=old_conf,
        new_confidence=new_conf,
        components={},
        upstream_kref="",
        depth=1,
    )


# ─── StrategicBelief conflict ────────────────────────────────────────────────


class TestStrategicBeliefConflict:
    async def test_two_high_conf_beliefs_with_contradicts_edge(self, driver, ns):
        from atlas_core.ripple import (
            ContradictionCategory,
            Severity,
            detect_contradictions,
        )

        a = await make_belief(driver, ns, "a", 0.85, "premium pricing wins")
        b = await make_belief(driver, ns, "b", 0.80, "market is softening")
        await link(driver, a, "CONTRADICTS", b)

        result = await detect_contradictions(driver, [make_proposal(a, 0.85)])

        assert len(result) == 1
        assert result[0].category == ContradictionCategory.STRATEGIC_BELIEF_CONFLICT
        assert result[0].severity == Severity.MEDIUM
        assert result[0].opposed_kref == b

    async def test_both_above_high_severity_threshold_escalates(self, driver, ns):
        from atlas_core.ripple import Severity, detect_contradictions

        a = await make_belief(driver, ns, "a", 0.92)
        b = await make_belief(driver, ns, "b", 0.90)
        await link(driver, a, "CONTRADICTS", b)

        result = await detect_contradictions(driver, [make_proposal(a, 0.92)])
        assert len(result) == 1
        assert result[0].severity == Severity.HIGH

    async def test_proposal_below_floor_no_contradiction(self, driver, ns):
        from atlas_core.ripple import detect_contradictions

        a = await make_belief(driver, ns, "a", 0.5, "tentative")  # below 0.7 floor
        b = await make_belief(driver, ns, "b", 0.85)
        await link(driver, a, "CONTRADICTS", b)

        # Proposal pegs new_conf at 0.5, below the strategic-belief floor
        result = await detect_contradictions(driver, [make_proposal(a, 0.5)])
        assert len(result) == 0

    async def test_opposed_below_floor_no_contradiction(self, driver, ns):
        from atlas_core.ripple import detect_contradictions

        a = await make_belief(driver, ns, "a", 0.85)
        b = await make_belief(driver, ns, "b", 0.4)  # below floor
        await link(driver, a, "CONTRADICTS", b)

        result = await detect_contradictions(driver, [make_proposal(a, 0.85)])
        assert len(result) == 0

    async def test_no_contradicts_edge_no_detection(self, driver, ns):
        from atlas_core.ripple import detect_contradictions

        a = await make_belief(driver, ns, "a", 0.85)
        await make_belief(driver, ns, "b", 0.80)
        # No CONTRADICTS edge

        result = await detect_contradictions(driver, [make_proposal(a, 0.85)])
        assert len(result) == 0


# ─── Decision unsupported ────────────────────────────────────────────────────


class TestDecisionUnsupported:
    async def test_decision_with_unsupported_belief(self, driver, ns):
        from atlas_core.ripple import (
            ContradictionCategory,
            Severity,
            detect_contradictions,
        )

        decision = await make_decision(driver, ns, "q3_pricing")
        weak_belief = await make_belief(driver, ns, "weak", 0.3, "softening market")
        await link(driver, decision, "SUPPORTS", weak_belief)

        result = await detect_contradictions(driver, [make_proposal(decision, 0.9)])

        assert len(result) == 1
        assert result[0].category == ContradictionCategory.DECISION_UNSUPPORTED
        assert result[0].severity == Severity.HIGH
        assert result[0].opposed_kref == weak_belief

    async def test_decision_with_supported_belief_ok(self, driver, ns):
        from atlas_core.ripple import detect_contradictions

        decision = await make_decision(driver, ns, "well_supported")
        strong = await make_belief(driver, ns, "strong", 0.85)
        await link(driver, decision, "SUPPORTS", strong)

        result = await detect_contradictions(driver, [make_proposal(decision, 0.9)])
        assert len(result) == 0


# ─── Commitment deadline conflict ────────────────────────────────────────────


class TestCommitmentDeadlineConflict:
    async def test_two_open_commitments_different_deadlines(self, driver, ns):
        from atlas_core.ripple import (
            ContradictionCategory,
            Severity,
            detect_contradictions,
        )

        owner = f"kref://{ns}/People/rich.person"
        c1 = await make_commitment(
            driver, ns, "ship_v1", owner, "Ship Atlas v1", "2026-05-01"
        )
        c2 = await make_commitment(
            driver, ns, "ship_v1_alt", owner, "Ship Atlas v1", "2026-06-15"
        )

        result = await detect_contradictions(driver, [make_proposal(c1, 0.9)])

        assert len(result) == 1
        assert result[0].category == ContradictionCategory.COMMITMENT_DEADLINE_CONFLICT
        assert result[0].severity == Severity.MEDIUM
        assert result[0].opposed_kref == c2

    async def test_different_descriptions_no_conflict(self, driver, ns):
        from atlas_core.ripple import detect_contradictions

        owner = f"kref://{ns}/People/rich.person"
        c1 = await make_commitment(
            driver, ns, "c1", owner, "Ship Atlas v1", "2026-05-01"
        )
        await make_commitment(
            driver, ns, "c2", owner, "Different commitment entirely", "2026-06-15"
        )

        result = await detect_contradictions(driver, [make_proposal(c1, 0.9)])
        assert len(result) == 0

    async def test_same_deadline_no_conflict(self, driver, ns):
        from atlas_core.ripple import detect_contradictions

        owner = f"kref://{ns}/People/rich.person"
        c1 = await make_commitment(
            driver, ns, "c1", owner, "Ship Atlas v1", "2026-05-01"
        )
        await make_commitment(
            driver, ns, "c2", owner, "Ship Atlas v1", "2026-05-01"
        )

        result = await detect_contradictions(driver, [make_proposal(c1, 0.9)])
        assert len(result) == 0


# ─── Multi-proposal aggregation ──────────────────────────────────────────────


class TestMultiProposalAggregation:
    async def test_multiple_proposals_aggregate(self, driver, ns):
        from atlas_core.ripple import detect_contradictions

        # Set up two independent contradictions
        a1 = await make_belief(driver, ns, "a1", 0.85)
        a2 = await make_belief(driver, ns, "a2", 0.85)
        await link(driver, a1, "CONTRADICTS", a2)

        decision = await make_decision(driver, ns, "d1")
        weak = await make_belief(driver, ns, "weak", 0.3)
        await link(driver, decision, "SUPPORTS", weak)

        proposals = [make_proposal(a1, 0.85), make_proposal(decision, 0.9)]
        result = await detect_contradictions(driver, proposals)

        # One strategic conflict + one decision_unsupported = 2 contradictions
        assert len(result) == 2
        categories = {c.category.value for c in result}
        assert "strategic_belief_conflict" in categories
        assert "decision_unsupported" in categories

    async def test_deprecated_target_skipped(self, driver, ns):
        from atlas_core.ripple import detect_contradictions

        a = await make_belief(driver, ns, "a", 0.85)
        b = await make_belief(driver, ns, "b", 0.85)
        await link(driver, a, "CONTRADICTS", b)

        # Mark a deprecated
        async with driver.session() as session:
            await session.run("MATCH (n {kref: $k}) SET n.deprecated = true", k=a)

        result = await detect_contradictions(driver, [make_proposal(a, 0.85)])
        assert len(result) == 0
