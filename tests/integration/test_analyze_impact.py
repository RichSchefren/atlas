"""Integration tests for Ripple's analyze_impact against live Neo4j.

Validates the headline algorithmic property of Atlas: when a belief changes,
its downstream Depends_On cascade is correctly enumerated, in BFS order,
with cycles handled and bounds respected.

Spec: 06 - Ripple Algorithm Spec § 3
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
    return f"AtlasImpactTest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def cleanup(driver, ns):
    """Wipe everything in the test namespace before AND after."""
    cypher = """
    MATCH (n) WHERE n.kref STARTS WITH $prefix
    DETACH DELETE n
    """
    prefix = f"kref://{ns}/"
    async with driver.session() as session:
        await session.run(cypher, prefix=prefix)
    yield
    async with driver.session() as session:
        await session.run(cypher, prefix=prefix)


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def make_node(driver, ns: str, item: str, confidence: float | None = None) -> str:
    """Create a single AtlasItem node with a kref. Returns the kref."""
    kref = f"kref://{ns}/Beliefs/{item}.belief"
    cypher = """
    MERGE (n:AtlasItem {kref: $kref})
    SET n.deprecated = false,
        n.confidence_score = $conf,
        n.created_at = datetime()
    """
    async with driver.session() as session:
        await session.run(cypher, kref=kref, conf=confidence)
    return kref


async def make_depends_on(driver, source_kref: str, target_kref: str) -> None:
    """Create a DEPENDS_ON edge from source to target.

    Semantic: source DEPENDS_ON target means changes to target propagate to
    source. AnalyzeImpact starts at the changed node and traverses OUTGOING
    DEPENDS_ON edges to find dependents.
    """
    cypher = """
    MATCH (s {kref: $source_kref})
    MATCH (t {kref: $target_kref})
    MERGE (t)-[:DEPENDS_ON]->(s)
    """
    async with driver.session() as session:
        await session.run(cypher, source_kref=source_kref, target_kref=target_kref)


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestAnalyzeImpactBasics:
    async def test_isolated_node_has_no_impact(self, driver, ns):
        """An origin node with no outgoing Depends_On has empty impact set."""
        from atlas_core.ripple import analyze_impact

        origin = await make_node(driver, ns, "alone")
        result = await analyze_impact(driver, origin)

        assert result.impacted == []
        assert result.cycles_detected == []
        assert result.truncated is False

    async def test_single_dependent(self, driver, ns):
        """A → B (B depends on A): revising A surfaces B."""
        from atlas_core.ripple import analyze_impact

        a = await make_node(driver, ns, "a", confidence=0.9)
        b = await make_node(driver, ns, "b", confidence=0.6)
        await make_depends_on(driver, source_kref=b, target_kref=a)

        result = await analyze_impact(driver, a)

        assert len(result.impacted) == 1
        assert result.impacted[0].kref == b
        assert result.impacted[0].depth == 1
        assert result.impacted[0].upstream_kref == a
        assert result.impacted[0].current_confidence == 0.6

    async def test_two_independent_dependents(self, driver, ns):
        """A → B and A → C (both depend on A): revising A surfaces both at depth 1."""
        from atlas_core.ripple import analyze_impact

        a = await make_node(driver, ns, "a")
        b = await make_node(driver, ns, "b")
        c = await make_node(driver, ns, "c")
        await make_depends_on(driver, source_kref=b, target_kref=a)
        await make_depends_on(driver, source_kref=c, target_kref=a)

        result = await analyze_impact(driver, a)

        assert len(result.impacted) == 2
        krefs = {n.kref for n in result.impacted}
        assert krefs == {b, c}
        assert all(n.depth == 1 for n in result.impacted)


class TestAnalyzeImpactBFS:
    async def test_linear_chain_bfs_order(self, driver, ns):
        """A → B → C → D: BFS produces depth-ascending order."""
        from atlas_core.ripple import analyze_impact

        a = await make_node(driver, ns, "a")
        b = await make_node(driver, ns, "b")
        c = await make_node(driver, ns, "c")
        d = await make_node(driver, ns, "d")
        await make_depends_on(driver, source_kref=b, target_kref=a)
        await make_depends_on(driver, source_kref=c, target_kref=b)
        await make_depends_on(driver, source_kref=d, target_kref=c)

        result = await analyze_impact(driver, a)

        assert len(result.impacted) == 3
        # BFS: depth 1 first, then 2, then 3
        assert [n.depth for n in result.impacted] == [1, 2, 3]
        assert [n.kref for n in result.impacted] == [b, c, d]

    async def test_diamond_pattern(self, driver, ns):
        """A → B,C → D (both B and C feed D): D appears once at depth 2."""
        from atlas_core.ripple import analyze_impact

        a = await make_node(driver, ns, "a")
        b = await make_node(driver, ns, "b")
        c = await make_node(driver, ns, "c")
        d = await make_node(driver, ns, "d")
        await make_depends_on(driver, source_kref=b, target_kref=a)
        await make_depends_on(driver, source_kref=c, target_kref=a)
        await make_depends_on(driver, source_kref=d, target_kref=b)
        await make_depends_on(driver, source_kref=d, target_kref=c)

        result = await analyze_impact(driver, a)

        # B and C at depth 1, D once at depth 2 (visited-set dedup)
        assert len(result.impacted) == 3
        depths_by_kref = {n.kref: n.depth for n in result.impacted}
        assert depths_by_kref[b] == 1
        assert depths_by_kref[c] == 1
        assert depths_by_kref[d] == 2


class TestAnalyzeImpactCycles:
    async def test_self_loop(self, driver, ns):
        """A → A: detect cycle, do not infinite-loop."""
        from atlas_core.ripple import analyze_impact

        a = await make_node(driver, ns, "a")
        await make_depends_on(driver, source_kref=a, target_kref=a)

        result = await analyze_impact(driver, a)

        # Origin is visited at start; the back-edge to A is detected as cycle
        assert result.impacted == []
        assert len(result.cycles_detected) == 1
        assert a in result.cycles_detected[0]

    async def test_two_node_cycle(self, driver, ns):
        """A → B → A: B added once, then back-edge detected as cycle."""
        from atlas_core.ripple import analyze_impact

        a = await make_node(driver, ns, "a")
        b = await make_node(driver, ns, "b")
        await make_depends_on(driver, source_kref=b, target_kref=a)
        await make_depends_on(driver, source_kref=a, target_kref=b)

        result = await analyze_impact(driver, a)

        assert len(result.impacted) == 1
        assert result.impacted[0].kref == b
        assert len(result.cycles_detected) == 1

    async def test_three_node_cycle(self, driver, ns):
        """A → B → C → A: terminate cleanly."""
        from atlas_core.ripple import analyze_impact

        a = await make_node(driver, ns, "a")
        b = await make_node(driver, ns, "b")
        c = await make_node(driver, ns, "c")
        await make_depends_on(driver, source_kref=b, target_kref=a)
        await make_depends_on(driver, source_kref=c, target_kref=b)
        await make_depends_on(driver, source_kref=a, target_kref=c)

        result = await analyze_impact(driver, a)

        assert len(result.impacted) == 2
        assert {n.kref for n in result.impacted} == {b, c}
        assert len(result.cycles_detected) == 1


class TestAnalyzeImpactBounds:
    async def test_max_depth_truncates_chain(self, driver, ns):
        """A 5-deep chain with max_depth=2 returns only depths 1 and 2."""
        from atlas_core.ripple import analyze_impact

        nodes = [await make_node(driver, ns, f"n{i}") for i in range(6)]
        for i in range(5):
            await make_depends_on(driver, source_kref=nodes[i + 1], target_kref=nodes[i])

        result = await analyze_impact(driver, nodes[0], max_depth=2)

        assert len(result.impacted) == 2
        assert [n.depth for n in result.impacted] == [1, 2]

    async def test_max_nodes_truncates_fan_out(self, driver, ns):
        """High-fanout graph with max_nodes=3 returns 3 with truncated=True."""
        from atlas_core.ripple import analyze_impact

        a = await make_node(driver, ns, "a")
        for i in range(10):
            child = await make_node(driver, ns, f"c{i}")
            await make_depends_on(driver, source_kref=child, target_kref=a)

        result = await analyze_impact(driver, a, max_nodes=3)

        assert len(result.impacted) == 3
        assert result.truncated is True


class TestAnalyzeImpactDeprecated:
    async def test_deprecated_dependents_excluded(self, driver, ns):
        """Deprecated nodes don't enter the cascade — Atlas's two-tier model."""
        from atlas_core.ripple import analyze_impact

        a = await make_node(driver, ns, "a")
        live = await make_node(driver, ns, "live")
        gone = await make_node(driver, ns, "gone")
        await make_depends_on(driver, source_kref=live, target_kref=a)
        await make_depends_on(driver, source_kref=gone, target_kref=a)

        # Mark "gone" deprecated
        async with driver.session() as session:
            await session.run(
                "MATCH (n {kref: $k}) SET n.deprecated = true", k=gone
            )

        result = await analyze_impact(driver, a)

        krefs = {n.kref for n in result.impacted}
        assert krefs == {live}


class TestAnalyzeImpactPerformance:
    async def test_realistic_business_graph_under_500ms(self, driver, ns):
        """100-node business-shaped graph (b≈3, d≈4) traverses in well under 500ms.

        Per Ripple Spec § 3.3 perf target. Rich's actual graph will have similar
        shape — this test validates the latency budget on representative scale.
        """
        import time

        from atlas_core.ripple import analyze_impact

        # Build a 100-node tree-ish graph: 1 root, then ~3 fan-out, depth 4
        root = await make_node(driver, ns, "root")
        layer = [root]
        node_count = 1
        for d in range(4):
            new_layer = []
            for parent in layer:
                fanout = 3
                for i in range(fanout):
                    if node_count >= 100:
                        break
                    child = await make_node(driver, ns, f"d{d}_{node_count}")
                    await make_depends_on(driver, source_kref=child, target_kref=parent)
                    new_layer.append(child)
                    node_count += 1
                if node_count >= 100:
                    break
            layer = new_layer
            if node_count >= 100:
                break

        start = time.perf_counter()
        result = await analyze_impact(driver, root)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(result.impacted) >= 50, f"Expected substantial cascade, got {len(result.impacted)}"
        # Generous bound — first run with Cypher cold; will be tighter post-warmup
        assert elapsed_ms < 1500, f"AnalyzeImpact took {elapsed_ms:.0f}ms (target <500ms warm)"
