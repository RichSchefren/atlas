"""Ripple — Atlas's automatic downstream reassessment engine.

Phase 2 W3 implements:
  - analyze_impact: recursive Depends_On BFS with cycle detection
  - reassess: confidence propagation (W3 task #23)
  - contradiction_detect: type-aware rules (W3 task #24)
  - adjudication_route: routine vs strategic vs core_protected (W3 task #25)

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

__all__ = [
    "RippleEngine",
    "ImpactNode",
    "AnalyzeImpactResult",
    "analyze_impact",
    "MAX_DEPTH_DEFAULT",
    "MAX_NODES_DEFAULT",
]
