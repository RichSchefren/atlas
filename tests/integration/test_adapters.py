"""Integration tests for Atlas runtime adapters.

Validates Hermes + OpenClaw adapters round-trip through the same
AtlasMCPServer that backs MCP/HTTP/gRPC, proving the substrate strategy:
one Atlas brain, many agent-runtime entry points.
"""

import json
import os
import tempfile
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
def mcp_server(driver, tmp_dir):
    from atlas_core.api import AtlasMCPServer
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    return AtlasMCPServer(
        driver=driver,
        quarantine=QuarantineStore(tmp_dir / "candidates.db"),
        ledger=HashChainedLedger(tmp_dir / "ledger.db"),
    )


# ─── Claude Code MCP plugin (stdio bridge) ──────────────────────────────────


class TestClaudeCodeAdapter:
    """The stdio loop is wired in main(); test the dispatcher logic directly."""

    async def test_initialize_returns_protocol_version(self, mcp_server):
        from atlas_core.adapters.claude_code import PROTOCOL_VERSION, _handle

        response = await _handle(mcp_server, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
        })
        assert response["result"]["protocolVersion"] == PROTOCOL_VERSION
        assert response["result"]["serverInfo"]["name"] == "atlas"

    async def test_tools_list_returns_seventeen(self, mcp_server):
        from atlas_core.adapters.claude_code import _handle

        response = await _handle(mcp_server, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        })
        assert len(response["result"]["tools"]) == 17

    async def test_tools_call_dispatches(self, mcp_server):
        from atlas_core.adapters.claude_code import _handle

        response = await _handle(mcp_server, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {
                "name": "ledger.verify_chain", "arguments": {},
            },
        })
        assert response["result"]["isError"] is False
        body = json.loads(response["result"]["content"][0]["text"])
        assert body["intact"] is True

    async def test_tools_call_unknown_tool_marks_error(self, mcp_server):
        from atlas_core.adapters.claude_code import _handle

        response = await _handle(mcp_server, {
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "bogus.tool", "arguments": {}},
        })
        assert response["result"]["isError"] is True

    async def test_initialized_notification_no_response(self, mcp_server):
        from atlas_core.adapters.claude_code import _handle

        response = await _handle(mcp_server, {
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert response is None


# ─── Hermes MemoryProvider ──────────────────────────────────────────────────


class TestHermesAdapter:
    async def test_put_routes_through_quarantine(self, mcp_server):
        from atlas_core.adapters import AtlasHermesProvider, HermesMemoryItem

        provider = AtlasHermesProvider(mcp_server=mcp_server)
        item = HermesMemoryItem(
            content="dark mode",
            metadata={
                "subject_kref": "kref://test/People/agent.person",
                "predicate": "pref.theme",
                "confidence": 0.5,
                "lane": "atlas_chat_history",
            },
            created_at="2026-04-26T00:00:00+00:00",
        )
        memory_id = await provider.put(item)
        assert memory_id.startswith("01")  # ULID prefix

    async def test_put_requires_subject_and_predicate(self, mcp_server):
        from atlas_core.adapters import AtlasHermesProvider, HermesMemoryItem

        provider = AtlasHermesProvider(mcp_server=mcp_server)
        with pytest.raises(ValueError, match="subject_kref"):
            await provider.put(HermesMemoryItem(content="x", metadata={}))

    async def test_search_get_delete_round_trip(self, mcp_server):
        from atlas_core.adapters import AtlasHermesProvider, HermesMemoryItem

        provider = AtlasHermesProvider(mcp_server=mcp_server)
        memory_id = await provider.put(HermesMemoryItem(
            content="The launch webinar is scheduled for Thursday",
            metadata={
                "subject_kref": "kref://test/Events/launch.event",
                "predicate": "schedule.date",
                "confidence": 0.7,
                "lane": "atlas_chat_history",
            },
        ))

        hits = await provider.search("launch webinar Thursday", k=5)
        assert [hit.item_id for hit in hits] == [memory_id]
        assert hits[0].content == "The launch webinar is scheduled for Thursday"
        fetched = await provider.get(memory_id)
        assert fetched is not None and fetched.item_id == memory_id
        assert await provider.delete(memory_id) is True
        assert await provider.get(memory_id) is None
        assert await provider.search("launch webinar Thursday", k=5) == []
        assert await provider.delete("missing-id") is False


# ─── OpenClaw memory plugin ─────────────────────────────────────────────────


class TestOpenClawAdapter:
    async def test_store_returns_memory_id(self, mcp_server):
        from atlas_core.adapters import AtlasOpenClawPlugin

        plugin = AtlasOpenClawPlugin(mcp_server=mcp_server)
        memory_id = await plugin.store(
            "user prefers dark mode",
            metadata={
                "agent_id": "research_agent",
                "session_id": "sess_001",
                "predicate": "pref.theme",
                "subject_kref": "kref://openclaw/People/user.person",
                "confidence": 0.6,
            },
        )
        assert memory_id.startswith("01")

    async def test_list_memories_filters_by_agent(self, mcp_server):
        from atlas_core.adapters import AtlasOpenClawPlugin

        plugin = AtlasOpenClawPlugin(mcp_server=mcp_server)
        await plugin.store("alpha", metadata={
            "agent_id": "agent_alpha", "session_id": "s1",
            "predicate": "pref.color", "subject_kref": "kref://openclaw/Agents/agent_alpha.agent",
            "confidence": 0.5,
        })
        await plugin.store("beta", metadata={
            "agent_id": "agent_beta", "session_id": "s2",
            "predicate": "pref.color", "subject_kref": "kref://openclaw/Agents/agent_beta.agent",
            "confidence": 0.5,
        })
        # No filter returns both (modulo lane filtering)
        all_memories = await plugin.list_memories()
        agent_alpha = await plugin.list_memories({"agent_id": "agent_alpha"})
        # agent filter is a strict subset
        assert len(agent_alpha) <= len(all_memories)
        for m in agent_alpha:
            assert "agent_alpha" in m.metadata["subject_kref"]

    async def test_recall_and_forget_round_trip(self, mcp_server):
        from atlas_core.adapters import AtlasOpenClawPlugin

        plugin = AtlasOpenClawPlugin(mcp_server=mcp_server)
        memory_id = await plugin.store(
            "Customer prefers concise weekly reports",
            metadata={
                "agent_id": "chief_of_staff",
                "session_id": "sess_recall",
                "predicate": "pref.reporting_style",
                "confidence": 0.8,
            },
        )

        hits = await plugin.recall("concise weekly reports", k=5)
        assert [hit.memory_id for hit in hits] == [memory_id]
        assert hits[0].text == "Customer prefers concise weekly reports"
        assert await plugin.forget(memory_id) is True
        assert await plugin.recall("concise weekly reports", k=5) == []
        assert await plugin.forget("missing-id") is False

    async def test_plugin_factory_needs_no_neo4j(self, tmp_dir):
        from atlas_core.adapters import openclaw_plugin

        plug = openclaw_plugin({
            "atlas_data_dir": str(tmp_dir),
        })
        assert plug is not None
        assert plug.mcp.driver is None

    async def test_plugin_metadata_constants(self):
        from atlas_core.adapters import (
            OPENCLAW_PLUGIN_NAME,
            OPENCLAW_PLUGIN_TYPE,
            OPENCLAW_PLUGIN_VERSION,
        )
        assert OPENCLAW_PLUGIN_NAME == "atlas-memory"
        assert OPENCLAW_PLUGIN_TYPE == "memory"
        assert OPENCLAW_PLUGIN_VERSION
