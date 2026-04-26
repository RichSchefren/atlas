"""Type-aware contradiction detection — Ripple Spec § 5.

After Reassess produces proposals, check whether the new confidence states
create contradictions with existing high-confidence beliefs in the graph.

Atlas's distinguishing feature over generic memory systems: per-entity-type
contradiction rules. Different domain types fail in different ways:

  StrategicBelief ↔ StrategicBelief — both > 0.7 with CONTRADICTS edge
  Decision ↔ StrategicBelief        — Decision rests on belief whose conf <0.5
  Person.financial_relationship    — same counterparty, conflicting tier
  Commitment ↔ Commitment           — same owner+description, different deadline
  Price ↔ Price (Phase 2)           — same Program, overlapping validity windows

Spec: 06 - Ripple Algorithm Spec § 5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from atlas_core.ripple.reassess import ReassessmentProposal


log = logging.getLogger(__name__)


# ─── Thresholds (calibrated empirically in Phase 3) ──────────────────────────

STRATEGIC_BELIEF_CONFIDENCE_FLOOR: float = 0.70
"""Both StrategicBeliefs must exceed this confidence for a CONTRADICTS edge to
constitute an active conflict. Below this floor, the contradicting beliefs are
considered tentative and don't fire a contradiction event."""

STRATEGIC_BELIEF_HIGH_SEVERITY_FLOOR: float = 0.85
"""When both contradicting beliefs exceed this confidence, severity escalates
from medium to high — surfaces with extra urgency in the adjudication queue."""

DECISION_SUPPORT_FLOOR: float = 0.50
"""Below this confidence, a SUPPORTS belief is considered too weak to support
a Decision. Surfaces the decision as 'unsupported' contradiction."""


# ─── Taxonomy ────────────────────────────────────────────────────────────────


class ContradictionCategory(str, Enum):
    """Categories distinguish how the contradiction was detected and how
    Adjudication routing (Ripple Spec § 6) should handle it."""

    STRATEGIC_BELIEF_CONFLICT = "strategic_belief_conflict"
    """Two StrategicBeliefs both above confidence floor, linked by
    CONTRADICTS edge."""

    DECISION_UNSUPPORTED = "decision_unsupported"
    """A Decision's SUPPORTS belief has dropped below the support floor."""

    FINANCIAL_RELATIONSHIP_TIER_CONFLICT = "financial_tier_conflict"
    """Same counterparty appears with conflicting financial tier assignments."""

    COMMITMENT_DEADLINE_CONFLICT = "commitment_deadline_conflict"
    """Same owner+description Commitment exists with different deadlines."""


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ContradictionPair:
    """A detected contradiction between a proposal target and another node."""

    proposal_kref: str
    """The kref of the reassessed dependent that triggered detection."""

    opposed_kref: str
    """The kref of the conflicting node."""

    category: ContradictionCategory
    severity: Severity
    rationale: str
    """Human-readable explanation surfaced in the Obsidian adjudication queue."""


# ─── Type detection ──────────────────────────────────────────────────────────


def _primary_type(types: tuple[str, ...]) -> str | None:
    """Return the first non-Atlas-base label, which encodes the entity type."""
    for label in types:
        if label not in {"AtlasItem", "AtlasRevision", "AtlasTag", "Entity"}:
            return label
    # Fall back to first label if all are base
    return types[0] if types else None


# ─── Per-type detectors ──────────────────────────────────────────────────────


async def _detect_strategic_belief_conflict(
    driver: AsyncDriver,
    proposal: ReassessmentProposal,
) -> list[ContradictionPair]:
    """Find StrategicBeliefs linked by CONTRADICTS that both exceed the
    confidence floor after this reassessment."""
    if proposal.new_confidence < STRATEGIC_BELIEF_CONFIDENCE_FLOOR:
        return []

    cypher = """
    MATCH (a {kref: $kref})-[:CONTRADICTS]-(b)
    WHERE coalesce(b.deprecated, false) = false
      AND b.confidence_score >= $floor
    RETURN b.kref AS opposed_kref,
           b.confidence_score AS opposed_confidence,
           coalesce(b.hypothesis, '') AS opposed_hypothesis
    """
    contradictions: list[ContradictionPair] = []
    async with driver.session() as session:
        result = await session.run(
            cypher,
            kref=proposal.target_kref,
            floor=STRATEGIC_BELIEF_CONFIDENCE_FLOOR,
        )
        opposed_records = await result.data()

    for record in opposed_records:
        opposed_conf = record["opposed_confidence"]
        is_high_severity = (
            min(proposal.new_confidence, opposed_conf)
            >= STRATEGIC_BELIEF_HIGH_SEVERITY_FLOOR
        )
        contradictions.append(
            ContradictionPair(
                proposal_kref=proposal.target_kref,
                opposed_kref=record["opposed_kref"],
                category=ContradictionCategory.STRATEGIC_BELIEF_CONFLICT,
                severity=Severity.HIGH if is_high_severity else Severity.MEDIUM,
                rationale=(
                    f"Both beliefs exceed {STRATEGIC_BELIEF_CONFIDENCE_FLOOR:.2f} "
                    f"confidence ({proposal.new_confidence:.2f} vs "
                    f"{opposed_conf:.2f}) but are linked by CONTRADICTS edge."
                ),
            )
        )
    return contradictions


async def _detect_decision_unsupported(
    driver: AsyncDriver,
    proposal: ReassessmentProposal,
) -> list[ContradictionPair]:
    """Detect when this proposal is a Decision whose SUPPORTS belief just
    dropped below the support floor."""
    cypher = """
    MATCH (d {kref: $kref})-[:SUPPORTS]->(b)
    WHERE coalesce(b.deprecated, false) = false
      AND b.confidence_score < $floor
    RETURN b.kref AS opposed_kref,
           b.confidence_score AS opposed_confidence
    """
    contradictions: list[ContradictionPair] = []
    async with driver.session() as session:
        result = await session.run(
            cypher,
            kref=proposal.target_kref,
            floor=DECISION_SUPPORT_FLOOR,
        )
        records = await result.data()

    for record in records:
        contradictions.append(
            ContradictionPair(
                proposal_kref=proposal.target_kref,
                opposed_kref=record["opposed_kref"],
                category=ContradictionCategory.DECISION_UNSUPPORTED,
                severity=Severity.HIGH,
                rationale=(
                    f"Decision rests on belief at confidence "
                    f"{record['opposed_confidence']:.2f}, below "
                    f"{DECISION_SUPPORT_FLOOR:.2f} support floor."
                ),
            )
        )
    return contradictions


async def _detect_commitment_deadline_conflict(
    driver: AsyncDriver,
    proposal: ReassessmentProposal,
) -> list[ContradictionPair]:
    """Two open Commitments for the same owner with the same description but
    different deadlines is a conflict."""
    cypher = """
    MATCH (c {kref: $kref})
    WHERE c.status = 'open'
    OPTIONAL MATCH (other:AtlasItem)
    WHERE other.kref <> c.kref
      AND coalesce(other.deprecated, false) = false
      AND other.status = 'open'
      AND other.owner_kref = c.owner_kref
      AND other.description = c.description
      AND other.deadline IS NOT NULL
      AND c.deadline IS NOT NULL
      AND other.deadline <> c.deadline
    RETURN other.kref AS opposed_kref,
           other.deadline AS opposed_deadline,
           c.deadline AS our_deadline
    """
    contradictions: list[ContradictionPair] = []
    async with driver.session() as session:
        result = await session.run(cypher, kref=proposal.target_kref)
        records = await result.data()

    for record in records:
        if record["opposed_kref"] is None:
            continue
        contradictions.append(
            ContradictionPair(
                proposal_kref=proposal.target_kref,
                opposed_kref=record["opposed_kref"],
                category=ContradictionCategory.COMMITMENT_DEADLINE_CONFLICT,
                severity=Severity.MEDIUM,
                rationale=(
                    f"Two open Commitments same owner+description but "
                    f"different deadlines: {record['our_deadline']} vs "
                    f"{record['opposed_deadline']}."
                ),
            )
        )
    return contradictions


# ─── Top-level dispatcher ────────────────────────────────────────────────────


async def detect_contradictions(
    driver: AsyncDriver,
    proposals: list[ReassessmentProposal],
) -> list[ContradictionPair]:
    """For each proposal, run the per-type contradiction detectors that apply
    to its entity type. Returns aggregated contradiction list.

    Type dispatch is read from the node's labels in the graph. A proposal
    whose target is a StrategicBelief runs only StrategicBelief rules; a
    Decision runs only Decision rules; etc.
    """
    contradictions: list[ContradictionPair] = []

    for proposal in proposals:
        # Read the target's type from the graph
        cypher = """
        MATCH (n {kref: $kref})
        RETURN labels(n) AS types,
               coalesce(n.deprecated, false) AS deprecated
        """
        async with driver.session() as session:
            result = await session.run(cypher, kref=proposal.target_kref)
            record = await result.single()

        if record is None or record["deprecated"]:
            continue

        types = tuple(record["types"] or ())
        primary = _primary_type(types) or ""

        # Heuristic dispatch by kref kind suffix or label.
        # Phase 2 W3: kref kind suffix (.belief, .decision, .commitment).
        # Phase 2 W4 will add explicit Pydantic-class labels.
        kref_str = proposal.target_kref
        kind = ""
        if "?" in kref_str:
            kref_str = kref_str.split("?", 1)[0]
        if "." in kref_str.rsplit("/", 1)[-1]:
            kind = kref_str.rsplit(".", 1)[-1]

        # Run all detectors that match this proposal's type.
        # An entity may match multiple categories (e.g., StrategicBelief and
        # Decision both have evidence chains).
        if kind == "belief" or "StrategicBelief" in types:
            contradictions.extend(
                await _detect_strategic_belief_conflict(driver, proposal)
            )
        if kind == "decision" or "Decision" in types:
            contradictions.extend(
                await _detect_decision_unsupported(driver, proposal)
            )
        if kind == "commitment" or "Commitment" in types:
            contradictions.extend(
                await _detect_commitment_deadline_conflict(driver, proposal)
            )

    log.info(
        "Contradiction detection: %d proposals → %d contradictions",
        len(proposals),
        len(contradictions),
    )

    return contradictions
