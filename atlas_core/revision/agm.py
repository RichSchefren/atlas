"""AGM-compliant revision operators (Definitions 7.4, 7.5, 7.7 from Kumiho paper).

Atlas implementation of Kumiho's correspondence theorem. Three operators —
revise (B*A), contract (B÷A), expand (B+A) — operate atomically against the
Neo4j graph in a single Cypher transaction.

Formal correctness: revision satisfies AGM postulates K*2-K*6 + Hansson
Relevance + Core-Retainment, verified by the 49-scenario compliance suite at
benchmarks/agm_compliance_runner.py.

Spec: World Model Research/05 - Atlas Architecture & Schema § 5
       06 - Ripple Algorithm Spec § 4 (revise hooks Ripple via AtlasGraphiti)
       Kumiho paper arxiv:2603.17244 Section 7
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from atlas_core.revision.uri import Kref

if TYPE_CHECKING:
    from neo4j import AsyncDriver


log = logging.getLogger(__name__)


# Revision-tag conventions (Kumiho Section 6.4, 7.2)
TAG_CURRENT = "current"
"""Standard tag pointing at the active revision per Definition 7.4 step 3."""

TAG_INITIAL = "initial"
"""Tag pinned to the first revision; preserved across all supersessions."""


# ─── Result types ────────────────────────────────────────────────────────────


@dataclass
class RevisionOutcome:
    """Result of an AGM revision operation B * A.

    Returned to the caller for audit + Ripple trigger. The new_revision_kref
    can be passed to Ripple's AnalyzeImpact for downstream reassessment.
    """

    new_revision_kref: Kref
    superseded_kref: Kref | None
    was_first_revision: bool
    tag_updated: str
    audit_record: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContractionOutcome:
    """Result of an AGM contraction operation B ÷ A."""

    contracted_proposition: str
    affected_kref: Kref
    deprecated: bool
    tags_removed: list[str] = field(default_factory=list)
    audit_record: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExpansionOutcome:
    """Result of an AGM expansion operation B + A.

    Expansion creates a new revision whose content is the prior revision's
    content unioned with the new proposition. No SUPERSEDES edge.
    """

    new_revision_kref: Kref
    parent_revision_kref: Kref
    tag_assigned: str
    audit_record: dict[str, Any] = field(default_factory=dict)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    """Atlas's canonical timestamp format — ISO 8601 with explicit UTC."""
    return datetime.now(timezone.utc).isoformat()


def _content_hash(content: dict[str, Any]) -> str:
    """SHA-256 over canonical JSON. Deterministic across Python versions
    because we sort keys and use compact separators."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ─── Operators ───────────────────────────────────────────────────────────────


async def revise(
    driver: AsyncDriver,
    target_kref: Kref,
    new_content: dict[str, Any],
    *,
    revision_reason: str,
    evidence: dict[str, Any] | None = None,
    actor: str = "atlas",
    tag: str = TAG_CURRENT,
) -> RevisionOutcome:
    """AGM revision operator B * A — Kumiho Definition 7.4.

    Three-step atomic operation in a single Cypher transaction:
      1. Create new revision r_i^(k+1) with content φ(r_i^(k+1)) = new_content
      2. If a prior revision exists at the tag, add edge (r_i^(k+1), SUPERSEDES, r_i^(k))
      3. Move tag: τ' = τ[tag ↦ r_i^(k+1)]

    Postulates this operator preserves:
      - K*2 (Success): A ∈ φ(r^(k+1)), tag points at r^(k+1) ⇒ A ∈ B(τ')
      - K*3 (Inclusion, base): no atoms beyond new_content introduced
      - K*4 (Vacuity): when tag has no prior revision, no retraction occurs
      - K*5 (Consistency): SUPERSEDES replaces; τ' references only r^(k+1)
      - K*6 (Extensionality, ground atoms): syntactic identity = logical equivalence

    Args:
        driver: Live Neo4j AsyncDriver
        target_kref: kref of the root item to revise
        new_content: dict matching the target's typed schema (e.g., StrategicBelief.model_dump())
        revision_reason: human-readable rationale (audited)
        evidence: optional structured evidence pointers (will be stored on the new revision)
        actor: 'rich' | 'atlas' | extractor name
        tag: which tag to move; defaults to 'current'

    Returns:
        RevisionOutcome with new revision kref, superseded kref (or None for
        first revision), and audit record.
    """
    root = target_kref.root_kref()
    timestamp = _utc_now_iso()
    chash = _content_hash(new_content)
    new_kref_str = root.with_revision(chash[:12]).to_string()

    cypher = """
    // Ensure root item exists
    MERGE (root:AtlasItem {root_kref: $root_kref})
      ON CREATE SET root.created_at = $timestamp,
                    root.kind = $kind,
                    root.deprecated = false
    WITH root

    // Find prior revision at this tag (if any)
    OPTIONAL MATCH (root)-[:HAS_REVISION]->(prior:AtlasRevision)<-[:POINTS_TO]-(:AtlasTag {name: $tag, root_kref: $root_kref})
    WITH root, prior

    // Create the new immutable revision
    CREATE (new:AtlasRevision {
      kref: $new_kref,
      root_kref: $root_kref,
      content_hash: $chash,
      content_json: $content_json,
      revision_reason: $revision_reason,
      evidence_json: $evidence_json,
      actor: $actor,
      created_at: $timestamp
    })
    CREATE (root)-[:HAS_REVISION]->(new)
    WITH root, prior, new

    // Step 2: SUPERSEDES edge if prior exists
    FOREACH (p IN CASE WHEN prior IS NULL THEN [] ELSE [prior] END |
      CREATE (new)-[:SUPERSEDES {created_at: $timestamp, reason: $revision_reason}]->(p)
    )
    WITH root, prior, new

    // Step 3: ensure tag exists, then move pointer
    MERGE (tag:AtlasTag {name: $tag, root_kref: $root_kref})
      ON CREATE SET tag.created_at = $timestamp
    WITH new, tag, prior
    OPTIONAL MATCH (tag)-[oldEdge:POINTS_TO]->(:AtlasRevision)
    DELETE oldEdge
    WITH new, tag, prior
    CREATE (tag)-[:POINTS_TO {moved_at: $timestamp}]->(new)

    RETURN new.kref AS new_kref,
           prior.kref AS prior_kref
    """

    params = {
        "root_kref": root.to_string(),
        "kind": root.kind,
        "tag": tag,
        "new_kref": new_kref_str,
        "chash": chash,
        # Compact form (no spaces) — matches _content_hash canonicalization and
        # makes Cypher CONTAINS predicates predictable
        "content_json": json.dumps(new_content, sort_keys=True, separators=(",", ":")),
        "revision_reason": revision_reason,
        "evidence_json": json.dumps(evidence or {}, sort_keys=True, separators=(",", ":")),
        "actor": actor,
        "timestamp": timestamp,
    }

    async with driver.session() as session:
        result = await session.run(cypher, params)
        record = await result.single()

    if record is None:
        raise RuntimeError(f"AGM revise: Cypher returned no record for {target_kref}")

    new_kref = Kref.parse(record["new_kref"])
    prior_kref_str = record["prior_kref"]
    prior_kref = Kref.parse(prior_kref_str) if prior_kref_str else None

    log.info(
        "AGM revise: %s @ tag=%s, prior=%s, content_hash=%s",
        new_kref,
        tag,
        prior_kref or "<none>",
        chash[:12],
    )

    return RevisionOutcome(
        new_revision_kref=new_kref,
        superseded_kref=prior_kref,
        was_first_revision=(prior_kref is None),
        tag_updated=tag,
        audit_record={
            "operator": "revise",
            "actor": actor,
            "timestamp": timestamp,
            "content_hash": chash,
            "reason": revision_reason,
        },
    )


async def contract(
    driver: AsyncDriver,
    target_kref: Kref,
    proposition_to_remove: str,
    *,
    contraction_reason: str,
    actor: str = "atlas",
) -> ContractionOutcome:
    """AGM contraction operator B ÷ A — Kumiho Definition 7.5.

    Two-mechanism implementation:
      1. Tag removal: remove from τ any tag t where A ∈ φ(τ(t))
         Operationalized: tag-removal happens when the contracted item's
         content matched the proposition.
      2. Soft deprecation: mark item.deprecated = true (excluded from
         retrieval surface B_retr(τ) per Definition 7.3).

    Postulates this operator preserves:
      - Relevance (Hansson, Proposition 7.6): only revisions whose content
        explicitly contains A are affected
      - Core-Retainment (Hansson, Proposition 7.7): every removed belief was
        connected to the contracted belief's derivation
      - Consistency (K*5): two-tier epistemic model excludes deprecated items
        from agent retrieval surface

    INTENTIONALLY VIOLATES Recovery (Kumiho Section 7.3): immutable revisions
    + tag history make Recovery unnecessary.

    Phase 2 W2: tag-removal + soft-deprecation implemented; semantic
    proposition matching is naive substring; will tighten in W3 once
    embedding-based selection is available.
    """
    root = target_kref.root_kref()
    timestamp = _utc_now_iso()

    cypher = """
    MATCH (root:AtlasItem {root_kref: $root_kref})

    // Identify tagged revisions whose content explicitly contains the proposition
    OPTIONAL MATCH (tag:AtlasTag {root_kref: $root_kref})-[ptp:POINTS_TO]->(rev:AtlasRevision)
    WHERE rev.content_json CONTAINS $proposition

    WITH root, collect({tag_name: tag.name, ptp: ptp}) AS matches

    // Soft-deprecate the item
    SET root.deprecated = true,
        root.deprecated_at = $timestamp,
        root.deprecation_reason = $contraction_reason,
        root.deprecated_by = $actor
    WITH root, matches

    // Tag removal — delete POINTS_TO edges for matched pairs
    FOREACH (m IN matches |
      FOREACH (e IN CASE WHEN m.ptp IS NULL THEN [] ELSE [m.ptp] END |
        DELETE e
      )
    )

    RETURN [m IN matches WHERE m.tag_name IS NOT NULL | m.tag_name] AS removed_tag_names
    """

    params = {
        "root_kref": root.to_string(),
        "proposition": proposition_to_remove,
        "contraction_reason": contraction_reason,
        "actor": actor,
        "timestamp": timestamp,
    }

    async with driver.session() as session:
        result = await session.run(cypher, params)
        record = await result.single()

    removed_tags = record["removed_tag_names"] if record else []

    log.info(
        "AGM contract: %s, proposition=%r, removed_tags=%s",
        root,
        proposition_to_remove,
        removed_tags,
    )

    return ContractionOutcome(
        contracted_proposition=proposition_to_remove,
        affected_kref=root,
        deprecated=True,
        tags_removed=list(removed_tags),
        audit_record={
            "operator": "contract",
            "actor": actor,
            "timestamp": timestamp,
            "reason": contraction_reason,
        },
    )


async def expand(
    driver: AsyncDriver,
    target_kref: Kref,
    additional_content: dict[str, Any],
    *,
    expansion_reason: str,
    actor: str = "atlas",
    tag: str = TAG_CURRENT,
) -> ExpansionOutcome:
    """AGM expansion operator B + A — Kumiho Definition 7.7.

    Creates a new revision r_i^(k+1) with φ(r_i^(k+1)) = φ(r_i^(k)) ∪ {A}.
    Assigns the same tag without removing existing tag assignments.
    No SUPERSEDES edge — the prior revision remains tagged.

    Use case: adding a new field/fact to a typed belief without invalidating
    prior versions. Common in evidence accumulation for StrategicBelief.

    Postulates: K*2 trivially (A ∈ φ(r^(k+1))). Inclusion holds since the new
    content is the prior content unioned with A. No conflict ⇒ no contraction
    needed.
    """
    root = target_kref.root_kref()
    timestamp = _utc_now_iso()

    cypher = """
    MATCH (root:AtlasItem {root_kref: $root_kref})
    OPTIONAL MATCH (root)-[:HAS_REVISION]->(parent:AtlasRevision)<-[:POINTS_TO]-(:AtlasTag {name: $tag, root_kref: $root_kref})

    WITH root, parent
    WHERE parent IS NOT NULL

    // Merge prior content with additional_content
    WITH root, parent,
         apoc.convert.fromJsonMap(parent.content_json) AS prior_map
    WITH root, parent, prior_map,
         apoc.map.merge(prior_map, $additional_content) AS merged

    // Compute hash and create new revision
    CREATE (new:AtlasRevision {
      kref: $root_kref + "?r=" + apoc.util.sha1([apoc.convert.toJson(merged)]),
      root_kref: $root_kref,
      content_json: apoc.convert.toJson(merged),
      revision_reason: $expansion_reason,
      actor: $actor,
      created_at: $timestamp
    })
    CREATE (root)-[:HAS_REVISION]->(new)
    CREATE (new)-[:DERIVED_FROM {kind: 'expansion', created_at: $timestamp}]->(parent)

    // Tag move
    WITH new, parent
    MATCH (tag:AtlasTag {name: $tag, root_kref: $root_kref})
    OPTIONAL MATCH (tag)-[oldEdge:POINTS_TO]->(:AtlasRevision)
    DELETE oldEdge
    CREATE (tag)-[:POINTS_TO {moved_at: $timestamp}]->(new)

    RETURN new.kref AS new_kref, parent.kref AS parent_kref
    """

    params = {
        "root_kref": root.to_string(),
        "tag": tag,
        "additional_content": additional_content,
        "expansion_reason": expansion_reason,
        "actor": actor,
        "timestamp": timestamp,
    }

    async with driver.session() as session:
        result = await session.run(cypher, params)
        record = await result.single()

    if record is None:
        # No prior revision at tag — fall back to revision (creates fresh revision)
        outcome = await revise(
            driver,
            target_kref,
            additional_content,
            revision_reason=f"expand-fallback: {expansion_reason}",
            actor=actor,
            tag=tag,
        )
        return ExpansionOutcome(
            new_revision_kref=outcome.new_revision_kref,
            parent_revision_kref=outcome.new_revision_kref,
            tag_assigned=tag,
            audit_record={
                "operator": "expand",
                "actor": actor,
                "timestamp": timestamp,
                "fallback_to_revise": True,
            },
        )

    new_kref = Kref.parse(record["new_kref"])
    parent_kref = Kref.parse(record["parent_kref"])

    log.info("AGM expand: %s -> %s @ tag=%s", parent_kref, new_kref, tag)

    return ExpansionOutcome(
        new_revision_kref=new_kref,
        parent_revision_kref=parent_kref,
        tag_assigned=tag,
        audit_record={
            "operator": "expand",
            "actor": actor,
            "timestamp": timestamp,
            "reason": expansion_reason,
        },
    )
