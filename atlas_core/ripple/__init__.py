"""Ripple — Atlas's automatic downstream reassessment engine.

Phase 2 W3 modules:
  - analyze_impact: recursive Depends_On BFS with cycle detection (#22 ✓)
  - reassess: confidence propagation (#23 ✓)
  - contradiction_detect: type-aware rules (#24, next)
  - adjudication_route: routine vs strategic vs core_protected (#25)

Spec: 06 - Ripple Algorithm Spec.md
"""

from atlas_core.ripple.adjudication import (
    CONFIDENCE_DELTA_STRATEGIC_FLOOR,
    DEFAULT_ADJUDICATION_DIR,
    HIGH_STAKES_LEVELS,
    AdjudicationRoute,
    RoutingDecision,
    route_all,
    route_proposal,
    write_adjudication_entry,
    write_strategic_entries,
)
from atlas_core.ripple.analyze_impact import (
    MAX_DEPTH_DEFAULT,
    MAX_NODES_DEFAULT,
    AnalyzeImpactResult,
    ImpactNode,
    analyze_impact,
)
from atlas_core.ripple.contradiction import (
    DECISION_SUPPORT_FLOOR,
    STRATEGIC_BELIEF_CONFIDENCE_FLOOR,
    STRATEGIC_BELIEF_HIGH_SEVERITY_FLOOR,
    ContradictionCategory,
    ContradictionPair,
    Severity,
    detect_contradictions,
)
from atlas_core.ripple.engine import RippleEngine
from atlas_core.ripple.reassess import (
    DEFAULT_WEIGHTS,
    HALF_LIFE_DAYS,
    HeuristicReassessor,
    LLMReassessmentDelta,
    LLMReassessor,
    ReassessmentProposal,
    ReassessWeights,
    UpstreamChange,
    reassess_cascade,
    reassess_dependent,
)

__all__ = [
    # Engine
    "RippleEngine",
    # AnalyzeImpact
    "ImpactNode",
    "AnalyzeImpactResult",
    "analyze_impact",
    "MAX_DEPTH_DEFAULT",
    "MAX_NODES_DEFAULT",
    # Reassess
    "ReassessmentProposal",
    "ReassessWeights",
    "DEFAULT_WEIGHTS",
    "UpstreamChange",
    "LLMReassessor",
    "LLMReassessmentDelta",
    "HeuristicReassessor",
    "HALF_LIFE_DAYS",
    "reassess_dependent",
    "reassess_cascade",
    # Contradiction detection
    "ContradictionPair",
    "ContradictionCategory",
    "Severity",
    "detect_contradictions",
    "STRATEGIC_BELIEF_CONFIDENCE_FLOOR",
    "STRATEGIC_BELIEF_HIGH_SEVERITY_FLOOR",
    "DECISION_SUPPORT_FLOOR",
    # Adjudication routing
    "AdjudicationRoute",
    "RoutingDecision",
    "route_proposal",
    "route_all",
    "write_adjudication_entry",
    "write_strategic_entries",
    "CONFIDENCE_DELTA_STRATEGIC_FLOOR",
    "HIGH_STAKES_LEVELS",
    "DEFAULT_ADJUDICATION_DIR",
]
