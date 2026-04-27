"""Commitment entity — accountability layer.

Tracks who owes what to whom by when, with stakes and dependency tracking.
"""

from datetime import datetime
from enum import Enum

from pydantic import Field

from atlas_core.ontology.base import AtlasEntity


class CommitmentStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BROKEN = "broken"
    RENEGOTIATED = "renegotiated"


class StakeLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Commitment(AtlasEntity):
    """A commitment, promise, or stated intention with deadline and accountability."""

    description: str
    owner_kref: str = Field(..., description="kref:// of Person|Rich who made the commitment")
    counterparty_kref: str | None = Field(
        default=None, description="kref:// of who the commitment is owed to"
    )
    deadline: datetime | None = None
    depends_on_krefs: list[str] = Field(
        default_factory=list,
        description="kref://s of blockers — completing them must precede this commitment",
    )
    status: CommitmentStatus = CommitmentStatus.OPEN
    stakes: StakeLevel = StakeLevel.MEDIUM
    source_episode_kref: str | None = Field(
        default=None,
        description="kref:// of meeting/conversation/session where commitment was made",
    )
