"""End-to-end smoke test — verifies Atlas's Neo4j connection works and
AtlasGraphiti can be instantiated. Requires `docker-compose up` to be running."""

import os

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


def test_neo4j_reachable(neo4j_uri, neo4j_auth):
    """Atlas requires a live Neo4j 5.26+ instance for ingestion."""
    pytest.importorskip("neo4j")
    from neo4j import GraphDatabase

    user, password = neo4j_auth
    driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            result = session.run("RETURN 1 + 1 AS sum")
            assert result.single()["sum"] == 2
    finally:
        driver.close()


def test_neo4j_apoc_available(neo4j_uri, neo4j_auth):
    """APOC procedures are required for Graphiti's vector ops."""
    pytest.importorskip("neo4j")
    from neo4j import GraphDatabase

    user, password = neo4j_auth
    driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
    try:
        with driver.session() as session:
            result = session.run("CALL apoc.help('apoc') YIELD name RETURN count(name) AS n")
            assert result.single()["n"] > 0
    finally:
        driver.close()


def test_atlas_graphiti_instantiates(neo4j_uri, neo4j_auth, monkeypatch):
    """AtlasGraphiti subclass must instantiate without error against live Neo4j.

    Atlas's default LLM client is Anthropic; if no ANTHROPIC_API_KEY is in the
    environment we provide a stub LLM client to verify the subclass wiring
    independent of any LLM provider keys.
    """
    pytest.importorskip("graphiti_core")
    from atlas_core.graphiti import AtlasGraphiti

    # Provide stub LLM + embedder + cross-encoder so the test doesn't require any API keys.
    # Inherit from the abstract base classes so Graphiti's set_tracer / etc. methods work.
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.cross_encoder.client import CrossEncoderClient

    class _StubLLMClient(LLMClient):
        def __init__(self):
            pass
        async def _generate_response(self, *args, **kwargs):
            return {}
        def get_num_tokens(self, *args, **kwargs):
            return 0
        def set_tracer(self, tracer):
            self.tracer = tracer

    class _StubEmbedder(EmbedderClient):
        async def create(self, *args, **kwargs):
            return [0.0] * 1536
        async def create_batch(self, *args, **kwargs):
            return [[0.0] * 1536]

    class _StubCrossEncoder(CrossEncoderClient):
        async def rank(self, *args, **kwargs):
            return []

    user, password = neo4j_auth
    atlas = AtlasGraphiti(
        uri=neo4j_uri,
        user=user,
        password=password,
        llm_client=_StubLLMClient(),
        embedder=_StubEmbedder(),
        cross_encoder=_StubCrossEncoder(),
    )
    assert atlas is not None
    assert atlas.ripple_engine is None  # Phase 2 W1: not yet wired
    assert atlas.ledger is None         # Phase 2 W1: not yet wired
