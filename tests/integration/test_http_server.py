"""Integration tests for Atlas HTTP server — verifies FastAPI endpoints
mirror the MCP tool surface."""

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
def http_app(driver, tmp_dir):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from atlas_core.api import AtlasMCPServer, create_http_app
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    quarantine = QuarantineStore(tmp_dir / "candidates.db")
    ledger = HashChainedLedger(tmp_dir / "ledger.db")
    server = AtlasMCPServer(driver=driver, quarantine=quarantine, ledger=ledger)
    return create_http_app(mcp_server=server)


@pytest.fixture
async def client(http_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=http_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHTTPHealth:
    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "atlas"
        assert "version" in body


class TestHTTPTools:
    async def test_lists_eight_tools(self, client):
        from atlas_core.api import ATLAS_MCP_TOOLS

        response = await client.get("/tools")
        assert response.status_code == 200
        tools = response.json()["tools"]
        assert len(tools) == 10
        names = {t["name"] for t in tools}
        assert names == set(ATLAS_MCP_TOOLS)

    async def test_dispatch_tool_via_http(self, client):
        response = await client.post(
            "/tools/quarantine.list_pending",
            json={"params": {"limit": 10}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert "candidates" in body["result"]

    async def test_unknown_tool_returns_400(self, client):
        response = await client.post(
            "/tools/nonexistent.tool",
            json={"params": {}},
        )
        assert response.status_code == 400


class TestHTTPVerifyChain:
    async def test_verify_chain_endpoint(self, client):
        response = await client.get("/verify-chain")
        assert response.status_code == 200
        body = response.json()
        assert body["intact"] is True
        assert body["last_verified_sequence"] == 0


class TestGRPCScaffold:
    """Test the gRPC scaffold's documented contract — Phase 2 W7 wires the
    actual handlers, but the scaffold publishes the method list now."""

    def test_kumiho_compat_method_count(self):
        from atlas_core.api.grpc_server import (
            KUMIHO_COMPAT_METHODS,
            grpc_compat_method_count,
        )

        # Per Kumiho SDK audit: ~50 RPC methods. Our list documents the contract.
        count = grpc_compat_method_count()
        assert count >= 40, f"Expected ≥40 Kumiho-compat methods; got {count}"
        # Critical methods must be present
        assert "AnalyzeImpact" in KUMIHO_COMPAT_METHODS
        assert "TraverseEdges" in KUMIHO_COMPAT_METHODS
        assert "CreateRevision" in KUMIHO_COMPAT_METHODS
        assert "TagRevision" in KUMIHO_COMPAT_METHODS
