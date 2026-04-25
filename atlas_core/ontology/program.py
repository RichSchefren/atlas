"""Program entity — coaching, education, or community programs Rich runs."""

from enum import Enum
from typing import Optional

from pydantic import Field

from atlas_core.ontology.base import AtlasEntity


class EnrollmentStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    WAITLIST = "waitlist"
    DORMANT = "dormant"


class LifecycleStage(str, Enum):
    IDEATION = "ideation"
    BETA = "beta"
    LIVE = "live"
    MATURE = "mature"
    SUNSETTING = "sunsetting"
    SUNSET = "sunset"


class Program(AtlasEntity):
    """A coaching, education, or community program Rich operates.

    Examples: ZenithPro, Zenith MindOS, BGS, SOW, Force Multiplier.
    """

    program_type: str = Field(
        ...,
        description="course | mastermind | workshop | community | system",
    )
    deliverables: list[str] = Field(default_factory=list)
    enrollment_status: EnrollmentStatus = EnrollmentStatus.DORMANT
    lifecycle_stage: LifecycleStage = LifecycleStage.IDEATION
    runner_kref: Optional[str] = Field(
        default=None,
        description="kref:// of Person who owns day-to-day operations of this program",
    )
