"""Event timeline generator — produces the 90-day operational stream
for Atlas Coffee Roasting Co.

Events span:
  - Pricing changes (10-15 over 90 days)
  - Hires + role changes (5-10)
  - Decisions (15-20)
  - Wholesale orders (~6 clients × 12 weeks ≈ 72 orders)
  - Strategic beliefs asserted + revised (10-15)
  - Embedded contradictions (5-10 to surface in eval)
  - Embedded deprecations (3-5 to test forgetfulness)

Deterministic from a seed so corpus runs are reproducible.
The EventLog produced here is the source of truth for both the
written corpus (meetings/, vault/, screen_events/, messages/) and
the gold question files.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from benchmarks.business_mem_bench.corpus_generator.business import (
    CORPUS_DAYS,
    CORPUS_START_DATE,
    AtlasCoffeeWorld,
    ProductLine,
)

# Event-density tuning — tested empirically to land near 1,000-question target.
# Bumping these shifts category counts proportionally.
N_PRICING_CHANGES: int = 12
N_HIRES_OR_ROLE: int = 7
N_STRATEGIC_DECISIONS: int = 18
N_BELIEFS_ASSERTED: int = 14
N_EMBEDDED_CONTRADICTIONS: int = 8
N_EMBEDDED_DEPRECATIONS: int = 5
WEEKS_OF_WHOLESALE: int = 12  # 6 clients × 12 weeks = 72 orders


class EventKind(str, Enum):
    """Eight canonical event kinds the generator emits."""

    PRICING_CHANGE = "pricing_change"
    HIRE = "hire"
    ROLE_CHANGE = "role_change"
    DECISION = "decision"
    BELIEF_ASSERTED = "belief_asserted"
    BELIEF_REVISED = "belief_revised"
    WHOLESALE_ORDER = "wholesale_order"
    DEPRECATION = "deprecation"


@dataclass
class Event:
    """One discrete operational event in the corpus timeline.

    `kref_subject` and `kref_object` link the event into the synthesized
    typed graph. `payload` carries category-specific fields (e.g.,
    pricing_change carries old_price + new_price).
    """

    event_id: str
    kind: EventKind
    occurred_at: str            # ISO-8601 UTC
    kref_subject: str
    kref_object: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    summary: str = ""           # human-readable (used in meeting/vault corpus)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class EventLog:
    """The full timeline. `events` is sorted by `occurred_at` ASC."""

    seed: int
    events: list[Event] = field(default_factory=list)

    def by_kind(self, kind: EventKind) -> list[Event]:
        return [e for e in self.events if e.kind == kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "n_events": len(self.events),
            "events": [e.to_dict() for e in self.events],
        }

    def write_jsonl(self, path) -> None:
        """Persist the timeline to a JSONL file (one event per line)."""
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e.to_dict(), separators=(",", ":")))
                f.write("\n")


# ─── Generator ──────────────────────────────────────────────────────────────


def generate_events(world: AtlasCoffeeWorld, seed: int = 42) -> EventLog:
    """Generate the full 90-day event timeline for the corpus.

    The seed determines event timing (which day each event lands on),
    which employee owns each commitment, and which beliefs get
    contradicted later. The constants in business.py + the count
    constants above remain fixed across seeds.
    """
    rng = random.Random(seed)
    log = EventLog(seed=seed)
    counter = [0]  # closure over event_id allocation

    def next_id(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix}_{counter[0]:04d}"

    def ts_for_day(day_offset: int, hour_jitter: bool = True) -> str:
        d = CORPUS_START_DATE + timedelta(days=day_offset)
        hour = rng.randint(8, 18) if hour_jitter else 9
        minute = rng.randint(0, 59) if hour_jitter else 0
        dt = datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)
        return dt.isoformat()

    # ── Pricing changes ─────────────────────────────────────────────────
    # Generate the change list first (with day + product), sort by day,
    # then walk in chronological order so each event's `old_price` is the
    # genuinely-prior price, not the initial constant.
    pending_changes: list[tuple[int, ProductLine, float]] = []
    used_product_days: set[tuple[str, int]] = set()
    attempts = 0
    while len(pending_changes) < N_PRICING_CHANGES and attempts < N_PRICING_CHANGES * 10:
        attempts += 1
        product = rng.choice(world.product_lines)
        day = rng.randint(7, CORPUS_DAYS - 7)
        if (product.product_id, day) in used_product_days:
            continue
        used_product_days.add((product.product_id, day))
        delta_pct = rng.choice([-0.20, -0.10, 0.10, 0.15, 0.25, 0.45])
        pending_changes.append((day, product, delta_pct))
    pending_changes.sort(key=lambda t: t[0])

    running_prices: dict[str, float] = {
        p.product_id: p.initial_price for p in world.product_lines
    }
    for day, product, delta_pct in pending_changes:
        old = running_prices[product.product_id]
        new = round(old * (1 + delta_pct), 2)
        running_prices[product.product_id] = new
        log.events.append(Event(
            event_id=next_id("evt_price"),
            kind=EventKind.PRICING_CHANGE,
            occurred_at=ts_for_day(day),
            kref_subject=f"kref://AtlasCoffee/Programs/{product.product_id}.program",
            kref_object=None,
            payload={"product_id": product.product_id, "old_price": old, "new_price": new},
            summary=f"Pricing on '{product.name}' moves from ${old:.2f} to ${new:.2f}/mo",
        ))

    # ── Hires + role changes ────────────────────────────────────────────
    for i in range(N_HIRES_OR_ROLE):
        emp = world.employees[i % len(world.employees)]
        day = rng.randint(0, CORPUS_DAYS - 1)
        kind = rng.choice([EventKind.HIRE, EventKind.ROLE_CHANGE])
        log.events.append(Event(
            event_id=next_id("evt_hire"),
            kind=kind,
            occurred_at=ts_for_day(day),
            kref_subject=f"kref://AtlasCoffee/People/{emp.employee_id}.person",
            kref_object=None,
            payload={"name": emp.name, "role": emp.role, "department": emp.department},
            summary=(
                f"{emp.name} hired as {emp.role}" if kind == EventKind.HIRE
                else f"{emp.name} role updated to {emp.role}"
            ),
        ))

    # ── Strategic decisions ─────────────────────────────────────────────
    decision_templates = [
        ("expand_into_decaf", "Expand product line to include decaf options"),
        ("hire_2_roasters", "Hire 2 additional roasters by end of Q1"),
        ("renew_lease",      "Renew main roastery lease for 3 years"),
        ("launch_subscription_tier", "Launch new subscription tier 'Reserve'"),
        ("discontinue_festive", "Discontinue Festive Blend product line"),
        ("partner_with_client_w03", "Sign exclusive deal with The Daily Grind"),
        ("invest_in_packaging", "Upgrade packaging line equipment ($45k)"),
        ("attend_specialty_expo", "Attend Specialty Coffee Expo as exhibitor"),
        ("hire_marketing_lead", "Hire dedicated marketing lead"),
        ("open_second_cafe", "Open second cafe location in Q2"),
        ("rebrand_logo",       "Commission rebrand of company logo"),
        ("automate_invoicing", "Adopt automated invoicing for wholesale clients"),
        ("seasonal_origin_program", "Launch seasonal-rotating Single Origin"),
        ("training_program",   "Create barista certification training program"),
        ("audit_supply_chain", "Conduct full supply-chain audit"),
        ("freeze_hiring",      "Freeze hiring through April"),
        ("price_promotion_q1", "Run 15% promotion on Origins for Q1"),
        ("renegotiate_w01",    "Renegotiate Brewhouse contract pricing"),
    ]
    for template_id, desc in decision_templates[:N_STRATEGIC_DECISIONS]:
        owner = rng.choice(world.employees)
        day = rng.randint(0, CORPUS_DAYS - 30)
        log.events.append(Event(
            event_id=next_id("evt_decision"),
            kind=EventKind.DECISION,
            occurred_at=ts_for_day(day),
            kref_subject=f"kref://AtlasCoffee/Decisions/{template_id}.decision",
            kref_object=f"kref://AtlasCoffee/People/{owner.employee_id}.person",
            payload={
                "decision_id": template_id,
                "description": desc,
                "owner_id": owner.employee_id,
                "owner_name": owner.name,
            },
            summary=f"Decision: {desc} (owner: {owner.name})",
        ))

    # ── Strategic beliefs (some get revised later) ─────────────────────
    belief_templates = [
        ("origins_most_accessible", "Origins is our most accessible price point",
         "kref://AtlasCoffee/Programs/p01.program"),
        ("reserve_drives_loyalty",  "Reserve tier drives the highest customer loyalty",
         "kref://AtlasCoffee/Programs/p03.program"),
        ("festive_viable",          "Festive Blend is a viable seasonal product",
         "kref://AtlasCoffee/Programs/p04.program"),
        ("wholesale_tuesday_pref",  "Wholesale clients prefer Tuesday delivery",
         "kref://AtlasCoffee/Routes/wholesale.route"),
        ("verdant_main_competitor", "Verdant Coffee is our primary direct competitor",
         "kref://AtlasCoffee/Markets/c01.competitor"),
        ("hiring_freeze_active",    "We have a hiring freeze through April",
         "kref://AtlasCoffee/Operations/hiring.policy"),
        ("roster_team_understaffed","The roaster team is understaffed for current volume",
         "kref://AtlasCoffee/Departments/production.dept"),
        ("daily_grind_strategic",   "The Daily Grind is our most strategic wholesale account",
         "kref://AtlasCoffee/Clients/w03.client"),
        ("q1_growth_from_newcomers","Q1 growth depends on newcomer acquisition",
         "kref://AtlasCoffee/Strategy/q1_growth.belief"),
        ("packaging_is_bottleneck", "Packaging is the current production bottleneck",
         "kref://AtlasCoffee/Operations/packaging.policy"),
        ("rebrand_will_lift_dtc",   "Rebrand will lift DTC subscriptions 20%",
         "kref://AtlasCoffee/Strategy/rebrand.belief"),
        ("decaf_gap_in_market",     "There's a gap in the local decaf market",
         "kref://AtlasCoffee/Markets/decaf.segment"),
        ("expo_pays_back_in_year",  "Specialty Coffee Expo investment pays back within a year",
         "kref://AtlasCoffee/Decisions/attend_specialty_expo.decision"),
        ("tier_pricing_is_optimal", "Current tier pricing is optimized for margin",
         "kref://AtlasCoffee/Strategy/pricing.belief"),
    ]
    for belief_id, text, supports in belief_templates[:N_BELIEFS_ASSERTED]:
        day = rng.randint(0, CORPUS_DAYS - 30)
        log.events.append(Event(
            event_id=next_id("evt_belief"),
            kind=EventKind.BELIEF_ASSERTED,
            occurred_at=ts_for_day(day),
            kref_subject=f"kref://AtlasCoffee/Beliefs/{belief_id}.belief",
            kref_object=supports,
            payload={
                "belief_id": belief_id,
                "text": text,
                "initial_confidence": round(rng.uniform(0.78, 0.95), 2),
                "depends_on": supports,
            },
            summary=f"Belief asserted: {text}",
        ))

    # ── Embedded contradictions — pair a decision with a contradicting belief
    # asserted close in time. The benchmark questions test detection of these.
    contradiction_pairs = [
        ("hire_2_roasters",  "hiring_freeze_active"),
        ("discontinue_festive", "festive_viable"),
        ("expand_into_decaf", "tier_pricing_is_optimal"),
        ("price_promotion_q1", "tier_pricing_is_optimal"),
        ("partner_with_client_w03", "verdant_main_competitor"),
        ("freeze_hiring", "roster_team_understaffed"),
        ("open_second_cafe", "packaging_is_bottleneck"),
        ("renegotiate_w01", "daily_grind_strategic"),
    ]
    for decision_id, belief_id in contradiction_pairs[:N_EMBEDDED_CONTRADICTIONS]:
        log.events.append(Event(
            event_id=next_id("evt_contra"),
            kind=EventKind.BELIEF_ASSERTED,
            occurred_at=ts_for_day(rng.randint(30, CORPUS_DAYS - 5)),
            kref_subject=f"kref://AtlasCoffee/Beliefs/{belief_id}.belief",
            kref_object=f"kref://AtlasCoffee/Decisions/{decision_id}.decision",
            payload={
                "belief_id": belief_id,
                "contradicts_decision": decision_id,
                "is_embedded_contradiction": True,
            },
            summary=(
                f"Belief reinforced: '{belief_id}' (now in tension with "
                f"prior decision '{decision_id}')"
            ),
        ))

    # ── Embedded deprecations — old beliefs explicitly invalidated by date
    deprecation_targets = [
        "tier_pricing_is_optimal",
        "verdant_main_competitor",
        "festive_viable",
        "rebrand_will_lift_dtc",
        "decaf_gap_in_market",
    ]
    for belief_id in deprecation_targets[:N_EMBEDDED_DEPRECATIONS]:
        deprecate_day = rng.randint(60, CORPUS_DAYS - 1)
        log.events.append(Event(
            event_id=next_id("evt_dep"),
            kind=EventKind.DEPRECATION,
            occurred_at=ts_for_day(deprecate_day),
            kref_subject=f"kref://AtlasCoffee/Beliefs/{belief_id}.belief",
            kref_object=None,
            payload={
                "belief_id": belief_id,
                "valid_until": (
                    CORPUS_START_DATE + timedelta(days=deprecate_day)
                ).isoformat(),
            },
            summary=f"Belief deprecated: '{belief_id}'",
        ))

    # ── Wholesale orders ────────────────────────────────────────────────
    for week in range(WEEKS_OF_WHOLESALE):
        for client in world.wholesale_clients:
            day_offset = week * 7 + _delivery_day_offset(client.delivery_day)
            if day_offset >= CORPUS_DAYS:
                continue
            log.events.append(Event(
                event_id=next_id("evt_order"),
                kind=EventKind.WHOLESALE_ORDER,
                occurred_at=ts_for_day(day_offset, hour_jitter=False),
                kref_subject=f"kref://AtlasCoffee/Clients/{client.client_id}.client",
                kref_object=None,
                payload={
                    "client_id": client.client_id,
                    "volume_lbs": client.monthly_volume_lbs // 4,
                    "delivery_day": client.delivery_day,
                },
                summary=(
                    f"Wholesale order: {client.name} — "
                    f"{client.monthly_volume_lbs // 4} lbs"
                ),
            ))

    # Sort the timeline so consumers can stream by date
    log.events.sort(key=lambda e: e.occurred_at)
    return log


def _delivery_day_offset(day: str) -> int:
    """Mon=0, Tue=1, ..., Sun=6 — 2026-01-01 was a Thursday (offset 3)."""
    weekday_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
    target = weekday_map.get(day, 1)
    start_weekday = 3  # 2026-01-01 = Thursday
    return (target - start_weekday) % 7
