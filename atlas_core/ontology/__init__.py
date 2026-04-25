"""Atlas Phase 1 ontology — 8 typed business entities + 16 typed relationships.

Locked via Rich Schefren whiteboard 2026-04-24. See spec:
World Model Research/05a - Atlas Phase 1 Ontology Lock.md
"""

from atlas_core.ontology.commitment import (
    Commitment,
    CommitmentStatus,
    StakeLevel,
)
from atlas_core.ontology.edges import (
    EDGE_TYPE_MAP,
    DomainEdgeType,
    StructuralEdgeType,
)
from atlas_core.ontology.market_entity import (
    MarketEntity,
    MarketEntityType,
    PriceRange,
    ThreatLevel,
)
from atlas_core.ontology.person import (
    ClosenessSignals,
    FinancialRelationship,
    FinRelType,
    ImportanceTier,
    Person,
    PriorityTier,
    ReciprocityState,
)
from atlas_core.ontology.program import (
    EnrollmentStatus,
    LifecycleStage,
    Program,
)
from atlas_core.ontology.project import (
    Milestone,
    Project,
    ProjectHealth,
    ProjectStatus,
)
from atlas_core.ontology.revenue import Period, Revenue, RevenueType
from atlas_core.ontology.rich import (
    FinancialSnapshot,
    HealthState,
    PsychReport,
    Rich,
)
from atlas_core.ontology.strategic_belief import (
    CONFIDENCE_LABEL_DEFAULTS,
    CONFIDENCE_TRANSITION_HYSTERESIS,
    ConfidenceLabel,
    StrategicBelief,
)

# The 8 Phase 1 entity types — passed to AtlasGraphiti.add_episode(entity_types=...)
PHASE_1_ENTITY_TYPES = {
    "Rich": Rich,
    "Person": Person,
    "Program": Program,
    "Commitment": Commitment,
    "MarketEntity": MarketEntity,
    "Revenue": Revenue,
    "Project": Project,
    "StrategicBelief": StrategicBelief,
}

__all__ = [
    "PHASE_1_ENTITY_TYPES",
    "EDGE_TYPE_MAP",
    "StructuralEdgeType",
    "DomainEdgeType",
    "Rich",
    "PsychReport",
    "HealthState",
    "FinancialSnapshot",
    "Person",
    "ClosenessSignals",
    "FinancialRelationship",
    "FinRelType",
    "PriorityTier",
    "ReciprocityState",
    "ImportanceTier",
    "Program",
    "EnrollmentStatus",
    "LifecycleStage",
    "Commitment",
    "CommitmentStatus",
    "StakeLevel",
    "MarketEntity",
    "MarketEntityType",
    "ThreatLevel",
    "PriceRange",
    "Revenue",
    "Period",
    "RevenueType",
    "Project",
    "ProjectStatus",
    "ProjectHealth",
    "Milestone",
    "StrategicBelief",
    "ConfidenceLabel",
    "CONFIDENCE_LABEL_DEFAULTS",
    "CONFIDENCE_TRANSITION_HYSTERESIS",
]
