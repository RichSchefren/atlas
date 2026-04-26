"""Atlas decision-lineage subsystem.

Every Decision links via SUPPORTS edges to the StrategicBeliefs
it rests on. When a belief gets demoted via Ripple, every Decision
now resting on weakened support surfaces through the contradiction
detector.

Spec: PHASE-5-AND-BEYOND.md § 1.5
       06 - Ripple Algorithm Spec § 5 (lineage-weakening contradictions)
"""

from atlas_core.lineage.contradiction import (
    LineageContradiction,
    detect_lineage_contradictions,
)
from atlas_core.lineage.extractor import (
    LineageExtractor,
    extract_supports_edges,
)
from atlas_core.lineage.walker import (
    LineageWalk,
    LineageWalker,
    walk_decision_chain,
)

__all__ = [
    "LineageContradiction",
    "detect_lineage_contradictions",
    "LineageExtractor",
    "extract_supports_edges",
    "LineageWalk",
    "LineageWalker",
    "walk_decision_chain",
]
