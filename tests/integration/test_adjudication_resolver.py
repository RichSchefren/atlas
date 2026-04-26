"""End-to-end test for the Ripple resolution loop.

Closes the loop: write an adjudication entry → call resolve_adjudication →
verify (1) AGM revise mutated Neo4j, (2) ledger got a SUPERSEDE event,
(3) the markdown file moved to resolved/.
"""

import os
import tempfile
import uuid
from pathlib import Path

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
def tmp_dir():
    with tempfile.TemporaryDirectory() as t:
        yield Path(t)


@pytest.fixture
def ledger(tmp_dir):
    from atlas_core.trust import HashChainedLedger
    return HashChainedLedger(tmp_dir / "ledger.db")


@pytest.fixture
def ns():
    return f"ResolveTest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def cleanup_neo4j(driver, ns):
    cypher = "MATCH (n) WHERE n.kref STARTS WITH $p OR n.root_kref STARTS WITH $p DETACH DELETE n"
    prefix = f"kref://{ns}/"
    async with driver.session() as session:
        await session.run(cypher, p=prefix)
    yield
    async with driver.session() as session:
        await session.run(cypher, p=prefix)


def _write_adjudication_file(
    *,
    directory: Path,
    proposal_id: str,
    target_kref: str,
    upstream_kref: str = "kref://up/x.belief",
    current: float = 0.85,
    proposed: float = 0.42,
    route: str = "strategic_review",
) -> Path:
    """Synthesize a minimum-viable adjudication entry the resolver can parse."""
    directory.mkdir(parents=True, exist_ok=True)
    body = f"""---
type: ripple_adjudication
status: pending
created: 2026-04-26T00:00:00+00:00
proposal_id: {proposal_id}
target_kref: {target_kref}
upstream_kref: {upstream_kref}
route: {route}
contradictions_count: 0
---

# Ripple Adjudication

**Routing decision:** `{route}`
**Reason:** test

## Confidence change proposed

- **Current:** {current:.3f}
- **Proposed:** {proposed:.3f}
"""
    path = directory / f"2026-04-26-001-{proposal_id}.md"
    path.write_text(body, encoding="utf-8")
    return path


# ─── Resolver round-trip ────────────────────────────────────────────────────


class TestResolveRoundtrip:
    async def test_accept_creates_revision_and_ledger_event(
        self, driver, ledger, tmp_dir, ns,
    ):
        from atlas_core.ripple.resolver import resolve_adjudication

        target_kref = f"kref://{ns}/Beliefs/origins_accessible.belief"
        adj_dir = tmp_dir / "adjudication"
        _write_adjudication_file(
            directory=adj_dir,
            proposal_id="adj_2026_001",
            target_kref=target_kref,
            current=0.85,
            proposed=0.40,
        )

        outcome = await resolve_adjudication(
            "adj_2026_001",
            "accept",
            driver=driver,
            ledger=ledger,
            directory=adj_dir,
        )

        assert outcome.applied is True
        assert outcome.target_kref == target_kref
        assert outcome.confidence_set == 0.40
        assert outcome.new_revision_kref is not None
        assert outcome.new_revision_kref.startswith(target_kref)
        assert outcome.ledger_event_id

        # Ledger chain still intact + the new event is at sequence 1
        chain = ledger.verify_chain()
        assert chain.intact is True
        assert chain.last_verified_sequence == 1

        # Markdown file moved
        original = adj_dir / "2026-04-26-001-adj_2026_001.md"
        archived = adj_dir / "resolved" / "2026-04-26-001-adj_2026_001.md"
        assert not original.exists()
        assert archived.exists()
        assert outcome.archived_to == str(archived)

        # Neo4j actually has the new revision
        async with driver.session() as session:
            result = await session.run(
                "MATCH (r:AtlasRevision {kref: $k}) RETURN r.confidence_present",
                k=outcome.new_revision_kref,
            )
            row = await result.single()
            assert row is not None

    async def test_adjust_uses_provided_confidence(
        self, driver, ledger, tmp_dir, ns,
    ):
        from atlas_core.ripple.resolver import resolve_adjudication

        target_kref = f"kref://{ns}/Beliefs/adjust.belief"
        adj_dir = tmp_dir / "adjudication"
        _write_adjudication_file(
            directory=adj_dir,
            proposal_id="adj_2026_adj",
            target_kref=target_kref,
            current=0.80, proposed=0.30,
        )

        outcome = await resolve_adjudication(
            "adj_2026_adj",
            "adjust",
            driver=driver,
            ledger=ledger,
            adjusted_confidence=0.55,
            directory=adj_dir,
        )
        assert outcome.applied is True
        assert outcome.confidence_set == 0.55  # not 0.30 (proposed)

    async def test_reject_writes_audit_event_no_revision(
        self, driver, ledger, tmp_dir, ns,
    ):
        from atlas_core.ripple.resolver import resolve_adjudication

        target_kref = f"kref://{ns}/Beliefs/keep.belief"
        adj_dir = tmp_dir / "adjudication"
        _write_adjudication_file(
            directory=adj_dir,
            proposal_id="adj_2026_rej",
            target_kref=target_kref,
            current=0.90, proposed=0.10,
        )
        outcome = await resolve_adjudication(
            "adj_2026_rej",
            "reject",
            driver=driver,
            ledger=ledger,
            directory=adj_dir,
        )
        assert outcome.applied is False
        assert outcome.new_revision_kref is None
        # But the audit event still landed
        assert outcome.ledger_event_id
        chain = ledger.verify_chain()
        assert chain.intact is True
        assert chain.last_verified_sequence == 1

    async def test_demote_core_clears_flag_and_revises(
        self, driver, ledger, tmp_dir, ns,
    ):
        from atlas_core.ripple.resolver import resolve_adjudication

        target_kref = f"kref://{ns}/Beliefs/sacred.belief"
        adj_dir = tmp_dir / "adjudication"
        _write_adjudication_file(
            directory=adj_dir,
            proposal_id="adj_2026_demote",
            target_kref=target_kref,
            current=0.95, proposed=0.30,
            route="core_protected",
        )
        outcome = await resolve_adjudication(
            "adj_2026_demote",
            "demote_core",
            driver=driver,
            ledger=ledger,
            directory=adj_dir,
        )
        assert outcome.applied is True
        assert any("core_protected flag cleared" in n for n in outcome.notes)

    async def test_invalid_decision_raises(self, driver, ledger, tmp_dir):
        from atlas_core.ripple.resolver import resolve_adjudication

        with pytest.raises(ValueError, match="decision must be one of"):
            await resolve_adjudication(
                "adj_x", "delete_everything",
                driver=driver, ledger=ledger,
                directory=tmp_dir,
            )

    async def test_adjust_without_confidence_raises(
        self, driver, ledger, tmp_dir,
    ):
        from atlas_core.ripple.resolver import resolve_adjudication

        with pytest.raises(ValueError, match="adjusted_confidence required"):
            await resolve_adjudication(
                "adj_x", "adjust",
                driver=driver, ledger=ledger,
                directory=tmp_dir,
            )

    async def test_unknown_proposal_id_raises(self, driver, ledger, tmp_dir):
        from atlas_core.ripple.resolver import resolve_adjudication

        with pytest.raises(ValueError, match="adjudication entry not found"):
            await resolve_adjudication(
                "adj_missing", "accept",
                driver=driver, ledger=ledger,
                directory=tmp_dir,
            )


# ─── Frontmatter parser ─────────────────────────────────────────────────────


class TestFrontmatterParse:
    def test_parses_simple_kv_lines(self):
        from atlas_core.ripple.resolver import _parse_frontmatter

        text = "---\nkey: value\nfoo: bar\n---\n# body\n"
        fm = _parse_frontmatter(text)
        assert fm == {"key": "value", "foo": "bar"}

    def test_returns_empty_for_no_frontmatter(self):
        from atlas_core.ripple.resolver import _parse_frontmatter

        assert _parse_frontmatter("# just body") == {}

    def test_extracts_confidences(self):
        from atlas_core.ripple.resolver import _parse_confidences

        text = (
            "## Confidence change proposed\n\n"
            "- **Current:** 0.850\n"
            "- **Proposed:** 0.421\n"
        )
        cur, prop = _parse_confidences(text)
        assert cur == 0.85
        assert prop == 0.421
