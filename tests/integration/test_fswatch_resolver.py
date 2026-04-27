"""Integration tests for the fswatch-driven adjudication resolver.

Spec: PHASE-5-AND-BEYOND.md § 1.2
"""

import os
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
def ledger(tmp_path):
    from atlas_core.trust import HashChainedLedger
    return HashChainedLedger(tmp_path / "ledger.db")


@pytest.fixture
def ns():
    return f"FsWatchTest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def cleanup(driver, ns):
    cypher = "MATCH (n) WHERE n.kref STARTS WITH $p OR n.root_kref STARTS WITH $p DETACH DELETE n"
    prefix = f"kref://{ns}/"
    async with driver.session() as s:
        await s.run(cypher, p=prefix)
    yield
    async with driver.session() as s:
        await s.run(cypher, p=prefix)


def _write_adj(path: Path, *, proposal_id: str, target_kref: str,
               decision: str | None = None,
               adjusted: float | None = None) -> Path:
    body = (
        f"---\n"
        f"type: ripple_adjudication\n"
        f"proposal_id: {proposal_id}\n"
        f"target_kref: {target_kref}\n"
        f"upstream_kref: kref://x/up\n"
        f"route: strategic_review\n"
        f"---\n\n"
        f"# Ripple Adjudication\n\n"
        f"## Confidence change proposed\n"
        f"- **Current:** 0.85\n"
        f"- **Proposed:** 0.40\n\n"
        f"## Decide\n\n"
    )
    if decision == "accept":
        body += "- [x] **Accept** — apply proposed confidence (0.40)\n"
    elif decision == "reject":
        body += "- [x] **Reject** — keep current confidence\n"
    elif decision == "adjust" and adjusted is not None:
        body += (
            f"- [x] **Adjust** — set confidence to: {adjusted}\n"
        )
    else:
        body += "- [ ] **Accept** — apply proposed confidence\n"
    path.write_text(body, encoding="utf-8")
    return path


# ─── Parsers ────────────────────────────────────────────────────────────────


class TestParsers:
    def test_parse_proposal_id(self):
        from atlas_core.ripple.fswatch_resolver import parse_proposal_id
        text = "---\ntype: x\nproposal_id: adj_001\n---\n"
        assert parse_proposal_id(text) == "adj_001"

    def test_parse_proposal_id_missing(self):
        from atlas_core.ripple.fswatch_resolver import parse_proposal_id
        assert parse_proposal_id("# no frontmatter") is None

    def test_parse_decision_accept(self):
        from atlas_core.ripple.fswatch_resolver import parse_decision
        text = "## Decide\n- [x] **Accept** — go for it"
        decision, conf = parse_decision(text)
        assert decision == "accept"
        assert conf is None

    def test_parse_decision_reject(self):
        from atlas_core.ripple.fswatch_resolver import parse_decision
        text = "## Decide\n- [x] **Reject** — no thanks"
        decision, conf = parse_decision(text)
        assert decision == "reject"

    def test_parse_decision_adjust_with_confidence(self):
        from atlas_core.ripple.fswatch_resolver import parse_decision
        text = "- [x] **Adjust** — set confidence to: 0.55"
        decision, conf = parse_decision(text)
        assert decision == "adjust"
        assert conf == 0.55

    def test_parse_decision_no_check(self):
        from atlas_core.ripple.fswatch_resolver import parse_decision
        text = "- [ ] **Accept** — not yet"
        decision, conf = parse_decision(text)
        assert decision is None


# ─── resolve_one ────────────────────────────────────────────────────────────


class TestResolveOne:
    async def test_no_decision_returns_no_op(
        self, driver, ledger, tmp_path, ns,
    ):
        from atlas_core.ripple.fswatch_resolver import resolve_one

        target = f"kref://{ns}/Beliefs/x.belief"
        path = _write_adj(
            tmp_path / "adj.md",
            proposal_id="adj_test_pending",
            target_kref=target,
        )
        ev = await resolve_one(
            path, driver=driver, ledger=ledger,
            directory=tmp_path,
        )
        assert ev.proposal_id == "adj_test_pending"
        assert ev.decision == ""
        assert ev.applied is False
        # File NOT moved (still being edited)
        assert path.exists()

    async def test_accept_round_trips_to_revision(
        self, driver, ledger, tmp_path, ns,
    ):
        from atlas_core.ripple.fswatch_resolver import resolve_one

        target = f"kref://{ns}/Beliefs/y.belief"
        path = _write_adj(
            tmp_path / "adj_accept.md",
            proposal_id="adj_test_accept",
            target_kref=target,
            decision="accept",
        )
        ev = await resolve_one(
            path, driver=driver, ledger=ledger,
            directory=tmp_path,
        )
        assert ev.applied is True
        assert ev.decision == "accept"
        assert ev.error is None

    async def test_adjust_carries_confidence(
        self, driver, ledger, tmp_path, ns,
    ):
        from atlas_core.ripple.fswatch_resolver import resolve_one

        target = f"kref://{ns}/Beliefs/z.belief"
        path = _write_adj(
            tmp_path / "adj_adjust.md",
            proposal_id="adj_test_adjust",
            target_kref=target,
            decision="adjust",
            adjusted=0.6,
        )
        ev = await resolve_one(
            path, driver=driver, ledger=ledger,
            directory=tmp_path,
        )
        assert ev.applied is True
        assert ev.decision == "adjust"


# ─── Watcher.scan_once ──────────────────────────────────────────────────────


class TestWatcherScanOnce:
    async def test_empty_dir_returns_empty(
        self, driver, ledger, tmp_path,
    ):
        from atlas_core.ripple.fswatch_resolver import AdjudicationWatcher
        w = AdjudicationWatcher(
            tmp_path / "missing", driver=driver, ledger=ledger,
        )
        assert await w.scan_once() == []

    async def test_scan_processes_every_file(
        self, driver, ledger, tmp_path, ns,
    ):
        from atlas_core.ripple.fswatch_resolver import AdjudicationWatcher

        adj_dir = tmp_path / "adjudication"
        adj_dir.mkdir()
        _write_adj(
            adj_dir / "1-a.md",
            proposal_id="adj_scan_001",
            target_kref=f"kref://{ns}/Beliefs/a.belief",
            decision="accept",
        )
        _write_adj(
            adj_dir / "2-b.md",
            proposal_id="adj_scan_002",
            target_kref=f"kref://{ns}/Beliefs/b.belief",
            decision="reject",
        )
        w = AdjudicationWatcher(
            adj_dir, driver=driver, ledger=ledger,
        )
        events = await w.scan_once()
        assert len(events) == 2
        decisions = {e.decision for e in events}
        assert decisions == {"accept", "reject"}
