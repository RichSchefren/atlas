"""Ripple — Atlas's automatic downstream reassessment engine.

Phase 2 W3 modules:
  - analyze_impact: recursive Depends_On BFS with cycle detection (#22 ✓)
  - reassess: confidence propagation (#23 ✓)
  - contradiction_detect: type-aware rules (#24, next)
  - adjudication_route: routine vs strategic vs core_protected (#25)

Spec: 06 - Ripple Algorithm Spec.md
"""

from atlas_core.ripple.analyze_impact import (
    MAX_DEPTH_DEFAULT,
    MAX_NODES_DEFAULT,
    AnalyzeImpactResult,
    ImpactNode,
    analyze_impact,
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
]
