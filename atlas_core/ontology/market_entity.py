"""MarketEntity entity — competitors, adjacent players, market categories, platforms."""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from atlas_core.ontology.base import AtlasEntity


class MarketEntityType(str, Enum):
    COMPETITOR = "competitor"
    ADJACENT_PLAYER = "adjacent_player"
    CATEGORY = "category"
    PLATFORM = "platform"


class ThreatLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXISTENTIAL = "existential"


class PriceRange(BaseModel):
    low_usd: Decimal | None = None
    high_usd: Decimal | None = None
    typical_usd: Decimal | None = None


class MarketEntity(AtlasEntity):
    """A competitor, adjacent player, market category, or platform Rich operates near."""

    entity_market_type: MarketEntityType
    positioning: str | None = None
    pricing_range: PriceRange | None = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    threat_level: ThreatLevel = ThreatLevel.LOW
    last_observed: datetime | None = None
    source_paths: list[str] = Field(
        default_factory=list,
        description="Vault paths to source materials (articles, social posts, transcripts)",
    )
