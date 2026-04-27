"""Rich — sovereign singleton entity. Everything orbits this node.

Locked via whiteboard 2026-04-24. Rich is a first-class entity, separate from Person,
because the user is the sovereign node of their own world model.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from atlas_core.ontology.base import AtlasEntity


class HealthState(BaseModel):
    """Rich's current health state. Updated from health summaries + capture streams."""

    energy: int = Field(..., ge=1, le=10, description="Current energy 1-10")
    sleep_last_night_hours: float | None = None
    workout_completed_today: bool = False
    pain_or_injury: str | None = None
    last_updated: datetime


class FinancialSnapshot(BaseModel):
    """High-level financial state. Atlas never stores cents-level detail."""

    monthly_revenue_band: str = Field(
        ...,
        description="Coarse band: 'sub_100k' | '100k_250k' | '250k_500k' | '500k_plus'",
    )
    runway_months: float | None = None
    biggest_revenue_concern: str | None = None
    last_updated: datetime


class PsychReport(BaseModel):
    """Single psychological assessment Rich has taken (Enneagram, Big Five, etc.)."""

    report_type: str = Field(
        ..., description="'Enneagram' | 'Big Five' | 'DISC' | 'Hogan' | 'Kolbe' | etc."
    )
    date: datetime
    key_findings: list[str] = Field(default_factory=list)
    full_document_path: str = Field(..., description="Vault path to the full report")


class Rich(AtlasEntity):
    """The sovereign singleton — Rich Schefren as a first-class entity.

    Everything orbits this node. Atlas reasons about commitments, priorities, beliefs,
    and relationships in terms of their relationship to Rich.
    """

    psychological_profiles: list[PsychReport] = Field(default_factory=list)
    current_health: HealthState | None = None
    current_priorities: list[str] = Field(
        default_factory=list,
        description="Active priority refs as kref:// strings",
    )
    current_blockers: list[str] = Field(default_factory=list)
    active_frustrations: list[str] = Field(default_factory=list)
    active_excitements: list[str] = Field(default_factory=list)
    learning_in_progress: list[str] = Field(default_factory=list)
    operating_standards: list[str] = Field(default_factory=list)
    family_state_summary: str | None = None
    relationship_state_sabrina: str | None = None
    financial_state_snapshot: FinancialSnapshot | None = None
