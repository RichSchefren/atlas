"""AGM selection function (Kumiho Definition 7.6).

Targets(A, τ) = {(t, r) | t ∈ dom(τ), r = τ(t), A ∈ φ(r)}

Content-based, exhaustive: targets every tagged revision whose content explicitly
contains the proposition A. Deterministic. Computable in O(|dom(τ)|) by scanning
tag-referenced revisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas_core.revision.uri import Kref


@dataclass(frozen=True)
class SelectionTarget:
    """A (tag, revision) pair targeted by content-based selection."""

    tag_name: str
    revision_kref: Kref


async def select_targets(
    driver: Any,
    proposition: str,
    namespace: str = "Atlas",
) -> list[SelectionTarget]:
    """Compute Targets(A, τ) — all tag/revision pairs where A is explicitly present.

    Phase 2 Week 1: STUB. Week 2: Cypher impl using full-text search on revision
    summaries + extracted facts.

    Implementation will use:
      MATCH (t:Tag {project: $namespace})-[:POINTS_TO]->(r:Revision)
      WHERE r.searchable_content CONTAINS $proposition
        OR EXISTS { (r)-[:CONTAINS_FACT]->(f) WHERE f.text = $proposition }
      RETURN t.name, r.kref
    """
    raise NotImplementedError(
        "AGM select_targets() — Phase 2 Week 2. Spec: Kumiho Definition 7.6"
    )
