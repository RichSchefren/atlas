"""Corpus + question writer.

Materializes the EventLog into:
  corpus/
    meetings/<NN>.md       — synthetic meeting transcripts (Limitless-style)
    vault/<slug>.md        — synthetic Obsidian markdown notes
    screen_events/log.csv  — synthetic Screenpipe-style rows
    messages/messages.jsonl — synthetic iMessage stream
  ground_truth.json        — final state of the typed graph
  gold/<category>.jsonl    — generated questions for each of the 7 categories
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmarks.business_mem_bench.corpus_generator.business import (
    CORPUS_END_DATE,
    AtlasCoffeeWorld,
)
from benchmarks.business_mem_bench.corpus_generator.events import (
    EventKind,
    EventLog,
    generate_events,
)

# ─── Public entry points ────────────────────────────────────────────────────


def generate_corpus(
    out_dir: Path | str, *, seed: int = 42,
) -> tuple[EventLog, Path]:
    """Write the full BusinessMemBench corpus to `out_dir`. Returns
    (event_log, ground_truth_path) so question generation can chain."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    world = AtlasCoffeeWorld()
    log = generate_events(world, seed=seed)

    # Per-stream subdirs
    (out / "meetings").mkdir(exist_ok=True)
    (out / "vault").mkdir(exist_ok=True)
    (out / "screen_events").mkdir(exist_ok=True)
    (out / "messages").mkdir(exist_ok=True)

    _write_meetings(log, world, out / "meetings")
    _write_vault(log, world, out / "vault")
    _write_screen_events(log, out / "screen_events" / "log.csv")
    _write_messages(log, out / "messages" / "messages.jsonl")

    # Persist the raw event log too — useful for debugging
    log.write_jsonl(out / "events.jsonl")

    gt_path = out / "ground_truth.json"
    gt_path.write_text(
        json.dumps(_compute_ground_truth(log, world), indent=2),
    )
    return log, gt_path


def generate_questions(
    out_dir: Path | str, *, seed: int = 42,
) -> dict[str, int]:
    """Write gold/<category>.jsonl files. Returns counts by category."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gold = out / "gold"
    gold.mkdir(exist_ok=True)

    world = AtlasCoffeeWorld()
    log = generate_events(world, seed=seed)

    counts: dict[str, int] = {}
    counts["propagation"]   = _write_propagation_questions(log, gold)
    counts["contradiction"] = _write_contradiction_questions(log, gold)
    counts["lineage"]       = _write_lineage_questions(log, gold)
    counts["cross_stream"]  = _write_cross_stream_questions(log, gold)
    counts["historical"]    = _write_historical_questions(log, world, gold)
    counts["provenance"]    = _write_provenance_questions(log, gold)
    counts["forgetfulness"] = _write_forgetfulness_questions(log, gold)
    return counts


# ─── Corpus writers ─────────────────────────────────────────────────────────


def _write_meetings(log: EventLog, world: AtlasCoffeeWorld, out: Path) -> None:
    """Group events by ISO week → one synthetic standup transcript per week."""
    by_week: dict[str, list] = {}
    for event in log.events:
        wk_key = datetime.fromisoformat(event.occurred_at).strftime("%Y-W%V")
        by_week.setdefault(wk_key, []).append(event)

    for wk, events in sorted(by_week.items()):
        path = out / f"{wk}-standup.md"
        attendees = ", ".join(e.name for e in world.employees[:6])
        action_items = [
            f"  - {e.summary}"
            for e in events
            if e.kind in {
                EventKind.DECISION,
                EventKind.HIRE,
                EventKind.ROLE_CHANGE,
                EventKind.PRICING_CHANGE,
            }
        ]
        decisions = [
            f"  - {e.summary}"
            for e in events if e.kind == EventKind.DECISION
        ]
        body = f"""---
type: meeting
week: {wk}
attendees: [{attendees}]
event_count: {len(events)}
---

# Weekly Standup — {wk}

## Attendees
{attendees}

## Action items
{chr(10).join(action_items) if action_items else "  - (none this week)"}

## Decisions
{chr(10).join(decisions) if decisions else "  - (none this week)"}

## Notes
Synthetic transcript generated from {len(events)} timeline events.
"""
        path.write_text(body, encoding="utf-8")


def _write_vault(log: EventLog, world: AtlasCoffeeWorld, out: Path) -> None:
    """One markdown file per asserted belief; updated on revisions."""
    by_belief: dict[str, list] = {}
    for e in log.events:
        if e.kind in {EventKind.BELIEF_ASSERTED, EventKind.BELIEF_REVISED, EventKind.DEPRECATION}:
            bid = e.payload.get("belief_id", "")
            if bid:
                by_belief.setdefault(bid, []).append(e)

    for bid, events in by_belief.items():
        path = out / f"belief-{bid}.md"
        timeline = "\n".join(
            f"- {e.occurred_at[:10]} — {e.summary}" for e in events
        )
        first = events[0]
        body = f"""---
type: belief
belief_id: {bid}
title: {first.payload.get('text', bid)}
---

# {first.payload.get('text', bid)}

Initial confidence: {first.payload.get('initial_confidence', 'unknown')}

## Timeline
{timeline}
"""
        path.write_text(body, encoding="utf-8")


def _write_screen_events(log: EventLog, path: Path) -> None:
    """Synthetic Screenpipe-style CSV — one row per pricing/decision event."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "app", "transcription"])
        for e in log.events:
            if e.kind not in {EventKind.PRICING_CHANGE, EventKind.DECISION}:
                continue
            writer.writerow([e.occurred_at, "Slack", e.summary])


def _write_messages(log: EventLog, path: Path) -> None:
    """Synthetic iMessage JSONL — informal references to decisions + orders."""
    rng = random.Random(log.seed + 1000)
    with path.open("w", encoding="utf-8") as f:
        for e in log.events:
            if e.kind == EventKind.WHOLESALE_ORDER:
                msg = {
                    "timestamp": e.occurred_at,
                    "from": "rich",
                    "to": e.payload.get("client_id", "unknown"),
                    "text": rng.choice([
                        "Order confirmed for tomorrow.",
                        "Truck rolling Tuesday.",
                        "Shipment scheduled.",
                    ]),
                }
                f.write(json.dumps(msg, separators=(",", ":")))
                f.write("\n")


# ─── Ground truth ───────────────────────────────────────────────────────────


def _compute_ground_truth(
    log: EventLog, world: AtlasCoffeeWorld,
) -> dict[str, Any]:
    """End-of-window state of the typed graph. Used for historical +
    forgetfulness scoring."""
    # Latest pricing per product
    final_prices: dict[str, float] = {p.product_id: p.initial_price for p in world.product_lines}
    for e in log.by_kind(EventKind.PRICING_CHANGE):
        final_prices[e.payload["product_id"]] = e.payload["new_price"]

    # Deprecated beliefs
    deprecated = [
        e.payload["belief_id"]
        for e in log.by_kind(EventKind.DEPRECATION)
    ]

    return {
        "as_of": CORPUS_END_DATE.isoformat(),
        "n_events": len(log.events),
        "final_prices_by_product": final_prices,
        "deprecated_beliefs": deprecated,
        "n_decisions": len(log.by_kind(EventKind.DECISION)),
        "n_beliefs_asserted": len(log.by_kind(EventKind.BELIEF_ASSERTED)),
        "n_wholesale_orders": len(log.by_kind(EventKind.WHOLESALE_ORDER)),
    }


# ─── Question writers ───────────────────────────────────────────────────────


# Paraphrase templates per category — each (template, surface_id_suffix)
# pair turns one underlying event into a fresh question with the same
# scoring payload but a different natural-language surface. Stays
# deterministic so corpus regeneration is reproducible.
_PROPAGATION_PHRASINGS: tuple[tuple[str, str], ...] = (
    ("After pricing on product {pid} moved from ${old:.2f} to ${new:.2f}, "
     "what is the system's confidence in 'product is most accessible'?", "v1"),
    ("Product {pid} pricing changed ${old:.2f} → ${new:.2f}. Confidence "
     "in the 'most accessible' belief?", "v2"),
    ("Given pricing on {pid} now at ${new:.2f} (was ${old:.2f}), "
     "report the propagated confidence on its accessibility belief.", "v3"),
)
_LINEAGE_PHRASINGS: tuple[tuple[str, str], ...] = (
    ("What was the supporting belief chain for decision '{did}'?", "v1"),
    ("Trace the lineage of decision '{did}' back to its supporting kref.", "v2"),
)
_HISTORICAL_PHRASINGS: tuple[tuple[str, str], ...] = (
    ("What was the price for product {pid} on {day}?", "v1"),
    ("On {day}, what price did product {pid} carry?", "v2"),
    ("Report the price of {pid} as of end-of-day {day}.", "v3"),
)


def _write_propagation_questions(log: EventLog, gold: Path) -> int:
    """Each pricing change creates a propagation question — does the
    'most accessible' belief get its confidence reassessed?"""
    out_path = gold / "propagation.jsonl"
    # POLICY DECISION (2026-04-26): bands are FROZEN to Ripple's
    # current output range — additive-with-damping at α=0.5 + the
    # default β/γ/δ weights from atlas_core/ripple/reassess.py.
    #
    # Why frozen and not adaptive: the benchmark's purpose is to
    # publish Atlas's expected behavior. If a future PR changes
    # Ripple's weights, the resulting BMB score drop surfaces the
    # behavior change EXPLICITLY rather than letting bands
    # auto-recalibrate around silent drift. CI gates regressions
    # at >= 0.90 (.github/workflows/test.yml). When Ripple weights
    # change intentionally, update both the spec doc AND these
    # bands in the same commit.
    written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for e in log.by_kind(EventKind.PRICING_CHANGE):
            old, new = e.payload["old_price"], e.payload["new_price"]
            band = (
                {"min": 0.7, "max": 1.0}
                if new <= old
                else {"min": 0.5, "max": 0.85}
            )
            new_conf = max(0.0, min(1.0, 0.9 - (new - old) / old))
            for template, suffix in _PROPAGATION_PHRASINGS:
                qid = f"prop_{written + 1:04d}"
                payload = {
                    "id": qid,
                    "question": template.format(
                        pid=e.payload["product_id"], old=old, new=new,
                    ),
                    "scoring": "binary_in_band",
                    "correct_answer_band": band,
                    "upstream_kref": e.kref_subject,
                    "old_confidence": 0.9,
                    "new_confidence": new_conf,
                    "_surface": suffix,
                }
                f.write(json.dumps(payload, separators=(",", ":")))
                f.write("\n")
                written += 1
    return written


def _write_contradiction_questions(log: EventLog, gold: Path) -> int:
    out_path = gold / "contradiction.jsonl"
    written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for e in log.by_kind(EventKind.BELIEF_ASSERTED):
            if not e.payload.get("is_embedded_contradiction"):
                continue
            decision_id = e.payload["contradicts_decision"]
            belief_id = e.payload["belief_id"]
            qid = f"contra_{written + 1:04d}"
            payload = {
                "id": qid,
                "question": (
                    f"Is the belief '{belief_id}' in tension with the prior "
                    f"decision '{decision_id}'?"
                ),
                "scoring": "f1_on_pair_recall",
                "expected_pair": [
                    f"kref://AtlasCoffee/Decisions/{decision_id}.decision",
                    f"kref://AtlasCoffee/Beliefs/{belief_id}.belief",
                ],
                "proposals": [],
            }
            f.write(json.dumps(payload, separators=(",", ":")))
            f.write("\n")
            written += 1
    return written


def _write_lineage_questions(log: EventLog, gold: Path) -> int:
    """For each decision that hangs off a belief, ask the system to
    trace the lineage."""
    out_path = gold / "lineage.jsonl"
    written = 0
    decisions = log.by_kind(EventKind.DECISION)
    with out_path.open("w", encoding="utf-8") as f:
        for d in decisions:
            for template, suffix in _LINEAGE_PHRASINGS:
                qid = f"lineage_{written + 1:04d}"
                payload = {
                    "id": qid,
                    "question": template.format(did=d.payload["decision_id"]),
                    "scoring": "ordered_chain_recall_f1",
                    "correct_chain": [
                        d.kref_subject,
                        d.kref_object or "",
                    ],
                    "_surface": suffix,
                }
                f.write(json.dumps(payload, separators=(",", ":")))
                f.write("\n")
                written += 1
    return written


def _write_cross_stream_questions(log: EventLog, gold: Path) -> int:
    """One question per wholesale client — which streams reference them?"""
    out_path = gold / "cross_stream.jsonl"
    written = 0
    seen_clients: set[str] = set()
    with out_path.open("w", encoding="utf-8") as f:
        for e in log.by_kind(EventKind.WHOLESALE_ORDER):
            cid = e.payload["client_id"]
            if cid in seen_clients:
                continue
            seen_clients.add(cid)
            qid = f"cross_{written + 1:04d}"
            payload = {
                "id": qid,
                "question": (
                    f"Which source streams contain references to client {cid}?"
                ),
                "scoring": "cross_stream_overlap",
                "expected_sources": ["atlas_observational", "atlas_chat_history"],
                "subject_kref": e.kref_subject,
            }
            f.write(json.dumps(payload, separators=(",", ":")))
            f.write("\n")
            written += 1
    return written


def _write_historical_questions(
    log: EventLog, world: AtlasCoffeeWorld, gold: Path,
) -> int:
    """For each pricing change, ask: what was the price the day BEFORE
    the change? Asking about the change-day itself is ambiguous (was it
    the old or new price during the day?), so we shift back one day —
    Atlas's strict-before-cutoff query is unambiguously correct."""
    from datetime import date as _date
    from datetime import timedelta as _td

    out_path = gold / "historical.jsonl"
    written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for e in log.by_kind(EventKind.PRICING_CHANGE):
            change_day = _date.fromisoformat(e.occurred_at[:10])
            day_before = (change_day - _td(days=1)).isoformat()
            for template, suffix in _HISTORICAL_PHRASINGS:
                qid = f"hist_{written + 1:04d}"
                payload = {
                    "id": qid,
                    "question": template.format(
                        pid=e.payload["product_id"], day=day_before,
                    ),
                    "scoring": "historical_exact",
                    "correct_answer": f"${e.payload['old_price']:.2f}",
                    "_surface": suffix,
                }
                f.write(json.dumps(payload, separators=(",", ":")))
                f.write("\n")
                written += 1
    return written


def _write_provenance_questions(log: EventLog, gold: Path) -> int:
    """For each belief, ask for the source episode kref chain."""
    out_path = gold / "provenance.jsonl"
    written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for e in log.by_kind(EventKind.BELIEF_ASSERTED):
            qid = f"prov_{written + 1:04d}"
            payload = {
                "id": qid,
                "question": (
                    f"What is the source provenance chain for belief "
                    f"'{e.payload.get('belief_id', '')}'?"
                ),
                "scoring": "provenance_chain",
                "expected_evidence_kref": e.kref_subject,
            }
            f.write(json.dumps(payload, separators=(",", ":")))
            f.write("\n")
            written += 1
    return written


def _write_forgetfulness_questions(log: EventLog, gold: Path) -> int:
    """Each deprecation produces a forgetfulness question — the
    deprecated kref must NOT be returned as active."""
    out_path = gold / "forgetfulness.jsonl"
    written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for e in log.by_kind(EventKind.DEPRECATION):
            bid = e.payload["belief_id"]
            qid = f"forget_{written + 1:04d}"
            payload = {
                "id": qid,
                "question": (
                    f"Does the active belief base contain the deprecated "
                    f"belief '{bid}'?"
                ),
                "scoring": "forgetfulness",
                "deprecated_krefs": [
                    f"kref://AtlasCoffee/Beliefs/{bid}.belief",
                ],
            }
            f.write(json.dumps(payload, separators=(",", ":")))
            f.write("\n")
            written += 1
    return written
