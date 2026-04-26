"""Lineage walker — traces a Decision back through its SUPPORTS chain.

Given a Decision kref, walks SUPPORTS edges N hops backward to surface
the belief chain that justified the decision. Used to answer "why did
we decide X?" queries and to detect when a decision's foundation has
weakened.

Spec: PHASE-5-AND-BEYOND.md § 1.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import AsyncDriver


log = logging.getLogger(__name__)


DEFAULT_MAX_DEPTH: int = 5
"""How many hops back the walker traces. Most decisions have a chain
of 2-3 supporting beliefs; 5 is a conservative ceiling."""


@dataclass
class LineageNode:
    """One belief in the decision's chain."""

    kref: str
    text: str
    confidence: float
    deprecated: bool
    depth: int  # 1 = direct support, 2 = support's support, etc.
    strength_to_parent: float


@dataclass
class LineageWalk:
    """Full walk result. `chain` is depth-ordered (depth 1 first)."""

    decision_kref: str
    chain: list[LineageNode] = field(default_factory=list)
    truncated: bool = False  # True if max_depth was hit before chain ended
    weakest_link_confidence: float = 1.0

    @property
    def is_load_bearing_weakened(self) -> bool:
        """True when any high-strength support has dropped below
        DECISION_SUPPORT_FLOOR. Surfaces decisions that need re-eval."""
        from atlas_core.ripple.contradiction import DECISION_SUPPORT_FLOOR
        return any(
            n.confidence < DECISION_SUPPORT_FLOOR and n.strength_to_parent >= 0.7
            for n in self.chain
        )


class LineageWalker:
    """Wraps the Cypher walk so callers don't write raw queries."""

    def __init__(self, driver: AsyncDriver, *, max_depth: int = DEFAULT_MAX_DEPTH):
        self.driver = driver
        self.max_depth = max_depth

    async def walk(self, decision_kref: str) -> LineageWalk:
        """Walk SUPPORTS chain backward from decision_kref."""
        cypher = (
            f"MATCH path = (d:Decision {{kref: $k}})"
            f"-[:SUPPORTS*1..{self.max_depth}]->(b:Belief) "
            "WITH path, length(path) AS depth "
            "ORDER BY depth ASC "
            "UNWIND relationships(path) AS r "
            "WITH startNode(r) AS parent, endNode(r) AS child, r, depth "
            "RETURN DISTINCT child.kref AS kref, "
            "       child.text AS text, "
            "       coalesce(child.confidence_score, child.confidence, 0.5) AS confidence, "
            "       coalesce(child.deprecated, false) AS deprecated, "
            "       coalesce(r.strength, 0.5) AS strength, "
            "       depth "
            "ORDER BY depth ASC, child.kref"
        )
        async with self.driver.session() as session:
            result = await session.run(cypher, k=decision_kref)
            rows = [r async for r in result]

        walk = LineageWalk(decision_kref=decision_kref)
        seen: set[str] = set()
        for row in rows:
            kref = row["kref"]
            if kref in seen:
                continue
            seen.add(kref)
            walk.chain.append(LineageNode(
                kref=kref,
                text=row.get("text") or "",
                confidence=float(row.get("confidence") or 0.5),
                deprecated=bool(row.get("deprecated") or False),
                depth=int(row.get("depth") or 1),
                strength_to_parent=float(row.get("strength") or 0.5),
            ))

        if walk.chain:
            walk.weakest_link_confidence = min(n.confidence for n in walk.chain)
        # Heuristic: if the deepest node hit max_depth, the chain may
        # extend further than we walked.
        if walk.chain and any(n.depth == self.max_depth for n in walk.chain):
            walk.truncated = True
        return walk


async def walk_decision_chain(
    driver: AsyncDriver,
    decision_kref: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> LineageWalk:
    """One-shot helper for the common case."""
    return await LineageWalker(driver, max_depth=max_depth).walk(decision_kref)
