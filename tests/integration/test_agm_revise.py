"""Integration tests for AGM revision operators against live Neo4j.

Verifies AGM postulates K*2-K*5 (Success, Inclusion, Vacuity, Consistency)
hold operationally. The full 49-scenario formal compliance suite lives at
benchmarks/agm_compliance_runner.py (Task #21).

Each test uses a unique root_kref namespace and cleans up after itself so
tests can run in any order.
"""

import json
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
def fresh_kref(driver) -> str:
    """Each test gets a unique root_kref namespace to prevent cross-test pollution."""
    test_id = uuid.uuid4().hex[:8]
    return f"kref://AtlasTest/StrategicBeliefs/test_{test_id}.belief"


@pytest.fixture(autouse=True)
async def cleanup_test_namespace(driver, fresh_kref):
    """Delete everything under the test root_kref before AND after the test."""
    cleanup = """
    MATCH (n) WHERE n.root_kref = $root_kref OR n.kref = $root_kref
    DETACH DELETE n
    """
    async with driver.session() as session:
        await session.run(cleanup, root_kref=fresh_kref)
    yield
    async with driver.session() as session:
        await session.run(cleanup, root_kref=fresh_kref)


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _get_belief_at_tag(driver, root_kref: str, tag: str = "current") -> dict | None:
    """Fetch the content currently tagged at root_kref. Returns parsed dict or None."""
    cypher = """
    MATCH (tag:AtlasTag {name: $tag, root_kref: $root_kref})-[:POINTS_TO]->(rev:AtlasRevision)
    RETURN rev.content_json AS content_json, rev.kref AS kref
    """
    async with driver.session() as session:
        result = await session.run(cypher, tag=tag, root_kref=root_kref)
        record = await result.single()
    if record is None:
        return None
    return {"content": json.loads(record["content_json"]), "kref": record["kref"]}


async def _count_supersedes(driver, root_kref: str) -> int:
    """Count SUPERSEDES edges within this item's revision chain."""
    cypher = """
    MATCH (a:AtlasRevision {root_kref: $root_kref})-[s:SUPERSEDES]->(b:AtlasRevision)
    RETURN count(s) AS n
    """
    async with driver.session() as session:
        result = await session.run(cypher, root_kref=root_kref)
        record = await result.single()
    return record["n"]


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestAGMReviseSuccess:
    """K*2 Success: A ∈ B * A."""

    async def test_first_revision_creates_node_and_tag(self, driver, fresh_kref):
        from atlas_core.revision import Kref, revise

        outcome = await revise(
            driver,
            Kref.parse(fresh_kref),
            new_content={"hypothesis": "premium pricing wins", "confidence": 0.6},
            revision_reason="initial assertion",
        )

        assert outcome.was_first_revision is True
        assert outcome.superseded_kref is None
        assert outcome.tag_updated == "current"

        # K*2: A ∈ B(τ')
        retrieved = await _get_belief_at_tag(driver, fresh_kref)
        assert retrieved is not None
        assert retrieved["content"]["hypothesis"] == "premium pricing wins"
        assert retrieved["content"]["confidence"] == 0.6

    async def test_second_revision_supersedes_first(self, driver, fresh_kref):
        from atlas_core.revision import Kref, revise

        await revise(
            driver, Kref.parse(fresh_kref),
            new_content={"hypothesis": "v1", "confidence": 0.6},
            revision_reason="initial",
        )
        outcome = await revise(
            driver, Kref.parse(fresh_kref),
            new_content={"hypothesis": "v2", "confidence": 0.8},
            revision_reason="updated after evidence",
        )

        assert outcome.was_first_revision is False
        assert outcome.superseded_kref is not None

        # K*2: new content present at tag
        retrieved = await _get_belief_at_tag(driver, fresh_kref)
        assert retrieved["content"]["hypothesis"] == "v2"

        # SUPERSEDES edge created
        assert await _count_supersedes(driver, fresh_kref) == 1


class TestAGMReviseConsistency:
    """K*5 Consistency: τ' references only the new revision (not the old)."""

    async def test_old_revision_no_longer_tag_referenced(self, driver, fresh_kref):
        from atlas_core.revision import Kref, revise

        await revise(
            driver, Kref.parse(fresh_kref),
            new_content={"hypothesis": "old", "confidence": 0.5},
            revision_reason="v1",
        )
        await revise(
            driver, Kref.parse(fresh_kref),
            new_content={"hypothesis": "new", "confidence": 0.9},
            revision_reason="v2",
        )

        # Verify only one revision is tagged at 'current'
        cypher = """
        MATCH (t:AtlasTag {name: 'current', root_kref: $root_kref})-[:POINTS_TO]->(rev)
        RETURN count(rev) AS n
        """
        async with driver.session() as session:
            result = await session.run(cypher, root_kref=fresh_kref)
            record = await result.single()
        assert record["n"] == 1

        # The 'old' revision still exists in the graph (provenance preserved)
        # but is no longer tag-referenced
        cypher2 = """
        MATCH (rev:AtlasRevision {root_kref: $root_kref})
        WHERE rev.content_json CONTAINS '"hypothesis":"old"'
        RETURN count(rev) AS n
        """
        async with driver.session() as session:
            result = await session.run(cypher2, root_kref=fresh_kref)
            record = await result.single()
        assert record["n"] == 1


class TestAGMReviseChain:
    """Multi-revision chains preserve all postulates and form a SUPERSEDES chain."""

    async def test_three_revision_chain(self, driver, fresh_kref):
        from atlas_core.revision import Kref, revise

        for i, hypothesis in enumerate(["v1", "v2", "v3"], start=1):
            await revise(
                driver, Kref.parse(fresh_kref),
                new_content={"hypothesis": hypothesis, "confidence": 0.5 + i * 0.1},
                revision_reason=f"revision-{i}",
            )

        # Two SUPERSEDES edges (v2->v1, v3->v2)
        assert await _count_supersedes(driver, fresh_kref) == 2

        # Current is v3
        retrieved = await _get_belief_at_tag(driver, fresh_kref)
        assert retrieved["content"]["hypothesis"] == "v3"

        # Three total revisions exist
        cypher = """
        MATCH (rev:AtlasRevision {root_kref: $root_kref})
        RETURN count(rev) AS n
        """
        async with driver.session() as session:
            result = await session.run(cypher, root_kref=fresh_kref)
            record = await result.single()
        assert record["n"] == 3


class TestAGMReviseInclusion:
    """K*3 (base-level): no atoms beyond new_content introduced."""

    async def test_revise_does_not_leak_prior_keys(self, driver, fresh_kref):
        from atlas_core.revision import Kref, revise

        await revise(
            driver, Kref.parse(fresh_kref),
            new_content={"hypothesis": "v1", "confidence": 0.6, "extra_key": "value1"},
            revision_reason="v1",
        )
        await revise(
            driver, Kref.parse(fresh_kref),
            new_content={"hypothesis": "v2", "confidence": 0.8},  # NO extra_key
            revision_reason="v2",
        )

        retrieved = await _get_belief_at_tag(driver, fresh_kref)
        # K*3 base-level: revised content contains exactly what was passed in,
        # nothing inherited from the prior revision
        assert "extra_key" not in retrieved["content"]
        assert retrieved["content"] == {"hypothesis": "v2", "confidence": 0.8}


class TestAGMReviseVacuity:
    """K*4 Vacuity: when no conflict (first revision), no retraction occurs."""

    async def test_first_revision_no_supersedes_edge(self, driver, fresh_kref):
        from atlas_core.revision import Kref, revise

        await revise(
            driver, Kref.parse(fresh_kref),
            new_content={"hypothesis": "first", "confidence": 0.5},
            revision_reason="initial",
        )
        # No prior revision means no SUPERSEDES edge should be created
        assert await _count_supersedes(driver, fresh_kref) == 0


class TestAGMContract:
    """Contract removes from the retrieval surface; preserves history."""

    async def test_contract_deprecates_item(self, driver, fresh_kref):
        from atlas_core.revision import Kref, contract, revise

        await revise(
            driver, Kref.parse(fresh_kref),
            new_content={"hypothesis": "v1", "confidence": 0.6},
            revision_reason="v1",
        )

        outcome = await contract(
            driver, Kref.parse(fresh_kref),
            proposition_to_remove="v1",
            contraction_reason="invalidated by new evidence",
        )

        assert outcome.deprecated is True

        # Item is now flagged deprecated
        cypher = """
        MATCH (root:AtlasItem {root_kref: $root_kref})
        RETURN root.deprecated AS deprecated
        """
        async with driver.session() as session:
            result = await session.run(cypher, root_kref=fresh_kref)
            record = await result.single()
        assert record["deprecated"] is True

    async def test_contract_preserves_revision_in_graph(self, driver, fresh_kref):
        """Soft-deprecation excludes from retrieval but keeps the revision intact."""
        from atlas_core.revision import Kref, contract, revise

        await revise(
            driver, Kref.parse(fresh_kref),
            new_content={"hypothesis": "preserved", "confidence": 0.6},
            revision_reason="v1",
        )
        await contract(
            driver, Kref.parse(fresh_kref),
            proposition_to_remove="preserved",
            contraction_reason="test",
        )

        # Revision still exists in the graph (provenance preserved)
        cypher = """
        MATCH (rev:AtlasRevision {root_kref: $root_kref})
        RETURN count(rev) AS n
        """
        async with driver.session() as session:
            result = await session.run(cypher, root_kref=fresh_kref)
            record = await result.single()
        assert record["n"] == 1
