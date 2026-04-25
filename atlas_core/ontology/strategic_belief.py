"""StrategicBelief entity — hypotheses with confidence.

The layer Ripple operates on. Hybrid confidence model: human-facing label + Atlas-internal
continuous score. Hysteresis on tier transitions prevents oscillation.
"""

from enum import Enum

from pydantic import Field

from atlas_core.ontology.base import AtlasEntity
from atlas_core.ontology.commitment import StakeLevel


class ConfidenceLabel(str, Enum):
    """Human-facing confidence tier. Set on belief creation; updated via Ripple via hysteresis."""

    UNSTATED_ASSUMPTION = "unstated_assumption"
    WORKING_HYPOTHESIS = "working_hypothesis"
    VALIDATED_BELIEF = "validated_belief"
    CORE_CONVICTION = "core_conviction"


# Default continuous score for each label on first-time labeling
CONFIDENCE_LABEL_DEFAULTS: dict[ConfidenceLabel, float] = {
    ConfidenceLabel.UNSTATED_ASSUMPTION: 0.40,
    ConfidenceLabel.WORKING_HYPOTHESIS: 0.60,
    ConfidenceLabel.VALIDATED_BELIEF: 0.80,
    ConfidenceLabel.CORE_CONVICTION: 0.95,
}

# Hysteresis band — score must cross tier boundary by this much before label changes.
# Prevents oscillation when score hovers near a tier boundary.
CONFIDENCE_TRANSITION_HYSTERESIS: float = 0.05


class StrategicBelief(AtlasEntity):
    """A hypothesis with confidence — the layer Ripple operates on.

    confidence_label is human-facing. confidence_score is Atlas-internal, continuous,
    and updated via Ripple's reassessment formula. Label changes only when score
    crosses a tier boundary by the hysteresis band.

    Beliefs marked is_core_conviction=True are protected from auto-demotion;
    Atlas surfaces challenges via the adjudication queue but does not auto-modify.
    """

    hypothesis: str = Field(..., description="Human-readable claim")
    confidence_label: ConfidenceLabel
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Atlas-internal continuous confidence; Ripple updates this",
    )
    evidence_for_krefs: list[str] = Field(default_factory=list)
    evidence_against_krefs: list[str] = Field(default_factory=list)
    stakes: StakeLevel = StakeLevel.MEDIUM
    is_core_conviction: bool = Field(
        default=False,
        description="When True, auto-demotion is blocked. Atlas surfaces challenges to Rich.",
    )
