"""Person entity — every human in Rich's orbit who isn't Rich himself.

Three first-class properties: closeness_score (auto-computed), importance_tier
(Rich-set, Atlas-protected), financial_relationship (structured when relevant).

Locked via whiteboard 2026-04-24.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from atlas_core.ontology.base import AtlasEntity


class ImportanceTier(str, Enum):
    """Rich-set tier — Atlas does not auto-modify. Determines retention + surfacing."""

    CORE = "core"
    STRATEGIC = "strategic"
    ACTIVE = "active"
    DORMANT = "dormant"
    PERIPHERAL = "peripheral"


class FinRelType(str, Enum):
    JV_PARTNER = "jv_partner"
    AFFILIATE = "affiliate"
    CLIENT = "client"
    VENDOR = "vendor"
    INVESTOR = "investor"
    EQUITY_HOLDER = "equity_holder"
    EMPLOYEE = "employee"
    CONTRACTOR = "contractor"
    CREDITOR = "creditor"
    NONE = "none"


class PriorityTier(str, Enum):
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class ReciprocityState(str, Enum):
    BALANCED = "balanced"
    I_OWE = "i_owe"
    THEY_OWE = "they_owe"


class FinancialRelationship(BaseModel):
    """Structured financial relationship — only set when type != none."""

    type: FinRelType
    priority_level: PriorityTier
    lifetime_value: Optional[Decimal] = None
    revenue_generated_ytd: Optional[Decimal] = None
    annual_value: Optional[Decimal] = None
    contract_path: Optional[str] = Field(default=None, description="Vault path to contract")
    payment_terms: Optional[str] = None
    expiration_date: Optional[date] = None
    reciprocity_state: ReciprocityState = ReciprocityState.BALANCED


class ClosenessSignals(BaseModel):
    """Raw inputs to closeness_score calculation.

    Atlas exposes these for transparency — Rich can audit why someone scored
    high or low. All counters are 90-day rolling.
    """

    limitless_mentions_90d: int = 0
    limitless_minutes_90d: float = 0.0
    imessage_messages_90d: int = 0
    imessage_recency_days: Optional[float] = None
    meeting_attendances_90d: int = 0
    last_interaction_date: Optional[date] = None


class Person(AtlasEntity):
    """A human in Rich's orbit (not Rich himself).

    closeness_score is Atlas-computed from capture streams (Limitless + iMessage +
    meetings). importance_tier is Rich-set and Atlas-protected. financial_relationship
    is optional structured data when applicable.
    """

    aliases: list[str] = Field(
        default_factory=list,
        description="Alternate names for entity resolution (e.g., 'Ashley S' → 'Ashley Shaw')",
    )
    person_role: str = Field(
        ...,
        description="Primary role/title (renamed from `role` to avoid Graphiti `name` collision concern)",
    )
    channels: list[str] = Field(
        default_factory=list,
        description="Communication channels: email, slack, sms, etc.",
    )

    # Auto-computed signal — rolling 90-day weighted blend
    closeness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    closeness_signals: Optional[ClosenessSignals] = None

    # Rich-set, Atlas-protected
    importance_tier: ImportanceTier = ImportanceTier.PERIPHERAL

    # Optional structured financial relationship
    financial_relationship: Optional[FinancialRelationship] = None

    follow_through_rate: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Commitments kept / commitments made (rolling)",
    )
