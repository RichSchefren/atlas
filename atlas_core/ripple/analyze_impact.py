"""Ripple AnalyzeImpact — recursive Depends_On BFS traversal with cycle detection.

When a belief is revised, AnalyzeImpact identifies every downstream dependent
that may need re-evaluation. Atlas's extension over Kumiho's spec: cycle
detection (visited-set + max-depth + max-nodes guards) so the traversal
terminates on circular DEPENDS_ON graphs without infinite recursion.

Key invariant from Kumiho § 7.6: AnalyzeImpact is structural traversal, NOT
logical inference. Outputs never enter the belief base; they're proposals for
the Reassess step (06 - Ripple Algorithm Spec § 4).

Spec: 06 - Ripple Algorithm Spec § 3
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from atlas_core.revision.uri import Kref

if TYPE_CHECKING:
    from neo4j import AsyncDriver


log = logging.getLogger(__name__)


# ─── Bounds (Phase 2 W3 defaults — calibrated empirically in Phase 3) ────────

MAX_DEPTH_DEFAULT: int = 10
"""Maximum Depends_On hops Ripple traverses. Kumiho default; Rich's graph has
b≈3-5, d≈3-5 typical so the 10-hop ceiling is generous."""

MAX_NODES_DEFAULT: int = 5000
"""Hard cap on total nodes touched. Prevents runaway propagation if a graph
has unexpected fan-out. Per Ripple Spec § 3.1."""


# ─── Result types ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImpactNode:
    """A single downstream dependent identified by AnalyzeImpact.

    Returned in BFS order (depth ascending) so the Reassess step can process
    higher-confidence layers first, preventing low-confidence cascades from
    contaminating downstream beliefs.
    """

    kref: str
    """Full kref URI string of the impacted dependent."""

    types: tuple[str, ...]
    """Neo4j labels on the dependent — e.g., ('AtlasRevision',) or ('AtlasItem',)."""

    current_confidence: Optional[float]
    """Current confidence_score on the node, or None if not a typed belief."""

    depth: int
    """BFS depth from the revised origin (1 = direct dependent, 2+ = transitive)."""

    upstream_kref: str
    """The immediate upstream node that connected this dependent into the cascade."""


@dataclass
class AnalyzeImpactResult:
    """Aggregate result of an AnalyzeImpact traversal."""

    impacted: list[ImpactNode] = field(default_factory=list)
    """Downstream dependents in BFS order (shallowest first)."""

    cycles_detected: list[str] = field(default_factory=list)
    """Edge descriptions where a cycle was detected — surfaced to adjudication
    queue per Ripple Spec § 3.2."""

    nodes_visited: int = 0
    """Total nodes touched. Compare against max_nodes to detect saturation."""

    truncated: bool = False
    """True when traversal hit max_nodes before exhausting the frontier."""


# ─── Algorithm ───────────────────────────────────────────────────────────────


async def analyze_impact(
    driver: AsyncDriver,
    revised_kref: Kref | str,
    *,
    max_depth: int = MAX_DEPTH_DEFAULT,
    max_nodes: int = MAX_NODES_DEFAULT,
) -> AnalyzeImpactResult:
    """Compute the downstream dependency cascade from a revised node.

    Algorithm (Ripple Spec § 3.1):
      visited ← {revised_kref}
      queue ← [(revised_kref, 0)]
      while queue not empty AND |impacted| < max_nodes:
        (current, depth) ← queue.popleft()
        if depth >= max_depth: continue
        for child in MATCH (current)-[:DEPENDS_ON]->(child):
          if child in visited:
            cycles.append("current -> child")
            continue
          visited ← visited ∪ {child}
          impacted.append(ImpactNode(child, depth+1, ...))
          queue.append((child, depth+1))

    Cycle detection (Atlas extension over Kumiho): visited-set tracks every
    node Ripple has seen in this traversal. Repeat encounters are recorded as
    cycle edges and skipped — preserves termination guarantees.

    Args:
        driver: Live Neo4j AsyncDriver
        revised_kref: kref of the belief that was just revised (Kref or string)
        max_depth: bound on BFS depth (default 10)
        max_nodes: hard cap on impacted nodes (default 5000)

    Returns:
        AnalyzeImpactResult with impacted nodes (BFS order), cycles, and
        truncation flag. The Reassess step consumes this result.
    """
    origin_kref = revised_kref if isinstance(revised_kref, str) else revised_kref.to_string()

    visited: set[str] = {origin_kref}
    cycles: list[str] = []
    impacted: list[ImpactNode] = []
    truncated = False

    queue: deque[tuple[str, int]] = deque([(origin_kref, 0)])

    # DEPENDS_ON semantic (Kumiho § 6.5): edge points FROM dependent TO support.
    # `(dependent)-[:DEPENDS_ON]->(support)` reads "dependent depends on support".
    # When a support node is revised, we traverse INCOMING DEPENDS_ON edges to
    # find every dependent that may need reassessment.
    cypher = """
    MATCH (current {kref: $current_kref})<-[:DEPENDS_ON]-(child)
    WHERE coalesce(child.deprecated, false) = false
    RETURN child.kref AS child_kref,
           labels(child) AS child_labels,
           child.confidence_score AS child_confidence
    """

    async with driver.session() as session:
        while queue:
            if len(impacted) >= max_nodes:
                truncated = True
                break

            current_kref, depth = queue.popleft()

            if depth >= max_depth:
                continue

            result = await session.run(cypher, current_kref=current_kref)
            children = await result.data()

            for record in children:
                child_kref = record["child_kref"]
                if child_kref is None:
                    continue

                if child_kref in visited:
                    cycles.append(f"{current_kref} -> {child_kref}")
                    continue

                visited.add(child_kref)
                impacted.append(
                    ImpactNode(
                        kref=child_kref,
                        types=tuple(record["child_labels"] or ()),
                        current_confidence=record["child_confidence"],
                        depth=depth + 1,
                        upstream_kref=current_kref,
                    )
                )
                queue.append((child_kref, depth + 1))

                if len(impacted) >= max_nodes:
                    truncated = True
                    break

            if truncated:
                break

    log.info(
        "AnalyzeImpact origin=%s depth_max=%d nodes=%d cycles=%d truncated=%s",
        origin_kref,
        max_depth,
        len(impacted),
        len(cycles),
        truncated,
    )

    return AnalyzeImpactResult(
        impacted=impacted,
        cycles_detected=cycles,
        nodes_visited=len(visited),
        truncated=truncated,
    )
