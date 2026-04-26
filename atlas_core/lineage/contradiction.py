"""Lineage-weakening contradiction detector.

When a belief gets demoted via Ripple, every Decision that rests on
that belief via a SUPPORTS edge with strength ≥ DECISION_SUPPORT_FLOOR
becomes a candidate contradiction. This module surfaces those decisions
through the existing contradiction-detector pipeline.

Spec: PHASE-5-AND-BEYOND.md § 1.5
       06 - Ripple Algorithm Spec § 5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import AsyncDriver


log = logging.getLogger(__name__)


@dataclass
class LineageContradiction:
    """A decision whose support chain has weakened below the floor."""

    decision_kref: str
    decision_description: str
    weakened_belief_kref: str
    weakened_belief_text: str
    new_belief_confidence: float
    edge_strength: float
    severity: str  # "high" if strength ≥ 0.85, "medium" otherwise


async def detect_lineage_contradictions(
    driver: AsyncDriver,
    weakened_belief_krefs: list[str],
) -> list[LineageContradiction]:
    """For each belief whose confidence dropped, find every Decision
    that depends on it with high strength. Returns one
    LineageContradiction per (decision, weakened_belief) pair."""
    if not weakened_belief_krefs:
        return []

    from atlas_core.ripple.contradiction import DECISION_SUPPORT_FLOOR

    cypher = (
        "MATCH (d:Decision)-[r:SUPPORTS]->(b:Belief) "
        "WHERE b.kref IN $belief_krefs "
        "  AND coalesce(b.confidence_score, b.confidence, 0.5) < $floor "
        "  AND r.strength >= 0.5 "
        "RETURN d.kref AS d_kref, "
        "       coalesce(d.description, '') AS d_desc, "
        "       b.kref AS b_kref, "
        "       coalesce(b.text, '') AS b_text, "
        "       coalesce(b.confidence_score, b.confidence, 0.5) AS b_conf, "
        "       r.strength AS strength"
    )

    async with driver.session() as session:
        result = await session.run(
            cypher,
            belief_krefs=weakened_belief_krefs,
            floor=DECISION_SUPPORT_FLOOR,
        )
        rows = [r async for r in result]

    out: list[LineageContradiction] = []
    for row in rows:
        strength = float(row["strength"])
        out.append(LineageContradiction(
            decision_kref=row["d_kref"],
            decision_description=row["d_desc"],
            weakened_belief_kref=row["b_kref"],
            weakened_belief_text=row["b_text"],
            new_belief_confidence=float(row["b_conf"]),
            edge_strength=strength,
            severity="high" if strength >= 0.85 else "medium",
        ))
    return out
