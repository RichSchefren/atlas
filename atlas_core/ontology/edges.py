"""Atlas Phase 1 edge taxonomy — 6 structural (Kumiho spec) + 10 domain (Atlas-original)."""

from enum import Enum


class StructuralEdgeType(str, Enum):
    """Six typed edges from Kumiho paper Section 6.5 (arxiv:2603.17244)."""

    DEPENDS_ON = "DEPENDS_ON"
    """Validity dependency. The PRIMARY edge Ripple traverses for AnalyzeImpact."""

    DERIVED_FROM = "DERIVED_FROM"
    """Evidential provenance — source produced the target as input."""

    SUPERSEDES = "SUPERSEDES"
    """Belief revision — source replaces target as the current belief."""

    REFERENCED = "REFERENCED"
    """Associative mention — source refers to target without dependency."""

    CONTAINS = "CONTAINS"
    """Bundle membership — target is a member of source's bundle."""

    CREATED_FROM = "CREATED_FROM"
    """Generative lineage — source was generated from target."""


class DomainEdgeType(str, Enum):
    """Ten Atlas-original domain edges."""

    COMMITS_TO = "COMMITS_TO"
    """Person → Commitment — who made which commitment."""

    OWNS = "OWNS"
    """Person → Project — project ownership."""

    RUNS = "RUNS"
    """Person → Program — day-to-day program operator."""

    GENERATES = "GENERATES"
    """Program → Revenue — income source attribution."""

    CONTRADICTS = "CONTRADICTS"
    """StrategicBelief ↔ StrategicBelief — belief conflict edge for Ripple."""

    SUPPORTS = "SUPPORTS"
    """Revision → StrategicBelief — evidence chain."""

    COMPETES_WITH = "COMPETES_WITH"
    """Program → MarketEntity — competitive positioning."""

    IMPORTANT_TO_RICH = "IMPORTANT_TO_RICH"
    """Rich → Person — Rich-set, Atlas-protected priority signal."""

    ORBITS = "ORBITS"
    """Person/Program/Project → Rich — sovereign-node anchor."""

    FINANCIAL_RELATIONSHIP = "FINANCIAL_RELATIONSHIP"
    """Person → Person/Program — JV/affiliate/client/etc. edge."""


# edge_type_map for Graphiti's add_episode(edge_type_map=...).
# Constrains which edge types can exist between which entity-type pairs.
EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    ("Person", "Commitment"): [DomainEdgeType.COMMITS_TO.value],
    ("Person", "Project"): [DomainEdgeType.OWNS.value],
    ("Person", "Program"): [
        DomainEdgeType.RUNS.value,
        DomainEdgeType.FINANCIAL_RELATIONSHIP.value,
    ],
    ("Person", "Person"): [DomainEdgeType.FINANCIAL_RELATIONSHIP.value],
    ("Program", "Revenue"): [DomainEdgeType.GENERATES.value],
    ("Program", "MarketEntity"): [DomainEdgeType.COMPETES_WITH.value],
    ("StrategicBelief", "StrategicBelief"): [
        DomainEdgeType.CONTRADICTS.value,
        DomainEdgeType.SUPPORTS.value,
    ],
    ("Rich", "Person"): [DomainEdgeType.IMPORTANT_TO_RICH.value],
    ("Person", "Rich"): [DomainEdgeType.ORBITS.value],
    ("Program", "Rich"): [DomainEdgeType.ORBITS.value],
    ("Project", "Rich"): [DomainEdgeType.ORBITS.value],
    # Default catch-all — Graphiti uses this when type pair isn't explicitly listed
    ("Entity", "Entity"): [],
}
