"""Integration tests for the Kumiho-compat gRPC handlers.

Tests the dispatch table + each wired method against live Neo4j.
The gRPC server transport (.proto + grpcio) lands in a follow-up;
this commit ships the business logic and verifies it round-trips.

Spec: PHASE-5-AND-BEYOND.md § 3.3
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
    return f"GRPCTest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def cleanup(driver, ns):
    cypher = (
        "MATCH (n) WHERE n.kref STARTS WITH $p OR n.root_kref STARTS WITH $p "
        "DETACH DELETE n"
    )
    prefix = f"kref://Atlas/Projects/{ns}_"
    async with driver.session() as s:
        await s.run(cypher, p=prefix)
        await s.run(
            "MATCH (n) WHERE n.kref STARTS WITH $p OR n.root_kref STARTS WITH $p "
            "DETACH DELETE n",
            p=f"kref://{ns}/",
        )
    yield
    async with driver.session() as s:
        await s.run(cypher, p=prefix)
        await s.run(
            "MATCH (n) WHERE n.kref STARTS WITH $p OR n.root_kref STARTS WITH $p "
            "DETACH DELETE n",
            p=f"kref://{ns}/",
        )


# ─── Project methods ─────────────────────────────────────────────


class TestProjectMethods:
    async def test_create_then_get_project(self, driver, ns):
        from atlas_core.api.grpc_handlers import create_project, get_project

        pid = f"{ns}_alpha"
        created = await create_project(driver, project_id=pid, name="Alpha")
        assert created.code == "OK"
        assert created.payload["kref"].endswith(f"/{pid}.project")

        got = await get_project(driver, project_id=pid)
        assert got.code == "OK"
        assert got.payload["name"] == "Alpha"

    async def test_get_missing_project_returns_not_found(self, driver):
        from atlas_core.api.grpc_handlers import get_project
        result = await get_project(driver, project_id="nonexistent_project_xyz")
        assert result.code == "NOT_FOUND"

    async def test_create_project_requires_id(self, driver):
        from atlas_core.api.grpc_handlers import create_project
        result = await create_project(driver, project_id="", name="empty")
        assert result.code == "INVALID_ARGUMENT"

    async def test_get_projects_lists_created(self, driver, ns):
        from atlas_core.api.grpc_handlers import create_project, get_projects
        pid = f"{ns}_beta"
        await create_project(driver, project_id=pid, name="Beta")
        result = await get_projects(driver)
        assert result.code == "OK"
        ids = {p["project_id"] for p in result.payload["projects"]}
        assert pid in ids


# ─── Revision methods ────────────────────────────────────────────


class TestRevisionMethods:
    async def test_create_revision_routes_through_agm(self, driver, ns):
        from atlas_core.api.grpc_handlers import create_revision, get_revision

        target = f"kref://{ns}/Beliefs/sample.belief"
        result = await create_revision(
            driver,
            target_kref=target,
            content={"confidence": 0.7, "text": "first revision"},
        )
        assert result.code == "OK"
        new_kref = result.payload["new_revision_kref"]
        assert new_kref.startswith(target)

        # Read it back
        fetched = await get_revision(driver, revision_kref=new_kref)
        assert fetched.code == "OK"
        assert fetched.payload["content"]["text"] == "first revision"

    async def test_create_revision_bad_kref_invalid_argument(self, driver):
        from atlas_core.api.grpc_handlers import create_revision
        result = await create_revision(
            driver, target_kref="not-a-kref", content={},
        )
        assert result.code == "INVALID_ARGUMENT"

    async def test_get_missing_revision_not_found(self, driver, ns):
        from atlas_core.api.grpc_handlers import get_revision
        result = await get_revision(
            driver, revision_kref=f"kref://{ns}/never.belief?r=deadbeef",
        )
        assert result.code == "NOT_FOUND"


# ─── Resolve kref ────────────────────────────────────────────────


class TestResolveKref:
    async def test_resolve_existing_node(self, driver, ns):
        from atlas_core.api.grpc_handlers import resolve_kref
        kref = f"kref://{ns}/People/sarah.person"
        async with driver.session() as s:
            await s.run(
                "MERGE (p:Person:AtlasItem {kref: $k}) SET p.name = 'Sarah'",
                k=kref,
            )
        result = await resolve_kref(driver, kref=kref)
        assert result.code == "OK"
        assert "Person" in result.payload["labels"]
        assert result.payload["properties"]["name"] == "Sarah"

    async def test_resolve_missing_kref_not_found(self, driver, ns):
        from atlas_core.api.grpc_handlers import resolve_kref
        result = await resolve_kref(
            driver, kref=f"kref://{ns}/People/never.person",
        )
        assert result.code == "NOT_FOUND"


# ─── Dispatch table ──────────────────────────────────────────────


class TestDispatchTable:
    async def test_unimplemented_method_returns_unimplemented(self, driver):
        from atlas_core.api.grpc_handlers import dispatch
        result = await dispatch(driver, "CreateBundle")
        assert result.code == "UNIMPLEMENTED"
        assert "CreateBundle" in result.message

    async def test_dispatch_routes_to_wired_handler(self, driver, ns):
        from atlas_core.api.grpc_handlers import dispatch
        result = await dispatch(
            driver, "CreateProject",
            project_id=f"{ns}_dispatch", name="Dispatch test",
        )
        assert result.code == "OK"

    async def test_dispatch_bad_args_invalid_argument(self, driver):
        from atlas_core.api.grpc_handlers import dispatch
        # Missing required project_id
        result = await dispatch(driver, "CreateProject", name="just a name")
        assert result.code == "INVALID_ARGUMENT"


# ─── Traversal ───────────────────────────────────────────────────


class TestTraversal:
    async def test_analyze_impact_routes_to_ripple(self, driver, ns):
        from atlas_core.api.grpc_handlers import analyze_impact
        upstream = f"kref://{ns}/Beliefs/up.belief"
        downstream = f"kref://{ns}/Beliefs/down.belief"
        async with driver.session() as s:
            await s.run(
                "MERGE (u:AtlasItem {kref: $u}) SET u.deprecated = false "
                "MERGE (d:AtlasItem {kref: $d}) SET d.deprecated = false, "
                "  d.confidence_score = 0.6 "
                "MERGE (d)-[:DEPENDS_ON]->(u)",
                u=upstream, d=downstream,
            )
        result = await analyze_impact(driver, kref=upstream)
        assert result.code == "OK"
        kreffs = {n["kref"] for n in result.payload["impacted"]}
        assert downstream in kreffs

    async def test_traverse_edges_returns_neighbors(self, driver, ns):
        from atlas_core.api.grpc_handlers import traverse_edges
        a = f"kref://{ns}/Items/a"
        b = f"kref://{ns}/Items/b"
        async with driver.session() as s:
            await s.run(
                "MERGE (x {kref: $a}) MERGE (y {kref: $b}) "
                "MERGE (x)-[:DEPENDS_ON]->(y)",
                a=a, b=b,
            )
        result = await traverse_edges(driver, start_kref=a, max_depth=2)
        assert result.code == "OK"
        krefs = {n["kref"] for n in result.payload["neighbors"]}
        assert b in krefs
