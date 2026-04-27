"""Project entity — active initiatives with owner, status, dependencies."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from atlas_core.ontology.base import AtlasEntity


class ProjectStatus(str, Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    DORMANT = "dormant"
    KILLED = "killed"


class ProjectHealth(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class Milestone(BaseModel):
    label: str
    target_date: datetime | None = None
    completed: bool = False
    completed_date: datetime | None = None


class Project(AtlasEntity):
    """An active initiative with owner, status, and dependencies."""

    project_status: ProjectStatus = ProjectStatus.PLANNING
    owner_kref: str = Field(..., description="kref:// of Person|Rich who owns this project")
    contributor_krefs: list[str] = Field(default_factory=list)
    associated_program_kref: str | None = None
    dependency_krefs: list[str] = Field(
        default_factory=list,
        description="kref://s of upstream Projects that must complete first",
    )
    milestones: list[Milestone] = Field(default_factory=list)
    started_at: datetime | None = None
    target_completion: datetime | None = None
    actual_completion: datetime | None = None
    health: ProjectHealth = ProjectHealth.GREEN
