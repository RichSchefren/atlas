"""Integration tests for the decision-lineage subsystem.

Spec: PHASE-5-AND-BEYOND.md § 1.5
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
def ns():
    return f"LineageTest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def cleanup(driver, ns):
    cypher = "MATCH (n) WHERE n.kref STARTS WITH $p DETACH DELETE n"
    prefix = f"kref://{ns}/"
    async with driver.session() as s:
        await s.run(cypher, p=prefix)
    yield
    async with driver.session() as s:
        await s.run(cypher, p=prefix)


# ─── Walker ─────────────────────────────────────────────────────────────────


class TestLineageWalker:
    async def test_decision_with_no_supports_returns_empty_chain(
        self, driver, ns,
    ):
        from atlas_core.lineage import walk_decision_chain

        d_kref = f"kref://{ns}/Decisions/orphan.decision"
        async with driver.session() as s:
            await s.run(
                "MERGE (d:Decision:AtlasItem {kref: $k}) "
                "SET d.description = 'Orphan decision'",
                k=d_kref,
            )
        walk = await walk_decision_chain(driver, d_kref)
        assert walk.decision_kref == d_kref
        assert walk.chain == []
        assert walk.truncated is False

    async def test_one_hop_chain(self, driver, ns):
        from atlas_core.lineage import walk_decision_chain

        d_kref = f"kref://{ns}/Decisions/d1.decision"
        b_kref = f"kref://{ns}/Beliefs/b1.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (d:Decision:AtlasItem {kref: $dk}) "
                "MERGE (b:Belief:AtlasItem {kref: $bk}) "
                "SET b.text = 'b1 text', b.confidence_score = 0.85, "
                "    b.deprecated = false "
                "MERGE (d)-[:SUPPORTS {strength: 0.9}]->(b)",
                dk=d_kref, bk=b_kref,
            )
        walk = await walk_decision_chain(driver, d_kref)
        assert len(walk.chain) == 1
        assert walk.chain[0].kref == b_kref
        assert walk.chain[0].text == "b1 text"
        assert walk.chain[0].confidence == 0.85
        assert walk.chain[0].depth == 1
        assert walk.chain[0].strength_to_parent == 0.9

    async def test_two_hop_chain_orders_by_depth(self, driver, ns):
        from atlas_core.lineage import walk_decision_chain

        d_kref = f"kref://{ns}/Decisions/d2.decision"
        b1_kref = f"kref://{ns}/Beliefs/b_outer.belief"
        b2_kref = f"kref://{ns}/Beliefs/b_inner.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (d:Decision:AtlasItem {kref: $dk}) "
                "MERGE (b1:Belief:AtlasItem {kref: $b1}) "
                "  SET b1.text = 'outer', b1.confidence_score = 0.8, b1.deprecated = false "
                "MERGE (b2:Belief:AtlasItem {kref: $b2}) "
                "  SET b2.text = 'inner', b2.confidence_score = 0.7, b2.deprecated = false "
                "MERGE (d)-[:SUPPORTS {strength: 0.9}]->(b1) "
                "MERGE (b1)-[:SUPPORTS {strength: 0.6}]->(b2)",
                dk=d_kref, b1=b1_kref, b2=b2_kref,
            )
        walk = await walk_decision_chain(driver, d_kref)
        assert len(walk.chain) == 2
        # Outer (depth 1) first, then inner (depth 2)
        assert walk.chain[0].depth == 1
        assert walk.chain[1].depth == 2
        assert walk.weakest_link_confidence == 0.7

    async def test_load_bearing_weakened_flag(self, driver, ns):
        from atlas_core.lineage import walk_decision_chain

        d_kref = f"kref://{ns}/Decisions/d3.decision"
        b_kref = f"kref://{ns}/Beliefs/b_weak.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (d:Decision:AtlasItem {kref: $dk}) "
                "MERGE (b:Belief:AtlasItem {kref: $bk}) "
                "  SET b.text = 'weak', b.confidence_score = 0.3, b.deprecated = false "
                "MERGE (d)-[:SUPPORTS {strength: 0.9}]->(b)",
                dk=d_kref, bk=b_kref,
            )
        walk = await walk_decision_chain(driver, d_kref)
        # belief at 0.3 < DECISION_SUPPORT_FLOOR (0.5) AND strength 0.9 ≥ 0.7
        assert walk.is_load_bearing_weakened is True


# ─── Contradiction detector ─────────────────────────────────────────────────


class TestLineageContradictionDetector:
    async def test_no_weakened_beliefs_returns_empty(self, driver):
        from atlas_core.lineage import detect_lineage_contradictions

        result = await detect_lineage_contradictions(driver, [])
        assert result == []

    async def test_high_strength_weakened_belief_surfaces(self, driver, ns):
        from atlas_core.lineage import detect_lineage_contradictions

        d_kref = f"kref://{ns}/Decisions/d_critical.decision"
        b_kref = f"kref://{ns}/Beliefs/b_critical.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (d:Decision:AtlasItem {kref: $dk}) "
                "  SET d.description = 'Hire 2 roasters' "
                "MERGE (b:Belief:AtlasItem {kref: $bk}) "
                "  SET b.text = 'capacity is constrained', "
                "      b.confidence_score = 0.3, b.deprecated = false "
                "MERGE (d)-[:SUPPORTS {strength: 0.9}]->(b)",
                dk=d_kref, bk=b_kref,
            )
        contras = await detect_lineage_contradictions(driver, [b_kref])
        assert len(contras) == 1
        c = contras[0]
        assert c.decision_kref == d_kref
        assert c.weakened_belief_kref == b_kref
        assert c.severity == "high"
        assert c.new_belief_confidence == 0.3

    async def test_low_strength_edge_does_not_surface(self, driver, ns):
        from atlas_core.lineage import detect_lineage_contradictions

        d_kref = f"kref://{ns}/Decisions/d_loose.decision"
        b_kref = f"kref://{ns}/Beliefs/b_loose.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (d:Decision:AtlasItem {kref: $dk}) "
                "MERGE (b:Belief:AtlasItem {kref: $bk}) "
                "  SET b.text = 't', b.confidence_score = 0.3, b.deprecated = false "
                "MERGE (d)-[:SUPPORTS {strength: 0.4}]->(b)",  # below 0.5 floor
                dk=d_kref, bk=b_kref,
            )
        contras = await detect_lineage_contradictions(driver, [b_kref])
        assert contras == []
