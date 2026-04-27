"""Integration tests for Atlas MCP server — uses live Neo4j.

Verifies the 8 Atlas-original tools dispatch correctly and produce the
expected result shapes.
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
def quarantine(tmp_dir):
    from atlas_core.trust import QuarantineStore
    return QuarantineStore(tmp_dir / "candidates.db")


@pytest.fixture
def ledger(tmp_dir):
    from atlas_core.trust import HashChainedLedger
    return HashChainedLedger(tmp_dir / "ledger.db")


@pytest.fixture
def mcp_server(driver, quarantine, ledger):
    from atlas_core.api import AtlasMCPServer
    return AtlasMCPServer(driver=driver, quarantine=quarantine, ledger=ledger)


@pytest.fixture
def ns() -> str:
    return f"AtlasMCPTest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def cleanup_neo4j(driver, ns):
    cypher = "MATCH (n) WHERE n.kref STARTS WITH $prefix DETACH DELETE n"
    prefix = f"kref://{ns}/"
    async with driver.session() as session:
        await session.run(cypher, prefix=prefix)
    yield
    async with driver.session() as session:
        await session.run(cypher, prefix=prefix)


# ─── Server registration ────────────────────────────────────────────────────


class TestServerRegistration:
    def test_eight_tools_registered(self, mcp_server):
        from atlas_core.api import ATLAS_MCP_TOOLS

        listed = mcp_server.list_tools()
        names = {t["name"] for t in listed}
        assert names == set(ATLAS_MCP_TOOLS)
        assert len(listed) == 13

    def test_tool_definitions_have_input_schema(self, mcp_server):
        for tool in mcp_server.list_tools():
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_duplicate_register_raises(self, mcp_server):
        from atlas_core.api import MCPTool

        async def noop(**kwargs):
            return {}

        existing = mcp_server.list_tools()[0]["name"]
        with pytest.raises(ValueError, match="already registered"):
            mcp_server.register(MCPTool(
                name=existing, description="x",
                parameters_schema={"type": "object"},
                handler=noop,
            ))


# ─── Dispatch error handling ────────────────────────────────────────────────


class TestDispatchErrors:
    async def test_unknown_tool_returns_error(self, mcp_server):
        result = await mcp_server.dispatch("nonexistent.tool", {})
        assert result.ok is False
        assert "unknown tool" in result.error

    async def test_invalid_params_returns_error(self, mcp_server):
        # ripple.analyze_impact requires `kref`
        result = await mcp_server.dispatch("ripple.analyze_impact", {})
        assert result.ok is False
        assert "invalid params" in result.error.lower()


# ─── ripple.analyze_impact ──────────────────────────────────────────────────


class TestRippleAnalyzeImpactTool:
    async def test_isolated_node_empty_impact(self, mcp_server, driver, ns):
        kref = f"kref://{ns}/Beliefs/alone.belief"
        async with driver.session() as session:
            await session.run(
                "MERGE (n:AtlasItem {kref: $k}) SET n.deprecated = false",
                k=kref,
            )

        result = await mcp_server.dispatch(
            "ripple.analyze_impact", {"kref": kref},
        )
        assert result.ok is True
        assert result.result["impacted"] == []
        assert result.result["cycles_detected"] == []
        assert result.result["truncated"] is False

    async def test_with_dependent(self, mcp_server, driver, ns):
        upstream = f"kref://{ns}/Beliefs/up.belief"
        downstream = f"kref://{ns}/Beliefs/down.belief"
        async with driver.session() as session:
            await session.run(
                "MERGE (a:AtlasItem {kref: $a}) SET a.deprecated = false "
                "MERGE (b:AtlasItem {kref: $b}) SET b.deprecated = false, "
                "  b.confidence_score = 0.6 "
                "MERGE (b)-[:DEPENDS_ON]->(a)",
                a=upstream, b=downstream,
            )

        result = await mcp_server.dispatch(
            "ripple.analyze_impact", {"kref": upstream},
        )
        assert result.ok is True
        assert len(result.result["impacted"]) == 1
        assert result.result["impacted"][0]["kref"] == downstream
        assert result.result["impacted"][0]["depth"] == 1


# ─── quarantine.upsert / list_pending ───────────────────────────────────────


class TestQuarantineTools:
    async def test_upsert_then_list_pending(self, mcp_server):
        # `pref.*` predicate => low-risk classification.
        # confidence 0.5 < 0.90 => not auto-promoted, so status lands in PENDING
        # (not REQUIRES_APPROVAL, which `list_pending` would skip).
        params = {
            "lane": "atlas_sessions",
            "assertion_type": "preference",
            "subject_kref": "kref://test/People/x.person",
            "predicate": "pref.cli_tool",
            "object_value": "tmux",
            "confidence": 0.5,
            "evidence_source": "session_a",
            "evidence_source_family": "session",
            "evidence_kref": "kref://test/Sessions/s.session",
            "evidence_timestamp": "2026-04-26T00:00:00+00:00",
        }
        upsert = await mcp_server.dispatch("quarantine.upsert", params)
        assert upsert.ok is True
        assert upsert.result["is_new"] is True
        cid = upsert.result["candidate_id"]

        pending = await mcp_server.dispatch(
            "quarantine.list_pending", {"limit": 50},
        )
        assert pending.ok is True
        cids = {c["candidate_id"] for c in pending.result["candidates"]}
        assert cid in cids

    async def test_upsert_auto_promotes_low_risk_high_conf(self, mcp_server):
        result = await mcp_server.dispatch(
            "quarantine.upsert",
            {
                "lane": "atlas_sessions",
                "assertion_type": "preference",
                "subject_kref": "kref://test/People/rich.person",
                "predicate": "pref.theme",
                "object_value": "dark",
                "confidence": 0.95,
                "evidence_source": "x",
                "evidence_source_family": "session",
                "evidence_kref": "kref://test/x.session",
                "evidence_timestamp": "2026-04-26T00:00:00+00:00",
            },
        )
        assert result.ok is True
        assert result.result["is_auto_promoted"] is True
        assert result.result["trust_score"] == 1.0


# ─── ledger.verify_chain ────────────────────────────────────────────────────


class TestLedgerVerifyChain:
    async def test_empty_ledger_intact(self, mcp_server):
        result = await mcp_server.dispatch("ledger.verify_chain", {})
        assert result.ok is True
        assert result.result["intact"] is True
        assert result.result["last_verified_sequence"] == 0


# ─── adjudication ───────────────────────────────────────────────────────────


class TestAdjudicationTools:
    async def test_resolve_validates_decision_enum(self, mcp_server):
        result = await mcp_server.dispatch(
            "adjudication.resolve",
            {"proposal_id": "adj_x", "decision": "bogus"},
        )
        assert result.ok is False
        assert "decision must be one of" in result.error

    async def test_resolve_adjust_requires_confidence(self, mcp_server):
        result = await mcp_server.dispatch(
            "adjudication.resolve",
            {"proposal_id": "adj_x", "decision": "adjust"},
        )
        assert result.ok is False
        assert "adjusted_confidence required" in result.error

    async def test_resolve_unknown_proposal_id_fails(self, mcp_server, tmp_dir):
        result = await mcp_server.dispatch(
            "adjudication.resolve",
            {
                "proposal_id": "adj_does_not_exist",
                "decision": "accept",
                "adjudication_dir": str(tmp_dir),
            },
        )
        assert result.ok is False
        assert "not found" in result.error
