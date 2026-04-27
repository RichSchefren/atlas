"""Ripple engine — the integrated orchestrator.

Wires the four Ripple stages — analyze_impact → reassess → contradiction
→ adjudication routing — into one entry point. The pieces have lived in
their own modules from day one (analyze_impact.py, reassess.py,
contradiction.py, adjudication.py); this file is what binds them so a
caller invokes ONE method and gets the full cascade.

Pipeline:
  1. AnalyzeImpact(origin_kref) → downstream Depends_On dependents D
  2. For each d in D: compute new confidence via the additive-with-
     damping formula in reassess.py (α + β·strength·Δ + γ·llm + δ·decay)
  3. Type-aware contradiction detection across the proposal set
  4. Route each proposal: AUTO_APPLY | STRATEGIC_REVIEW | CORE_PROTECTED
  5. (Optional) emit a /events SSE notification for the live viz
  6. Return a structured CascadeResult so callers can audit

Spec: notes/06 - Ripple Algorithm Spec.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from atlas_core.ripple.adjudication import (
    AdjudicationRoute,
    RoutingDecision,
    route_proposal,
)
from atlas_core.ripple.analyze_impact import (
    AnalyzeImpactResult,
    analyze_impact,
)
from atlas_core.ripple.contradiction import (
    ContradictionPair,
    detect_contradictions,
)
from atlas_core.ripple.reassess import (
    ReassessmentProposal,
    UpstreamChange,
    reassess_cascade,
)

if TYPE_CHECKING:
    from neo4j import AsyncDriver


log = logging.getLogger(__name__)


@dataclass
class CascadeResult:
    """Everything one Ripple cascade produced — structured so callers
    can audit without re-walking the graph."""

    origin_kref: str
    impact: AnalyzeImpactResult
    proposals: list[ReassessmentProposal] = field(default_factory=list)
    contradictions: list[ContradictionPair] = field(default_factory=list)
    routing: list[RoutingDecision] = field(default_factory=list)
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None

    @property
    def n_impacted(self) -> int:
        return len(self.impact.impacted) if self.impact else 0

    @property
    def n_strategic(self) -> int:
        return sum(
            1 for r in self.routing
            if r.route == AdjudicationRoute.STRATEGIC_REVIEW
        )

    @property
    def n_core_protected(self) -> int:
        return sum(
            1 for r in self.routing
            if r.route == AdjudicationRoute.CORE_PROTECTED
        )

    @property
    def n_auto_apply(self) -> int:
        return sum(
            1 for r in self.routing
            if r.route == AdjudicationRoute.AUTO_APPLY
        )


class RippleEngine:
    """Integrated Ripple orchestrator — the entry point for "a fact
    changed, run the whole cascade."

    Construct once with a Neo4j driver, call .propagate() per
    upstream change. Every stage is delegated to the dedicated module
    (analyze_impact / reassess / contradiction / adjudication) so the
    AGM correctness guarantees in those modules hold.
    """

    def __init__(
        self,
        driver: AsyncDriver,
        *,
        emit_events: bool = True,
        max_depth: int = 10,
        max_nodes: int = 5000,
    ):
        self.driver = driver
        self.emit_events = emit_events
        self.max_depth = max_depth
        self.max_nodes = max_nodes

    async def propagate(
        self,
        upstream_kref: str,
        *,
        old_confidence: float,
        new_confidence: float,
        belief_text: str = "",
    ) -> CascadeResult:
        """Run the full cascade for one upstream change.

        Args:
            upstream_kref: The fact that changed (the origin of the
                cascade).
            old_confidence: Confidence value the upstream had BEFORE
                the change.
            new_confidence: Confidence value the upstream has AFTER
                the change.
            belief_text: Optional human-readable description of the
                upstream change. Threads through reassess + adjudication.

        Returns:
            CascadeResult with impact + proposals + contradictions +
            routing decisions. Errors are captured in result.error
            rather than raised so the caller can decide how to react.
        """
        result = CascadeResult(
            origin_kref=upstream_kref,
            impact=AnalyzeImpactResult(
                impacted=[], cycles_detected=[], nodes_visited=0,
                truncated=False,
            ),
        )

        try:
            # Stage 1: AnalyzeImpact
            impact = await analyze_impact(
                self.driver,
                upstream_kref,
                max_depth=self.max_depth,
                max_nodes=self.max_nodes,
            )
            result.impact = impact

            if not impact.impacted:
                # Nothing depends on this upstream — emit a synthetic
                # "no-op" event for visibility but bail early.
                if self.emit_events:
                    self._emit("ripple_cascade", {
                        "upstream_kref": upstream_kref,
                        "impacted_count": 0,
                        "noop": True,
                    })
                return result

            # Stage 2: Reassess — produce proposals (no graph mutation)
            change = UpstreamChange(
                upstream_kref=upstream_kref,
                belief_text=belief_text,
                old_confidence=old_confidence,
                new_confidence=new_confidence,
            )
            proposals = await reassess_cascade(
                self.driver, impact.impacted, change,
            )
            result.proposals = proposals

            # Stage 3: Type-aware contradiction detection
            contradictions = await detect_contradictions(
                self.driver, proposals,
            )
            result.contradictions = contradictions

            # Stage 4: Routing per proposal
            routing: list[RoutingDecision] = []
            for proposal in proposals:
                decision = await route_proposal(
                    self.driver, proposal, contradictions,
                )
                routing.append(decision)
            result.routing = routing

            # Stage 5: Emit a live-viz event with the headline counts
            if self.emit_events:
                self._emit("ripple_cascade", {
                    "upstream_kref": upstream_kref,
                    "impacted_count": result.n_impacted,
                    "contradictions_count": len(contradictions),
                    "strategic_count": result.n_strategic,
                    "core_protected_count": result.n_core_protected,
                    "auto_apply_count": result.n_auto_apply,
                })

            return result

        except Exception as exc:  # pragma: no cover — defensive
            log.exception("Ripple cascade crashed for %s", upstream_kref)
            result.error = f"{type(exc).__name__}: {exc}"
            return result

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        """Best-effort SSE emit. Failures here MUST NOT block the
        cascade — visualization is a courtesy, not a contract."""
        try:
            from atlas_core.api.events import GLOBAL_BROADCASTER, AtlasEvent
            GLOBAL_BROADCASTER.emit(AtlasEvent(kind=kind, payload=payload))
        except Exception:  # pragma: no cover
            pass
