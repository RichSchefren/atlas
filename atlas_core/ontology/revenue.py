"""Revenue entity — financial pulse line items."""

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import Field

from atlas_core.ontology.base import AtlasEntity


class Period(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    ONE_TIME = "one_time"
    RECURRING = "recurring"


class RevenueType(str, Enum):
    SUBSCRIPTION = "subscription"
    ONE_TIME = "one_time"
    ROYALTY = "royalty"
    COMMISSION = "commission"
    EQUITY_DIVIDEND = "equity_dividend"
    CONSULTING = "consulting"


class Revenue(AtlasEntity):
    """A revenue line item — source, amount, period, association to Program/Person."""

    source: str = Field(..., description="Source label — program name, JV name, etc.")
    associated_program_kref: str | None = None
    associated_person_kref: str | None = Field(
        default=None,
        description="For affiliate/JV revenue — kref:// of generating Person",
    )
    amount_usd: Decimal
    period: Period
    period_start: date
    period_end: date | None = None
    revenue_type: RevenueType
