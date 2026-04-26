"""Atlas trust layer — Quarantine → Corroboration → Ledger.

Bicameral pattern ported. Real SHA-256 hash chain (Bicameral's was aspirational).
Phase 2 Week 4 implementation. See specs:
World Model Research/05 - Atlas Architecture & Schema.md § 6
"""

from atlas_core.trust.ledger import HashChainedLedger
from atlas_core.trust.quarantine import (
    AUTO_PROMOTE_THRESHOLD,
    CORROBORATION_BOOST_PER_SOURCE_FAMILY,
    CORROBORATION_CAPS,
    ELIGIBLE_ASSERTION_TYPES,
    LANE_CANDIDATES_ELIGIBLE,
    LANE_CORROBORATION_ONLY,
    LANE_RETRIEVAL_ELIGIBLE_GLOBAL,
    RECOMMEND_THRESHOLD,
    TRUST_CORROBORATED,
    TRUST_LEDGER,
    TRUST_QUARANTINED,
    CandidateClaim,
    CandidateStatus,
    EvidenceRef,
    QuarantineStore,
    UpsertResult,
)

__all__ = [
    "HashChainedLedger",
    "QuarantineStore",
    "CandidateClaim",
    "CandidateStatus",
    "EvidenceRef",
    "UpsertResult",
    "TRUST_QUARANTINED",
    "TRUST_CORROBORATED",
    "TRUST_LEDGER",
    "RECOMMEND_THRESHOLD",
    "AUTO_PROMOTE_THRESHOLD",
    "CORROBORATION_BOOST_PER_SOURCE_FAMILY",
    "CORROBORATION_CAPS",
    "ELIGIBLE_ASSERTION_TYPES",
    "LANE_RETRIEVAL_ELIGIBLE_GLOBAL",
    "LANE_CORROBORATION_ONLY",
    "LANE_CANDIDATES_ELIGIBLE",
]
