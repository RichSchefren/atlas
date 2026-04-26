"""The synthetic business — Atlas Coffee Roasting Co.

Phase 1 lock per Spec 08 § 2.2:
  - 12 employees with named roles + commitment patterns
  - 4 product lines (subscription tiers)
  - 6 wholesale clients
  - 3 competitors
  - 90 days of operational events spanning 2026-01-01 → 2026-03-31

Everything here is constant data — the business doesn't randomize.
What varies between corpus runs is the EVENT TIMELINE, generated
from a seed in events.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional


CORPUS_START_DATE: date = date(2026, 1, 1)
CORPUS_END_DATE: date = date(2026, 3, 31)
CORPUS_DAYS: int = (CORPUS_END_DATE - CORPUS_START_DATE).days + 1  # 90


@dataclass(frozen=True)
class Employee:
    """An Atlas Coffee Roasting Co. team member."""

    employee_id: str
    name: str
    role: str
    department: str
    follow_through_rate: float  # 0..1; how reliably they hit committed deadlines


@dataclass(frozen=True)
class ProductLine:
    """A coffee subscription tier. Pricing changes over the corpus
    window — events.py records each change as a Pricing supersession."""

    product_id: str
    name: str
    initial_price: float       # USD per month at corpus start
    accessible_threshold: float  # max price at which 'accessible' belief holds


@dataclass(frozen=True)
class WholesaleClient:
    """A B2B coffee buyer. Generates Commitments + RevenueRecords."""

    client_id: str
    name: str
    monthly_volume_lbs: int
    delivery_day: str  # 'Mon' .. 'Fri'


@dataclass(frozen=True)
class Competitor:
    """MarketEntity competitor for cross-stream consistency questions."""

    competitor_id: str
    name: str
    market_position: str


# ─── The business roster ────────────────────────────────────────────────────


EMPLOYEES: tuple[Employee, ...] = (
    Employee("e01", "Sarah Chen",      "CEO",                     "exec",       0.95),
    Employee("e02", "Marcus Rivera",   "Head Roaster",            "production", 0.92),
    Employee("e03", "Priya Patel",     "Head of Wholesale",       "sales",      0.88),
    Employee("e04", "Jordan Kim",      "Operations Manager",      "ops",        0.90),
    Employee("e05", "Alex Park",       "Roaster",                 "production", 0.85),
    Employee("e06", "Sam Okafor",      "Roaster",                 "production", 0.78),
    Employee("e07", "Maya Singh",      "Marketing Lead",          "marketing",  0.82),
    Employee("e08", "Ben Cohen",       "Cafe Manager",            "retail",     0.88),
    Employee("e09", "Riley Nguyen",    "Barista Trainer",         "retail",     0.91),
    Employee("e10", "Taylor Brooks",   "Finance Lead",            "exec",       0.96),
    Employee("e11", "Casey Morgan",    "Customer Success",        "sales",      0.84),
    Employee("e12", "Jamie Fontaine",  "QC Specialist",           "production", 0.93),
)


PRODUCT_LINES: tuple[ProductLine, ...] = (
    ProductLine("p01", "Origins",        89.0,  100.0),  # most-accessible threshold
    ProductLine("p02", "Single Origin",  129.0, 150.0),
    ProductLine("p03", "Reserve",        189.0, 220.0),
    ProductLine("p04", "Festive Blend",   75.0,  90.0),
)


WHOLESALE_CLIENTS: tuple[WholesaleClient, ...] = (
    WholesaleClient("w01", "Brewhouse Co.",       240, "Tue"),
    WholesaleClient("w02", "Morning Light Cafe",  180, "Tue"),
    WholesaleClient("w03", "The Daily Grind",     320, "Wed"),
    WholesaleClient("w04", "Common Grounds",      200, "Tue"),
    WholesaleClient("w05", "North End Roasters",  150, "Thu"),
    WholesaleClient("w06", "Park Avenue Cafe",    280, "Tue"),
)


COMPETITORS: tuple[Competitor, ...] = (
    Competitor("c01", "Verdant Coffee",       "premium_direct_competitor"),
    Competitor("c02", "Stonewall Roasters",   "value_segment"),
    Competitor("c03", "Heritage Cafe Group",  "wholesale_consolidator"),
)


# ─── World wrapper ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AtlasCoffeeWorld:
    """Container for the entire constant business universe.

    Used by the event generator + question generator + corpus writer.
    """

    employees: tuple[Employee, ...] = EMPLOYEES
    product_lines: tuple[ProductLine, ...] = PRODUCT_LINES
    wholesale_clients: tuple[WholesaleClient, ...] = WHOLESALE_CLIENTS
    competitors: tuple[Competitor, ...] = COMPETITORS

    def employee_by_id(self, eid: str) -> Optional[Employee]:
        for e in self.employees:
            if e.employee_id == eid:
                return e
        return None

    def product_by_id(self, pid: str) -> Optional[ProductLine]:
        for p in self.product_lines:
            if p.product_id == pid:
                return p
        return None

    def client_by_id(self, cid: str) -> Optional[WholesaleClient]:
        for c in self.wholesale_clients:
            if c.client_id == cid:
                return c
        return None

    def all_dates(self) -> list[date]:
        """The 90 corpus dates inclusive."""
        return [
            CORPUS_START_DATE + timedelta(days=i)
            for i in range(CORPUS_DAYS)
        ]
