"""Integration test: run the full 49-scenario AGM compliance suite.

Target: 100% pass rate matching Kumiho Table 18. This is the formal
correctness proof for Atlas's AGM operators.
"""

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


async def test_full_compliance_suite_passes_100_percent(driver):
    """The headline result: 49/49 scenarios pass, all 7 postulates upheld.

    This is the same shape as Kumiho Table 18 — 5 categories × 7 postulates,
    49 scenarios total, target 100% pass rate.
    """
    from benchmarks.agm_compliance import run_suite
    from benchmarks.agm_compliance.scenarios import ALL_SCENARIOS

    assert len(ALL_SCENARIOS) == 49, "Spec calls for 49 scenarios"

    report = await run_suite(driver, ALL_SCENARIOS, stop_on_failure=False)

    # Print full summary regardless of pass/fail
    print("\n" + report.summary())

    # The headline assertion — 100% pass rate
    assert report.failed == 0, (
        f"AGM compliance suite has {report.failed} failures.\n\n{report.summary()}"
    )
    assert report.passed == 49


async def test_all_seven_postulates_have_at_least_one_scenario(driver):
    """Sanity: every postulate Kumiho proves is exercised by at least one scenario."""
    from benchmarks.agm_compliance import Postulate
    from benchmarks.agm_compliance.scenarios import ALL_SCENARIOS

    postulates_covered = {s.postulate for s in ALL_SCENARIOS}
    expected = set(Postulate)
    assert postulates_covered == expected, (
        f"Missing postulates: {expected - postulates_covered}"
    )


async def test_all_five_categories_have_scenarios(driver):
    """Sanity: every category has at least one scenario."""
    from benchmarks.agm_compliance import ComplianceCategory
    from benchmarks.agm_compliance.scenarios import ALL_SCENARIOS

    cats_covered = {s.category for s in ALL_SCENARIOS}
    expected = set(ComplianceCategory)
    assert cats_covered == expected, f"Missing categories: {expected - cats_covered}"
