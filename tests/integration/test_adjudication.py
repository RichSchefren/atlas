"""Integration tests for adjudication routing + Obsidian queue writing.

Spec: 06 - Ripple Algorithm Spec § 6
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from atlas_core.ripple import ReassessmentProposal

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
    return f"AtlasAdjTest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def cleanup(driver, ns):
    cypher = "MATCH (n) WHERE n.kref STARTS WITH $prefix DETACH DELETE n"
    prefix = f"kref://{ns}/"
    async with driver.session() as session:
        await session.run(cypher, prefix=prefix)
    yield
    async with driver.session() as session:
        await session.run(cypher, prefix=prefix)


@pytest.fixture
def temp_queue_dir():
    """Per-test isolated adjudication queue directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def make_belief(
    driver,
    ns: str,
    item: str,
    confidence: float,
    *,
    stakes: str = "medium",
    is_core_conviction: bool = False,
) -> str:
    kref = f"kref://{ns}/Beliefs/{item}.belief"
    cypher = """
    MERGE (n:AtlasItem {kref: $kref})
    SET n.deprecated = false,
        n.confidence_score = $conf,
        n.stakes = $stakes,
        n.is_core_conviction = $core
    """
    async with driver.session() as session:
        await session.run(
            cypher,
            kref=kref,
            conf=confidence,
            stakes=stakes,
            core=is_core_conviction,
        )
    return kref


def make_proposal(
    target_kref: str,
    new_conf: float,
    old_conf: float,
    *,
    rationale: str = "",
) -> ReassessmentProposal:
    from atlas_core.ripple import ReassessmentProposal

    return ReassessmentProposal(
        target_kref=target_kref,
        old_confidence=old_conf,
        new_confidence=new_conf,
        components={"current": old_conf, "perturbation": new_conf - old_conf},
        llm_rationale=rationale,
        upstream_kref="kref://test/upstream.belief",
        depth=1,
    )


# ─── Routing tests ───────────────────────────────────────────────────────────


class TestRoutingRoutine:
    async def test_low_stakes_small_delta_no_contras_routes_routine(self, driver, ns):
        from atlas_core.ripple import (
            AdjudicationRoute,
            route_proposal,
        )

        kref = await make_belief(driver, ns, "ordinary", 0.6, stakes="low")
        proposal = make_proposal(kref, new_conf=0.65, old_conf=0.6)

        decision = await route_proposal(driver, proposal, contradictions=[])

        assert decision.route == AdjudicationRoute.AUTO_APPLY
        assert decision.contradictions_count == 0


class TestRoutingStrategic:
    async def test_high_stakes_routes_strategic(self, driver, ns):
        from atlas_core.ripple import (
            AdjudicationRoute,
            route_proposal,
        )

        kref = await make_belief(driver, ns, "high_stakes", 0.6, stakes="high")
        proposal = make_proposal(kref, new_conf=0.62, old_conf=0.6)

        decision = await route_proposal(driver, proposal, contradictions=[])

        assert decision.route == AdjudicationRoute.STRATEGIC_REVIEW
        assert "high" in decision.rationale.lower()

    async def test_critical_stakes_routes_strategic(self, driver, ns):
        from atlas_core.ripple import (
            AdjudicationRoute,
            route_proposal,
        )

        kref = await make_belief(driver, ns, "critical", 0.6, stakes="critical")
        proposal = make_proposal(kref, new_conf=0.6, old_conf=0.6)

        decision = await route_proposal(driver, proposal, contradictions=[])
        assert decision.route == AdjudicationRoute.STRATEGIC_REVIEW

    async def test_large_confidence_delta_routes_strategic(self, driver, ns):
        from atlas_core.ripple import (
            AdjudicationRoute,
            route_proposal,
        )

        kref = await make_belief(driver, ns, "ord", 0.6, stakes="low")
        # Δ = 0.20 ≥ 0.15 floor → strategic
        proposal = make_proposal(kref, new_conf=0.40, old_conf=0.6)

        decision = await route_proposal(driver, proposal, contradictions=[])
        assert decision.route == AdjudicationRoute.STRATEGIC_REVIEW
        assert "delta" in decision.rationale.lower() or "Δ" in decision.rationale

    async def test_contradictions_route_strategic(self, driver, ns):
        from atlas_core.ripple import (
            AdjudicationRoute,
            ContradictionCategory,
            ContradictionPair,
            Severity,
            route_proposal,
        )

        kref = await make_belief(driver, ns, "ord", 0.6, stakes="low")
        proposal = make_proposal(kref, new_conf=0.65, old_conf=0.6)
        contradictions = [
            ContradictionPair(
                proposal_kref=kref,
                opposed_kref="kref://other/x.belief",
                category=ContradictionCategory.STRATEGIC_BELIEF_CONFLICT,
                severity=Severity.HIGH,
                rationale="test contradiction",
            )
        ]

        decision = await route_proposal(driver, proposal, contradictions)
        assert decision.route == AdjudicationRoute.STRATEGIC_REVIEW
        assert decision.contradictions_count == 1


class TestRoutingCoreProtected:
    async def test_core_conviction_protected(self, driver, ns):
        from atlas_core.ripple import (
            AdjudicationRoute,
            route_proposal,
        )

        kref = await make_belief(
            driver, ns, "core", 0.95,
            stakes="critical", is_core_conviction=True,
        )
        # Even with critical stakes + huge delta, core protection wins
        proposal = make_proposal(kref, new_conf=0.4, old_conf=0.95)

        decision = await route_proposal(driver, proposal, contradictions=[])

        assert decision.route == AdjudicationRoute.CORE_PROTECTED
        assert decision.is_core_conviction is True
        assert "core" in decision.rationale.lower()


class TestRouteAll:
    async def test_route_all_aggregates(self, driver, ns):
        from atlas_core.ripple import (
            AdjudicationRoute,
            route_all,
        )

        ord_kref = await make_belief(driver, ns, "ord", 0.6, stakes="low")
        high_kref = await make_belief(driver, ns, "high", 0.6, stakes="high")
        core_kref = await make_belief(
            driver, ns, "core", 0.95, is_core_conviction=True,
        )

        proposals = [
            make_proposal(ord_kref, 0.65, 0.6),
            make_proposal(high_kref, 0.62, 0.6),
            make_proposal(core_kref, 0.4, 0.95),
        ]
        decisions = await route_all(driver, proposals, contradictions=[])

        assert len(decisions) == 3
        routes = [d.route for d in decisions]
        assert AdjudicationRoute.AUTO_APPLY in routes
        assert AdjudicationRoute.STRATEGIC_REVIEW in routes
        assert AdjudicationRoute.CORE_PROTECTED in routes


# ─── Obsidian queue file writing ─────────────────────────────────────────────


class TestObsidianQueueWriter:
    async def test_writes_markdown_file(self, driver, ns, temp_queue_dir):
        from atlas_core.ripple import (
            route_proposal,
            write_adjudication_entry,
        )

        kref = await make_belief(driver, ns, "high", 0.6, stakes="high")
        proposal = make_proposal(kref, 0.62, 0.6, rationale="upstream slipped")
        decision = await route_proposal(driver, proposal, contradictions=[])

        path = await write_adjudication_entry(
            proposal=proposal,
            decision=decision,
            contradictions=[],
            directory=temp_queue_dir,
            upstream_belief_text="ZenithPro pricing changed",
        )

        assert path.exists()
        content = path.read_text(encoding="utf-8")

        # Frontmatter present
        assert "type: ripple_adjudication" in content
        assert "status: pending" in content
        assert kref in content
        assert "route: strategic_review" in content
        # Content sections
        assert "Confidence change proposed" in content
        assert "Decide" in content
        assert "Accept" in content
        assert "Reject" in content
        # Upstream summary rendered
        assert "ZenithPro pricing changed" in content

    async def test_filename_includes_date_and_seq(self, driver, ns, temp_queue_dir):
        from datetime import datetime, timezone

        from atlas_core.ripple import route_proposal, write_adjudication_entry

        kref = await make_belief(driver, ns, "x", 0.6, stakes="high")
        proposal = make_proposal(kref, 0.62, 0.6)
        decision = await route_proposal(driver, proposal, contradictions=[])

        path = await write_adjudication_entry(
            proposal=proposal, decision=decision,
            contradictions=[], directory=temp_queue_dir,
        )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert path.name.startswith(f"{today}-001-")

    async def test_per_day_sequence_increments(self, driver, ns, temp_queue_dir):
        from atlas_core.ripple import route_proposal, write_adjudication_entry

        for i in range(3):
            kref = await make_belief(driver, ns, f"item{i}", 0.6, stakes="high")
            proposal = make_proposal(kref, 0.62, 0.6)
            decision = await route_proposal(driver, proposal, contradictions=[])
            await write_adjudication_entry(
                proposal=proposal, decision=decision,
                contradictions=[], directory=temp_queue_dir,
            )

        files = sorted(temp_queue_dir.glob("*.md"))
        assert len(files) == 3
        # Sequence numbers visible in filenames
        names = [f.name for f in files]
        assert any("-001-" in n for n in names)
        assert any("-002-" in n for n in names)
        assert any("-003-" in n for n in names)

    async def test_contradictions_rendered(self, driver, ns, temp_queue_dir):
        from atlas_core.ripple import (
            ContradictionCategory,
            ContradictionPair,
            Severity,
            route_proposal,
            write_adjudication_entry,
        )

        kref = await make_belief(driver, ns, "x", 0.85, stakes="high")
        proposal = make_proposal(kref, 0.85, 0.85)
        contras = [
            ContradictionPair(
                proposal_kref=kref,
                opposed_kref="kref://test/opposed.belief",
                category=ContradictionCategory.STRATEGIC_BELIEF_CONFLICT,
                severity=Severity.HIGH,
                rationale="market is softening",
            )
        ]
        decision = await route_proposal(driver, proposal, contras)

        path = await write_adjudication_entry(
            proposal=proposal, decision=decision,
            contradictions=contras, directory=temp_queue_dir,
        )

        content = path.read_text(encoding="utf-8")
        assert "Contradictions detected" in content
        assert "strategic_belief_conflict" in content
        assert "high severity" in content
        assert "market is softening" in content

    async def test_write_strategic_entries_skips_routine(self, driver, ns, temp_queue_dir):
        from atlas_core.ripple import (
            route_all,
            write_strategic_entries,
        )

        ord_kref = await make_belief(driver, ns, "ord", 0.6, stakes="low")
        high_kref = await make_belief(driver, ns, "high", 0.6, stakes="high")
        core_kref = await make_belief(
            driver, ns, "core", 0.95, is_core_conviction=True,
        )

        proposals = [
            make_proposal(ord_kref, 0.65, 0.6),  # routine — skipped
            make_proposal(high_kref, 0.62, 0.6),  # strategic — written
            make_proposal(core_kref, 0.4, 0.95),  # core — written
        ]
        decisions = await route_all(driver, proposals, contradictions=[])

        written = await write_strategic_entries(
            proposals, decisions, contradictions=[], directory=temp_queue_dir,
        )

        assert len(written) == 2  # high + core, NOT ord
