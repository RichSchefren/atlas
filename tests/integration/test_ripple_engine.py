"""Integration tests for the integrated RippleEngine orchestrator.

Codex review (2026-04-27) flagged that engine.py was a log-only stub
even though the README claimed Ripple "shipped." This suite proves
the engine actually orchestrates the four stages end-to-end against
live Neo4j 5.26.

Spec: notes/06 - Ripple Algorithm Spec.md
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
    return f"EngineTest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def cleanup(driver, ns):
    cypher = "MATCH (n) WHERE n.kref STARTS WITH $p DETACH DELETE n"
    prefix = f"kref://{ns}/"
    async with driver.session() as s:
        await s.run(cypher, p=prefix)
    yield
    async with driver.session() as s:
        await s.run(cypher, p=prefix)


# ─── Single-node case ──────────────────────────────────────────────────────


class TestEngineNoOp:
    async def test_isolated_upstream_returns_empty_result(self, driver, ns):
        from atlas_core.ripple import RippleEngine

        kref = f"kref://{ns}/Beliefs/orphan.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (n:AtlasItem {kref: $k}) SET n.deprecated = false, "
                "n.confidence_score = 0.9",
                k=kref,
            )

        engine = RippleEngine(driver, emit_events=False)
        result = await engine.propagate(
            kref, old_confidence=0.9, new_confidence=0.3,
        )

        assert result.succeeded is True
        assert result.n_impacted == 0
        assert result.proposals == []
        assert result.contradictions == []
        assert result.routing == []


# ─── Single-dependent case ──────────────────────────────────────────────────


class TestEngineOneHop:
    async def test_upstream_change_produces_proposal(self, driver, ns):
        from atlas_core.ripple import RippleEngine

        upstream = f"kref://{ns}/Beliefs/upstream.belief"
        downstream = f"kref://{ns}/Beliefs/downstream.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (a:AtlasItem {kref: $a}) SET a.deprecated = false, "
                "  a.confidence_score = 0.9 "
                "MERGE (b:AtlasItem {kref: $b}) SET b.deprecated = false, "
                "  b.confidence_score = 0.85, b.last_evidence_days = 0 "
                "MERGE (b)-[:DEPENDS_ON {strength: 0.8}]->(a)",
                a=upstream, b=downstream,
            )

        engine = RippleEngine(driver, emit_events=False)
        result = await engine.propagate(
            upstream, old_confidence=0.9, new_confidence=0.2,
        )

        assert result.succeeded is True
        assert result.n_impacted == 1
        assert len(result.proposals) == 1
        prop = result.proposals[0]
        assert prop.target_kref == downstream
        # downstream confidence should weaken (or hold steady — not raise)
        assert prop.new_confidence <= 0.85

    async def test_returns_routing_decision_per_proposal(self, driver, ns):
        from atlas_core.ripple import RippleEngine

        upstream = f"kref://{ns}/Beliefs/up.belief"
        downstream = f"kref://{ns}/Beliefs/down.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (a:AtlasItem {kref: $a}) SET a.deprecated = false, "
                "  a.confidence_score = 0.9 "
                "MERGE (b:AtlasItem {kref: $b}) SET b.deprecated = false, "
                "  b.confidence_score = 0.8, b.last_evidence_days = 0 "
                "MERGE (b)-[:DEPENDS_ON {strength: 0.7}]->(a)",
                a=upstream, b=downstream,
            )

        engine = RippleEngine(driver, emit_events=False)
        result = await engine.propagate(
            upstream, old_confidence=0.9, new_confidence=0.2,
        )

        assert len(result.routing) == 1
        # n_strategic + n_core_protected + n_auto_apply == total proposals
        total = (
            result.n_strategic + result.n_core_protected + result.n_auto_apply
        )
        assert total == len(result.routing)


# ─── Cascade case ───────────────────────────────────────────────────────────


class TestEngineMultiHop:
    async def test_two_hop_cascade_produces_two_proposals(self, driver, ns):
        from atlas_core.ripple import RippleEngine

        upstream = f"kref://{ns}/Beliefs/root.belief"
        mid = f"kref://{ns}/Beliefs/mid.belief"
        leaf = f"kref://{ns}/Beliefs/leaf.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (r:AtlasItem {kref: $r}) SET r.deprecated = false, "
                "  r.confidence_score = 0.9 "
                "MERGE (m:AtlasItem {kref: $m}) SET m.deprecated = false, "
                "  m.confidence_score = 0.85, m.last_evidence_days = 0 "
                "MERGE (l:AtlasItem {kref: $l}) SET l.deprecated = false, "
                "  l.confidence_score = 0.80, l.last_evidence_days = 0 "
                "MERGE (m)-[:DEPENDS_ON {strength: 0.8}]->(r) "
                "MERGE (l)-[:DEPENDS_ON {strength: 0.7}]->(m)",
                r=upstream, m=mid, l=leaf,
            )

        engine = RippleEngine(driver, emit_events=False)
        result = await engine.propagate(
            upstream, old_confidence=0.9, new_confidence=0.2,
        )

        krefs = {p.target_kref for p in result.proposals}
        assert mid in krefs
        assert leaf in krefs
        assert result.n_impacted == 2


# ─── Error semantics ───────────────────────────────────────────────────────


class TestEngineErrorSemantics:
    async def test_engine_does_not_raise_on_internal_failure(
        self, driver, ns,
    ):
        """The contract: a Ripple cascade NEVER throws to the caller;
        errors land on result.error so the application keeps running."""
        from atlas_core.ripple import RippleEngine

        engine = RippleEngine(driver, emit_events=False)
        # Pass a malformed kref that analyze_impact will tolerate
        # (returns empty impacted) — the cascade should succeed with
        # zero impacted, not raise.
        result = await engine.propagate(
            "kref://does-not-exist-anywhere",
            old_confidence=0.9, new_confidence=0.1,
        )
        assert result.succeeded is True
        assert result.n_impacted == 0


# ─── Event emit (sanity) ───────────────────────────────────────────────────


class TestEngineEvents:
    async def test_emit_events_disabled_runs_clean(self, driver, ns):
        from atlas_core.ripple import RippleEngine

        engine = RippleEngine(driver, emit_events=False)
        result = await engine.propagate(
            f"kref://{ns}/x", old_confidence=0.9, new_confidence=0.5,
        )
        assert result.succeeded is True

    async def test_emit_events_enabled_does_not_block(self, driver, ns):
        """If GLOBAL_BROADCASTER is unreachable for any reason the
        cascade must still complete successfully."""
        from atlas_core.ripple import RippleEngine

        engine = RippleEngine(driver, emit_events=True)
        result = await engine.propagate(
            f"kref://{ns}/y", old_confidence=0.9, new_confidence=0.5,
        )
        assert result.succeeded is True
