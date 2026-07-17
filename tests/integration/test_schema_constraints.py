"""Integration tests for Atlas's Neo4j belief-node uniqueness constraints.

Audit finding (atlas #8): "No Neo4j indexes or constraints anywhere ... an
unconstrained MERGE key risks duplicate-node corruption under concurrent
writers."  These tests pin the fix: `ensure_schema` installs uniqueness
constraints so a duplicate belief kref can never be minted.

Requires a live Neo4j (the same instance the rest of tests/integration uses).
"""

import os
import uuid

import pytest

pytestmark = pytest.mark.integration

CONSTRAINT_NAMES = {
    "atlas_item_kref_unique",
    "atlas_item_root_kref_unique",
    "belief_candidate_id_unique",
}


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
    return f"kref://SchemaConstraintTest_{uuid.uuid4().hex[:8]}/Beliefs/x.belief"


async def _delete_ns(driver, ns: str) -> None:
    async with driver.session() as session:
        await session.run("MATCH (n {kref: $k}) DETACH DELETE n", k=ns)


async def _count(driver, ns: str) -> int:
    async with driver.session() as session:
        result = await session.run("MATCH (n {kref: $k}) RETURN count(n) AS n", k=ns)
        record = await result.single()
    return int(record["n"])


async def test_ensure_schema_installs_belief_constraints(driver):
    """ensure_schema creates every named belief-node uniqueness constraint."""
    from atlas_core.migrations.schema import ensure_schema

    await ensure_schema(driver)

    async with driver.session() as session:
        result = await session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        names = {record["name"] async for record in result}

    assert CONSTRAINT_NAMES.issubset(names), (
        f"missing constraints: {CONSTRAINT_NAMES - names}"
    )


async def test_ensure_schema_is_idempotent(driver):
    """Calling ensure_schema repeatedly is a no-op, never an error."""
    from atlas_core.migrations.schema import ensure_schema

    await ensure_schema(driver)
    await ensure_schema(driver)  # second call must not raise


async def test_unconstrained_label_permits_duplicate_kref(driver, ns):
    """Control: a label with no uniqueness constraint permits duplicate krefs.

    This pins the pre-fix behavior (Neo4j does not enforce key uniqueness on its
    own) using a throwaway label, so it never perturbs the real constraints that
    the rest of the suite relies on.
    """
    async with driver.session() as session:
        await session.run("MATCH (n:ReproUnconstrained {kref: $k}) DETACH DELETE n", k=ns)
    try:
        async with driver.session() as session:
            await session.run("CREATE (:ReproUnconstrained {kref: $k})", k=ns)
            await session.run("CREATE (:ReproUnconstrained {kref: $k})", k=ns)
            result = await session.run(
                "MATCH (n:ReproUnconstrained {kref: $k}) RETURN count(n) AS n", k=ns
            )
            record = await result.single()
        assert int(record["n"]) == 2, "expected duplicates on an unconstrained label"
    finally:
        async with driver.session() as session:
            await session.run(
                "MATCH (n:ReproUnconstrained {kref: $k}) DETACH DELETE n", k=ns
            )


async def test_duplicate_kref_rejected_after_ensure_schema(driver, ns):
    """After ensure_schema, a second node with the same AtlasItem kref is rejected."""
    from neo4j.exceptions import ConstraintError

    from atlas_core.migrations.schema import ensure_schema

    await ensure_schema(driver)
    await _delete_ns(driver, ns)
    try:
        async with driver.session() as session:
            await session.run("CREATE (:AtlasItem:Belief {kref: $k})", k=ns)
            with pytest.raises(ConstraintError):
                await session.run("CREATE (:AtlasItem:Belief {kref: $k})", k=ns)
        assert await _count(driver, ns) == 1, "duplicate must not have been created"
    finally:
        await _delete_ns(driver, ns)
