"""Neo4j graph schema — uniqueness constraints for belief-node identity.

Atlas keys its property-graph nodes on stable URIs (``kref`` / ``root_kref``)
and, for ingested beliefs, on ``candidate_id``.  Every production writer MERGEs
on one of these keys expecting it to name *exactly one* node:

    materializer  MERGE (:AtlasItem {kref})       / (:AtlasItem:Belief {candidate_id})
    agm.revise    MERGE (:AtlasItem {root_kref})

Neo4j does **not** enforce that expectation on its own: without a uniqueness
constraint a MERGE's match-or-create step is not atomic across sessions, so two
concurrent writers can each create a node for the same key.  Once a duplicate
exists it corrupts every downstream write — a later ``MERGE (:AtlasItem {kref})
SET ...`` matches *both* nodes and fans its update across all of them — and, at
that point, the constraint can no longer be added.  The protection has to be in
place *before* the first write.

Scope note: only the three keys written via idempotent MERGE are constrained
here.  ``:AtlasRevision {kref}`` is deliberately *not* constrained yet — AGM
``revise`` / the resolver mint revisions with ``CREATE`` (``agm.py`` ~L158),
which legitimately produces same-kref revisions on re-revision of identical
content; adding that constraint requires first converting those writes to an
idempotent MERGE (tracked as a separate identity-contract change).

``ensure_schema`` installs the constraints idempotently (``IF NOT EXISTS``), so
it is safe to call on every startup / batch run.  Each uniqueness constraint is
backed by an automatically-maintained range index, which also gives labelled
``kref`` lookups an index seek instead of a full-store scan.

Uniqueness constraints are property-scoped: a node that lacks the constrained
property is simply not covered, so the ``kref`` and ``root_kref`` constraints on
``:AtlasItem`` coexist cleanly (a materialized subject has ``kref`` but no
``root_kref``; an AGM root node has ``root_kref`` but no ``kref``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import AsyncDriver

# (constraint_name, node_label, property_key)
BELIEF_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    ("atlas_item_kref_unique", "AtlasItem", "kref"),
    ("atlas_item_root_kref_unique", "AtlasItem", "root_kref"),
    ("belief_candidate_id_unique", "Belief", "candidate_id"),
)


def constraint_statements() -> list[str]:
    """Return the idempotent ``CREATE CONSTRAINT`` statements for the schema."""
    return [
        f"CREATE CONSTRAINT {name} IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        for name, label, prop in BELIEF_CONSTRAINTS
    ]


async def ensure_schema(driver: AsyncDriver) -> None:
    """Install Atlas's belief-node uniqueness constraints if absent.

    Idempotent and cheap: each statement uses ``IF NOT EXISTS`` so repeated
    calls are no-ops.  Call it before any graph write path (ingestion /
    materialization / revision) so duplicate belief nodes can never be minted.
    """
    async with driver.session() as session:
        for statement in constraint_statements():
            await session.run(statement)
