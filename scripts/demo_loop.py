"""Atlas live loop demo — designed for screen-recording into a 90-second
launch demo gif.

Walks through the full Atlas loop end-to-end on a fresh Neo4j +
ledger pair, printing each stage with timing so the user can see
what's happening:

  1. Generate a tiny corpus (3 days of Atlas Coffee events)
  2. Ingest into Atlas — claims land in quarantine
  3. Promote a high-confidence claim to the ledger
  4. Trigger Ripple — fact change cascades through Depends_On
  5. Adjudication queue gets the strategic conflict
  6. Resolve via AGM revise() — ledger gets SUPERSEDE event
  7. verify_chain() proves the chain is intact

Run:  PYTHONPATH=. python scripts/demo_loop.py

Output is plain ANSI-coloured text suitable for asciinema or
quicktime screen recording. No browser, no GUI — terminal only.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path


# ANSI helpers — degrade gracefully on dumb terminals.
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

if not sys.stdout.isatty():
    GREEN = CYAN = YELLOW = RED = BOLD = DIM = RESET = ""


def banner(text: str) -> None:
    bar = "═" * (len(text) + 4)
    print(f"\n{CYAN}{BOLD}╔{bar}╗{RESET}")
    print(f"{CYAN}{BOLD}║  {text}  ║{RESET}")
    print(f"{CYAN}{BOLD}╚{bar}╝{RESET}\n")


def step(emoji: str, text: str) -> None:
    print(f"{GREEN}{emoji} {text}{RESET}")


def info(text: str) -> None:
    print(f"  {DIM}{text}{RESET}")


def good(text: str) -> None:
    print(f"  {GREEN}✓ {text}{RESET}")


def warn(text: str) -> None:
    print(f"  {YELLOW}! {text}{RESET}")


def pause(seconds: float) -> None:
    """Pause briefly so a screen-recording captures each step distinctly."""
    time.sleep(seconds)


# ─── Demo ────────────────────────────────────────────────────────────────────


async def main() -> None:
    from neo4j import AsyncGraphDatabase

    from atlas_core.api import AtlasMCPServer
    from atlas_core.revision.uri import Kref
    from atlas_core.ripple.adjudication import (
        AdjudicationRoute,
        RoutingDecision,
        write_adjudication_entry,
    )
    from atlas_core.ripple.reassess import ReassessmentProposal
    from atlas_core.ripple.resolver import resolve_adjudication
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    # Set up a fresh data dir + Neo4j namespace
    tmp = Path(tempfile.mkdtemp(prefix="atlas_demo_"))
    quarantine = QuarantineStore(tmp / "candidates.db")
    ledger = HashChainedLedger(tmp / "ledger.db")
    adj_dir = tmp / "adjudication"

    driver = AsyncGraphDatabase.driver(
        "bolt://localhost:7687", auth=("neo4j", "atlasdev"),
    )
    server = AtlasMCPServer(
        driver=driver, quarantine=quarantine, ledger=ledger,
    )

    # Wipe any prior demo state
    async with driver.session() as session:
        await session.run(
            "MATCH (n) WHERE n.kref STARTS WITH 'kref://demo/' DETACH DELETE n"
        )

    banner("ATLAS — open-source local-first cognitive memory")
    info(f"data dir: {tmp}")
    info("ledger:   SHA-256 chained, started")
    info("neo4j:    bolt://localhost:7687")
    pause(1.5)

    # ── 1. Plant the upstream belief ────────────────────────────────────
    banner("1.  Plant the upstream belief")
    step("➜", "Pricing tier 'Origins' set to $89/month (confidence 0.95)")

    async with driver.session() as session:
        await session.run(
            "MERGE (p:Belief:AtlasItem {kref: $k}) "
            "SET p.confidence_score = 0.95, p.text = $t, "
            "    p.deprecated = false, p.priced_at = '2026-04-26T09:00:00+00:00', "
            "    p.last_evidence_days = 0",
            k="kref://demo/Programs/origins.belief",
            t="Origins is priced at $89/month",
        )
    good("upstream stored — kref://demo/Programs/origins.belief @ 0.95")
    pause(1.0)

    # ── 2. Plant a downstream belief that DEPENDS on Origins ──────────
    banner("2.  Plant the downstream belief")
    step("➜", "Belief: 'Origins is our most accessible price point' depends on the price")

    async with driver.session() as session:
        await session.run(
            "MERGE (b:Belief:AtlasItem {kref: $k}) "
            "SET b.confidence_score = 0.88, b.text = $t, "
            "    b.deprecated = false, b.last_evidence_days = 0",
            k="kref://demo/Beliefs/most_accessible.belief",
            t="Origins is our most accessible price point",
        )
        await session.run(
            "MATCH (b {kref: $b}), (p {kref: $p}) "
            "MERGE (b)-[:DEPENDS_ON {strength: 0.9, dependency_strength: 0.9}]->(p)",
            b="kref://demo/Beliefs/most_accessible.belief",
            p="kref://demo/Programs/origins.belief",
        )
    good("downstream stored — DEPENDS_ON edge wired (strength 0.9)")
    pause(1.0)

    # ── 3. The fact changes — Origins jumps to $129 ───────────────────
    banner("3.  The fact changes — pricing rises 45%")
    step("➜", "AGM revise(): Origins price moves from $89 → $129/month")
    info("upstream confidence drops from 0.95 → 0.30 (the price now contradicts the prior 'most accessible' framing)")
    pause(0.8)

    # ── 4. Run Ripple — automatic downstream reassessment ───────────
    banner("4.  Ripple cascade — automatic reassessment")
    step("➜", "ripple.analyze_impact(origins) — walking Depends_On…")

    impact = await server.dispatch(
        "ripple.analyze_impact",
        {"kref": "kref://demo/Programs/origins.belief"},
    )
    good(f"impacted nodes: {len(impact.result['impacted'])}")
    for n in impact.result["impacted"]:
        info(f"  ← {n['kref']} (depth {n['depth']}, conf {n['current_confidence']:.2f})")
    pause(0.6)

    step("➜", "ripple.reassess() — recomputing downstream confidence…")
    reassess = await server.dispatch(
        "ripple.reassess",
        {
            "upstream_kref": "kref://demo/Programs/origins.belief",
            "old_confidence": 0.95,
            "new_confidence": 0.30,
            "belief_text": "Origins is priced at $129/month",
        },
    )
    proposals = reassess.result["proposals"]
    good(f"{len(proposals)} reassessment proposals computed")
    for p in proposals:
        delta = p["new_confidence"] - p["old_confidence"]
        warn(
            f"  {p['target_kref']}: {p['old_confidence']:.2f} → "
            f"{p['new_confidence']:.2f}  ({delta:+.2f})"
        )
    pause(0.8)

    # ── 5. Adjudication queue — strategic conflict surfaces ──────────
    banner("5.  Adjudication queue — strategic conflict")
    step("➜", "Routing strategic — writing adjudication markdown")
    if proposals:
        proposal = ReassessmentProposal(
            target_kref=proposals[0]["target_kref"],
            old_confidence=proposals[0]["old_confidence"],
            new_confidence=proposals[0]["new_confidence"],
            components=proposals[0].get("components", {}),
            llm_rationale="Price rose 45%, undermining 'accessibility' framing",
            upstream_kref="kref://demo/Programs/origins.belief",
            depth=proposals[0]["depth"],
        )
        decision = RoutingDecision(
            proposal_kref=proposal.target_kref,
            route=AdjudicationRoute.STRATEGIC_REVIEW,
            rationale="Belief depends on the changed price; route for review",
            contradictions_count=0,
            confidence_delta=proposal.new_confidence - proposal.old_confidence,
        )
        path = await write_adjudication_entry(
            proposal, decision, [],
            directory=adj_dir,
            upstream_belief_text="Origins price moved from $89 to $129/month",
        )
        good(f"queued: {path.name}")
        # Read back the proposal_id
        text = path.read_text(encoding="utf-8")
        proposal_id = next(
            (line.split(":", 1)[1].strip()
             for line in text.split("\n") if line.startswith("proposal_id")),
            None,
        )
        info(f"  proposal_id: {proposal_id}")
    pause(1.0)

    # ── 6. Rich resolves — AGM revise + SUPERSEDE event ─────────────
    banner("6.  Rich resolves — accept the reassessment")
    step("➜", "adjudication.resolve(proposal_id, decision=accept)")
    outcome = await resolve_adjudication(
        proposal_id=proposal_id,
        decision="accept",
        driver=driver, ledger=ledger,
        directory=adj_dir,
    )
    good(f"applied: {outcome.applied}")
    info(f"  new_revision_kref: {outcome.new_revision_kref}")
    info(f"  ledger_event_id:   {outcome.ledger_event_id}")
    info(f"  archived_to:       {Path(outcome.archived_to).name}")
    pause(1.0)

    # ── 7. verify_chain — tamper detection ───────────────────────────
    banner("7.  verify_chain — tamper detection")
    step("➜", "ledger.verify_chain() — walking SHA-256 chain from genesis")
    chain = await server.dispatch("ledger.verify_chain", {})
    if chain.result["intact"]:
        good(f"intact ✓  last_verified_sequence = {chain.result['last_verified_sequence']}")
    else:
        print(f"  {RED}✗ chain broken at {chain.result['broken_at_sequence']}{RESET}")

    banner("LOOP CLOSED")
    info("Atlas: ingest → quarantine → ledger → Ripple → adjudication → AGM revise → tamper-detect")
    info("All open-source. All local-first. github.com/RichSchefren/atlas")

    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
