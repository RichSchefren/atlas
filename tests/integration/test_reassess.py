"""Integration tests for Ripple Reassess against live Neo4j.

Validates the end-to-end behavior of the confidence-propagation formula
when fed real graph nodes from analyze_impact.

Spec: 06 - Ripple Algorithm Spec § 4
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
    return f"AtlasReassessTest_{uuid.uuid4().hex[:8]}"


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
    """Create a typed belief node ready for Reassess."""
    kref = f"kref://{ns}/Beliefs/{item}.belief"
    cypher = """
    MERGE (n:AtlasItem {kref: $kref})
    SET n.deprecated = false,
        n.confidence_score = $conf,
        n.hypothesis = $hyp,
        n.created_at = datetime()
    """
    async with driver.session() as session:
        await session.run(cypher, kref=kref, conf=confidence, hyp=hypothesis)
    return kref


async def link_depends_on(driver, dependent_kref: str, target_kref: str, strength: float = 1.0) -> None:
    """Create a DEPENDS_ON edge with explicit strength."""
    cypher = """
    MATCH (s {kref: $dep_kref})
    MATCH (t {kref: $target_kref})
    MERGE (s)-[r:DEPENDS_ON]->(t)
    SET r.dependency_strength = $strength
    """
    async with driver.session() as session:
        await session.run(cypher, dep_kref=dependent_kref, target_kref=target_kref, strength=strength)


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestReassessSingleDependent:
    async def test_upstream_drop_reduces_dependent_confidence(self, driver, ns):
        """Upstream confidence drops 0.9 → 0.4 → dependent should drop too."""
        from atlas_core.ripple import (
            ImpactNode,
            UpstreamChange,
            reassess_dependent,
        )

        upstream = await make_belief(driver, ns, "upstream", 0.4, "X used to be true")
        dependent = await make_belief(driver, ns, "dependent", 0.7, "Y depends on X")
        await link_depends_on(driver, dependent_kref=dependent, target_kref=upstream)

        impacted = ImpactNode(
            kref=dependent,
            types=("AtlasItem",),
            current_confidence=0.7,
            depth=1,
            upstream_kref=upstream,
        )
        change = UpstreamChange(
            upstream_kref=upstream,
            belief_text="X used to be true",
            old_confidence=0.9,
            new_confidence=0.4,
        )

        proposal = await reassess_dependent(driver, impacted, change)

        assert proposal.target_kref == dependent
        assert proposal.old_confidence == 0.7
        # Drop expected; bounded to [0, 1]
        assert proposal.new_confidence < proposal.old_confidence
        # Component breakdown — exposed for transparency
        assert "current" in proposal.components
        assert "beta" in proposal.components
        assert "gamma" in proposal.components
        assert "delta" in proposal.components
        assert "perturbation" in proposal.components

    async def test_upstream_rise_increases_dependent_confidence(self, driver, ns):
        from atlas_core.ripple import (
            ImpactNode,
            UpstreamChange,
            reassess_dependent,
        )

        upstream = await make_belief(driver, ns, "u", 0.95, "X")
        dependent = await make_belief(driver, ns, "d", 0.5, "Y depends on X")
        await link_depends_on(driver, dependent_kref=dependent, target_kref=upstream)

        impacted = ImpactNode(
            kref=dependent, types=("AtlasItem",),
            current_confidence=0.5, depth=1, upstream_kref=upstream,
        )
        change = UpstreamChange(
            upstream_kref=upstream, belief_text="X",
            old_confidence=0.4, new_confidence=0.95,
        )
        proposal = await reassess_dependent(driver, impacted, change)

        assert proposal.new_confidence > proposal.old_confidence


class TestReassessClipping:
    async def test_confidence_clipped_at_one(self, driver, ns):
        from atlas_core.ripple import (
            ImpactNode,
            UpstreamChange,
            reassess_dependent,
        )

        upstream = await make_belief(driver, ns, "u", 1.0, "X")
        dependent = await make_belief(driver, ns, "d", 0.99, "Y")
        await link_depends_on(driver, dependent_kref=dependent, target_kref=upstream)

        impacted = ImpactNode(
            kref=dependent, types=("AtlasItem",),
            current_confidence=0.99, depth=1, upstream_kref=upstream,
        )
        change = UpstreamChange(
            upstream_kref=upstream, belief_text="X",
            old_confidence=0.0, new_confidence=1.0,
        )
        proposal = await reassess_dependent(driver, impacted, change)
        assert proposal.new_confidence <= 1.0

    async def test_confidence_clipped_at_zero(self, driver, ns):
        from atlas_core.ripple import (
            ImpactNode,
            UpstreamChange,
            reassess_dependent,
        )

        upstream = await make_belief(driver, ns, "u", 0.01, "X")
        dependent = await make_belief(driver, ns, "d", 0.05, "Y")
        await link_depends_on(driver, dependent_kref=dependent, target_kref=upstream)

        impacted = ImpactNode(
            kref=dependent, types=("AtlasItem",),
            current_confidence=0.05, depth=1, upstream_kref=upstream,
        )
        change = UpstreamChange(
            upstream_kref=upstream, belief_text="X",
            old_confidence=1.0, new_confidence=0.0,
        )
        proposal = await reassess_dependent(driver, impacted, change)
        assert proposal.new_confidence >= 0.0


class TestReassessCascade:
    async def test_cascade_processes_in_bfs_order(self, driver, ns):
        """A → B → C cascade: B (depth 1) processed before C (depth 2)."""
        from atlas_core.ripple import (
            ImpactNode,
            UpstreamChange,
            analyze_impact,
            reassess_cascade,
        )

        a = await make_belief(driver, ns, "a", 0.3, "A drops")
        b = await make_belief(driver, ns, "b", 0.6, "B depends on A")
        c = await make_belief(driver, ns, "c", 0.7, "C depends on B")
        await link_depends_on(driver, dependent_kref=b, target_kref=a)
        await link_depends_on(driver, dependent_kref=c, target_kref=b)

        impact = await analyze_impact(driver, a)
        assert len(impact.impacted) == 2

        change = UpstreamChange(
            upstream_kref=a, belief_text="A drops",
            old_confidence=0.9, new_confidence=0.3,
        )
        proposals = await reassess_cascade(driver, impact.impacted, change)

        assert len(proposals) == 2
        # BFS-order processing: depth 1 first
        assert proposals[0].depth == 1
        assert proposals[0].target_kref == b
        assert proposals[1].depth == 2
        assert proposals[1].target_kref == c

    async def test_dependency_strength_modulates_propagation(self, driver, ns):
        """Strong (1.0) and weak (0.2) dependencies on same upstream should
        produce different reassessments — stronger dep moves more."""
        from atlas_core.ripple import (
            ImpactNode,
            UpstreamChange,
            reassess_dependent,
        )

        upstream = await make_belief(driver, ns, "u", 0.3, "X drops")
        strong = await make_belief(driver, ns, "strong", 0.7, "Strong dep")
        weak = await make_belief(driver, ns, "weak", 0.7, "Weak dep")
        await link_depends_on(driver, dependent_kref=strong, target_kref=upstream, strength=1.0)
        await link_depends_on(driver, dependent_kref=weak, target_kref=upstream, strength=0.2)

        change = UpstreamChange(
            upstream_kref=upstream, belief_text="X drops",
            old_confidence=0.9, new_confidence=0.3,
        )

        strong_imp = ImpactNode(
            kref=strong, types=("AtlasItem",),
            current_confidence=0.7, depth=1, upstream_kref=upstream,
        )
        weak_imp = ImpactNode(
            kref=weak, types=("AtlasItem",),
            current_confidence=0.7, depth=1, upstream_kref=upstream,
        )

        strong_p = await reassess_dependent(driver, strong_imp, change)
        weak_p = await reassess_dependent(driver, weak_imp, change)

        # Strong dep absorbs more of the negative signal → drops more
        assert strong_p.new_confidence < weak_p.new_confidence
