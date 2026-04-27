"""Ripple Reassess — confidence propagation for downstream dependents.

When a belief is revised, AnalyzeImpact (§3) identifies the cascade. Reassess
(§4) computes new confidence scores for each dependent using a four-component
weighted formula that blends prior confidence (inertia), upstream change
strength, LLM judgment, and temporal decay.

Atlas's extension over Kumiho's flag-only AnalyzeImpact: the LLM produces a
*proposal* (a delta), not a graph mutation. Mutations only happen via the
standard AGM revision operator, preserving K*2-K*6 compliance.

Spec: 06 - Ripple Algorithm Spec § 4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from atlas_core.ripple.analyze_impact import ImpactNode


log = logging.getLogger(__name__)


# ─── Confidence formula weights (calibrated empirically in Phase 3) ──────────


@dataclass(frozen=True)
class ReassessWeights:
    """Four-component additive-with-inertia confidence update.

    Phase 2 W3 reformulation of the spec formula. The original weighted-average
    formulation (α·current + β·delta + γ·llm + δ·decay where weights summed to 1)
    had a subtle bug: when no perturbation occurred, confidence decayed toward
    zero (because α<1 multiplied the prior). The corrected formulation:

        perturbation = β·strength·Δupstream + γ·llm_delta + δ·(decay - 0.5)
        new = current + (1 - α) · perturbation
        clipped to [0, 1]

    This satisfies the no-perturbation invariant: zero upstream change ⇒ zero
    confidence change. α now functions as a damping factor on the
    perturbation, not a weight on the prior. Weights will be empirically
    calibrated against BusinessMemBench in Phase 3.
    """

    alpha: float = 0.50
    """Inertia damping factor in [0, 1]. α=0 = full responsiveness to
    perturbation; α=1 = complete inertia (confidence never changes).
    Default 0.5 = perturbation halved."""

    beta: float = 0.30
    """Upstream-change responsiveness. Multiplied by edge dependency_strength
    × upstream confidence delta. Direct fraction of the upstream signal that
    propagates."""

    gamma: float = 0.15
    """LLM judgment weight. Multiplied by an LLM-produced delta in [-1, +1]
    representing whether the upstream change strengthens or weakens the
    dependent belief."""

    delta: float = 0.05
    """Temporal-decay weight. Older beliefs decay slightly when their support
    shifts. Half-life: 90 days from last evidence. Centered around 0 so
    no-decay-info contributes 0."""


DEFAULT_WEIGHTS: ReassessWeights = ReassessWeights()


# ─── LLM judgment protocol ───────────────────────────────────────────────────


@dataclass(frozen=True)
class UpstreamChange:
    """The change being propagated through the cascade — passed to the LLM."""

    upstream_kref: str
    belief_text: str
    old_confidence: float
    new_confidence: float
    evidence_summary: str = ""

    @property
    def confidence_delta(self) -> float:
        return self.new_confidence - self.old_confidence


@dataclass(frozen=True)
class LLMReassessmentDelta:
    """Structured output the LLM returns from the Reassess prompt."""

    delta: float
    """A signed delta in [-1.0, +1.0]:
       +1.0 = upstream change strongly INCREASES confidence in dependent
        0.0 = upstream change has no effect (mistakenly listed dependency)
       -1.0 = upstream change strongly DECREASES confidence in dependent"""

    rationale: str = ""


class LLMReassessor(Protocol):
    """Pluggable LLM client for the gamma component.

    Atlas defaults to a Claude-backed implementation (Phase 2 W3 includes a
    deterministic stub for testing without API keys; the production wiring
    happens in W6 when the Anthropic LLM client is integrated end-to-end).
    """

    async def evaluate(
        self,
        upstream: UpstreamChange,
        dependent_belief_text: str,
        dependent_confidence: float,
    ) -> LLMReassessmentDelta: ...


class HeuristicReassessor:
    """Default no-LLM reassessor — returns a deterministic delta proportional
    to the upstream confidence change.

    Used when no LLM client is wired (testing, offline mode). The full Atlas
    deployment uses a Claude-backed reassessor; this class is the fallback.
    """

    async def evaluate(
        self,
        upstream: UpstreamChange,
        dependent_belief_text: str,
        dependent_confidence: float,
    ) -> LLMReassessmentDelta:
        # Heuristic: upstream confidence drop → mild dependent confidence drop;
        # upstream confidence rise → mild dependent confidence rise.
        # Magnitude bounded at ±0.5 so it never dominates the formula.
        signal = upstream.confidence_delta
        bounded = max(-0.5, min(0.5, signal))
        return LLMReassessmentDelta(
            delta=bounded,
            rationale=(
                f"heuristic: upstream Δ={upstream.confidence_delta:+.2f} → "
                f"dependent delta={bounded:+.2f}"
            ),
        )


# ─── Result types ────────────────────────────────────────────────────────────


@dataclass
class ReassessmentProposal:
    """Output of Reassess for a single downstream dependent.

    PROPOSALS, not graph mutations. The adjudication routing layer (§6)
    decides whether to auto-apply via the AGM revise() operator or escalate
    for human review.
    """

    target_kref: str
    old_confidence: float
    new_confidence: float
    components: dict[str, float] = field(default_factory=dict)
    """Per-term breakdown: {alpha: ..., beta: ..., gamma: ..., delta: ...}.
    Exposed for transparency — Rich can audit *why* a confidence shifted."""

    llm_rationale: str = ""
    upstream_kref: str = ""
    depth: int = 0
    """BFS depth from the cascade origin. Earlier depths processed first."""


# ─── Algorithm ───────────────────────────────────────────────────────────────


HALF_LIFE_DAYS: float = 90.0
"""Temporal decay half-life — older beliefs lose 50% influence per 90 days."""


def _temporal_decay_factor(days_since_evidence: float | None) -> float:
    """Compute the decay factor centered around 0.5 — see Ripple Spec § 4.1.

    days=0 → 1.0 (full strength)
    days=90 → 0.5 (half strength, the half-life point)
    days=∞ → 0.0 (no influence)

    Centered around 0.5 in the formula so the δ term contributes 0 at
    half-life — neither boosting nor dragging the score.
    """
    if days_since_evidence is None:
        return 0.5  # Neutral when we don't know the age
    return 0.5 ** (days_since_evidence / HALF_LIFE_DAYS)


async def _fetch_dependent_metadata(
    driver: AsyncDriver,
    upstream_kref: str,
    dependent_kref: str,
) -> tuple[float, float | None, str]:
    """Return (dependency_strength, days_since_evidence, dependent_belief_text).

    Reads the DEPENDS_ON edge property dependency_strength (default 1.0 for
    hard deps, 0.5 for soft when not specified) and the dependent's
    confidence_score / hypothesis text.
    """
    # Kumiho-aligned DEPENDS_ON: edge from dependent → support.
    # `(dep)-[:DEPENDS_ON]->(upstream)` is the canonical direction.
    cypher = """
    MATCH (dep {kref: $dep_kref})
    OPTIONAL MATCH (dep)-[r:DEPENDS_ON]->(up {kref: $up_kref})
    WITH dep, coalesce(r.dependency_strength, 1.0) AS strength
    RETURN strength,
           dep.last_evidence_days AS days,
           coalesce(dep.hypothesis, dep.content_json, '') AS belief_text
    """
    async with driver.session() as session:
        result = await session.run(cypher, dep_kref=dependent_kref, up_kref=upstream_kref)
        record = await result.single()

    if record is None:
        return (1.0, None, "")
    return (
        float(record["strength"] or 1.0),
        record["days"],
        record["belief_text"] or "",
    )


async def reassess_dependent(
    driver: AsyncDriver,
    impacted: ImpactNode,
    upstream: UpstreamChange,
    *,
    weights: ReassessWeights = DEFAULT_WEIGHTS,
    llm: LLMReassessor | None = None,
) -> ReassessmentProposal:
    """Compute new confidence_score for a single dependent.

    Returns a PROPOSAL — does NOT mutate the graph. The adjudication routing
    layer (§6) decides whether to auto-apply via AGM revise() or escalate.

    Formula (Ripple Spec § 4.1):
      α·current + β·strength·Δupstream + γ·llm_delta + δ·(decay - 0.5)
    Clipped to [0, 1].

    Args:
        driver: Live Neo4j AsyncDriver for fetching dependent metadata
        impacted: ImpactNode from analyze_impact()
        upstream: UpstreamChange describing the originating revision
        weights: Component weights (default: 0.5/0.3/0.15/0.05)
        llm: Pluggable LLM reassessor; defaults to HeuristicReassessor

    Returns:
        ReassessmentProposal with old/new confidence + per-component
        breakdown for audit transparency.
    """
    if llm is None:
        llm = HeuristicReassessor()

    current = impacted.current_confidence if impacted.current_confidence is not None else 0.5

    strength, days_since_evidence, belief_text = await _fetch_dependent_metadata(
        driver,
        upstream_kref=upstream.upstream_kref,
        dependent_kref=impacted.kref,
    )

    # Perturbation components (signed, can be positive or negative)
    beta_term = weights.beta * strength * upstream.confidence_delta
    llm_response = await llm.evaluate(
        upstream=upstream,
        dependent_belief_text=belief_text,
        dependent_confidence=current,
    )
    gamma_term = weights.gamma * llm_response.delta
    decay = _temporal_decay_factor(days_since_evidence)
    delta_term = weights.delta * (decay - 0.5)

    perturbation = beta_term + gamma_term + delta_term
    damped_perturbation = (1.0 - weights.alpha) * perturbation

    raw = current + damped_perturbation
    new_confidence = max(0.0, min(1.0, raw))

    return ReassessmentProposal(
        target_kref=impacted.kref,
        old_confidence=current,
        new_confidence=new_confidence,
        components={
            "current": current,
            "beta": beta_term,
            "gamma": gamma_term,
            "delta": delta_term,
            "perturbation": perturbation,
            "damped": damped_perturbation,
            "raw": raw,
        },
        llm_rationale=llm_response.rationale,
        upstream_kref=impacted.upstream_kref,
        depth=impacted.depth,
    )


async def reassess_cascade(
    driver: AsyncDriver,
    impacted_nodes: list[ImpactNode],
    upstream: UpstreamChange,
    *,
    weights: ReassessWeights = DEFAULT_WEIGHTS,
    llm: LLMReassessor | None = None,
) -> list[ReassessmentProposal]:
    """Reassess every node in a cascade. Returns proposals in BFS order.

    Higher-confidence layers (lower depth) processed first per Ripple Spec
    § 3.1, preventing low-confidence cascades from contaminating
    downstream beliefs in subsequent reassessment rounds.
    """
    proposals: list[ReassessmentProposal] = []
    for node in sorted(impacted_nodes, key=lambda n: n.depth):
        proposal = await reassess_dependent(
            driver, node, upstream, weights=weights, llm=llm
        )
        proposals.append(proposal)

    log.info(
        "Reassess cascade: origin=%s, %d proposals, mean Δ=%+.3f",
        upstream.upstream_kref,
        len(proposals),
        (
            sum(p.new_confidence - p.old_confidence for p in proposals) / len(proposals)
            if proposals
            else 0.0
        ),
    )

    return proposals
