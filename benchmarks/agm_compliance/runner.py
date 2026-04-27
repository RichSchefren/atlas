"""AGM compliance suite — runner + result types + harness.

Each scenario:
  1. Sets up an initial graph state (a sequence of revisions/contractions)
  2. Performs a final operation
  3. Asserts a specific postulate holds

Postulate checks are operational not symbolic — Atlas tests the actual
Cypher-backed AGM operators against live Neo4j, not a symbolic engine.

Spec: Kumiho paper § 15.7 (49 scenarios). Atlas reproduces the table.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import AsyncDriver


# ─── Taxonomy ────────────────────────────────────────────────────────────────


class Postulate(str, Enum):
    """The seven postulates Kumiho proves Atlas must satisfy."""

    K2_SUCCESS = "K*2"
    K3_INCLUSION = "K*3"
    K4_VACUITY = "K*4"
    K5_CONSISTENCY = "K*5"
    K6_EXTENSIONALITY = "K*6"
    RELEVANCE = "Relevance"
    CORE_RETAINMENT = "Core-Retainment"


class ComplianceCategory(str, Enum):
    """The five scenario categories Kumiho's Table 18 spans."""

    SIMPLE = "simple"
    MULTI_ITEM = "multi_item"
    CHAIN = "chain"
    TEMPORAL = "temporal"
    ADVERSARIAL = "adversarial"


@dataclass
class Scenario:
    """A single compliance test scenario.

    `setup_fn` is async, receives the test root_kref and the live driver, and
    establishes graph state. `assertion_fn` performs the postulate check and
    returns (passed: bool, detail: str).
    """

    scenario_id: str
    category: ComplianceCategory
    postulate: Postulate
    description: str
    setup_fn: Callable[..., Awaitable[None]]
    assertion_fn: Callable[..., Awaitable[tuple[bool, str]]]


@dataclass
class ComplianceResult:
    """Outcome of one scenario."""

    scenario_id: str
    category: ComplianceCategory
    postulate: Postulate
    passed: bool
    detail: str = ""
    error: str | None = None


@dataclass
class SuiteReport:
    """Aggregate report across all scenarios."""

    results: list[ComplianceResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    def by_category(self) -> dict[ComplianceCategory, tuple[int, int]]:
        """Per-category (passed, total) tuples."""
        out: dict[ComplianceCategory, tuple[int, int]] = {}
        for r in self.results:
            p, t = out.get(r.category, (0, 0))
            out[r.category] = (p + (1 if r.passed else 0), t + 1)
        return out

    def by_postulate(self) -> dict[Postulate, tuple[int, int]]:
        """Per-postulate (passed, total) tuples."""
        out: dict[Postulate, tuple[int, int]] = {}
        for r in self.results:
            p, t = out.get(r.postulate, (0, 0))
            out[r.postulate] = (p + (1 if r.passed else 0), t + 1)
        return out

    def summary(self) -> str:
        lines = [
            f"AGM Compliance Suite — {self.passed}/{self.total} ({100 * self.pass_rate:.1f}%)",
            "",
            "By category:",
        ]
        for cat, (p, t) in sorted(self.by_category().items(), key=lambda x: x[0].value):
            lines.append(f"  {cat.value:14s} {p}/{t}")
        lines.append("")
        lines.append("By postulate:")
        for post, (p, t) in sorted(self.by_postulate().items(), key=lambda x: x[0].value):
            lines.append(f"  {post.value:18s} {p}/{t}")
        if self.failed > 0:
            lines.append("")
            lines.append("Failures:")
            for r in self.results:
                if not r.passed:
                    lines.append(f"  {r.scenario_id} [{r.category.value}/{r.postulate.value}]")
                    lines.append(f"    {r.error or r.detail}")
        return "\n".join(lines)


# ─── Harness helpers ─────────────────────────────────────────────────────────


def fresh_namespace() -> str:
    """Per-scenario unique kref namespace, prevents cross-scenario pollution."""
    return f"kref://AtlasComp/{uuid.uuid4().hex[:8]}/test_{uuid.uuid4().hex[:6]}.belief"


async def cleanup_namespace(driver: AsyncDriver, root_kref: str) -> None:
    """Delete all nodes/edges scoped to a test root_kref."""
    cypher = """
    MATCH (n)
    WHERE n.root_kref = $root_kref OR n.kref = $root_kref
    DETACH DELETE n
    """
    async with driver.session() as session:
        await session.run(cypher, root_kref=root_kref)


async def get_tagged_content(
    driver: AsyncDriver,
    root_kref: str,
    tag: str = "current",
) -> dict[str, Any] | None:
    """Fetch the content currently tagged at root_kref."""
    cypher = """
    MATCH (tag:AtlasTag {name: $tag, root_kref: $root_kref})-[:POINTS_TO]->(rev:AtlasRevision)
    RETURN rev.content_json AS content_json, rev.kref AS kref
    """
    async with driver.session() as session:
        result = await session.run(cypher, tag=tag, root_kref=root_kref)
        record = await result.single()
    if record is None:
        return None
    return {"content": json.loads(record["content_json"]), "kref": record["kref"]}


async def count_supersedes(driver: AsyncDriver, root_kref: str) -> int:
    """Count SUPERSEDES edges within a single item's revision chain."""
    cypher = """
    MATCH (a:AtlasRevision {root_kref: $root_kref})-[s:SUPERSEDES]->(b:AtlasRevision)
    RETURN count(s) AS n
    """
    async with driver.session() as session:
        result = await session.run(cypher, root_kref=root_kref)
        record = await result.single()
    return record["n"]


async def count_revisions(driver: AsyncDriver, root_kref: str) -> int:
    """Count distinct revisions for an item — includes superseded + tagged."""
    cypher = """
    MATCH (rev:AtlasRevision {root_kref: $root_kref})
    RETURN count(rev) AS n
    """
    async with driver.session() as session:
        result = await session.run(cypher, root_kref=root_kref)
        record = await result.single()
    return record["n"]


async def is_deprecated(driver: AsyncDriver, root_kref: str) -> bool:
    cypher = """
    MATCH (root:AtlasItem {root_kref: $root_kref})
    RETURN coalesce(root.deprecated, false) AS dep
    """
    async with driver.session() as session:
        result = await session.run(cypher, root_kref=root_kref)
        record = await result.single()
    return bool(record["dep"]) if record else False


# ─── Suite runner ────────────────────────────────────────────────────────────


async def run_suite(
    driver: AsyncDriver,
    scenarios: list[Scenario],
    *,
    stop_on_failure: bool = False,
) -> SuiteReport:
    """Execute all scenarios sequentially. Returns aggregate report.

    Each scenario gets its own fresh root_kref namespace and is fully isolated:
    setup → assertion → cleanup. A scenario failure does not contaminate the
    next scenario.
    """
    report = SuiteReport()

    for scenario in scenarios:
        ns = fresh_namespace()
        try:
            await scenario.setup_fn(driver, ns)
            passed, detail = await scenario.assertion_fn(driver, ns)
            report.results.append(
                ComplianceResult(
                    scenario_id=scenario.scenario_id,
                    category=scenario.category,
                    postulate=scenario.postulate,
                    passed=passed,
                    detail=detail,
                )
            )
            if not passed and stop_on_failure:
                break
        except Exception as exc:
            report.results.append(
                ComplianceResult(
                    scenario_id=scenario.scenario_id,
                    category=scenario.category,
                    postulate=scenario.postulate,
                    passed=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            if stop_on_failure:
                break
        finally:
            await cleanup_namespace(driver, ns)

    return report
