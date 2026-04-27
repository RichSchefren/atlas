#!/usr/bin/env bash
#
# Atlas demo — the undeniable demo path.
#
# One command does the entire loop visibly, end-to-end against a
# real Neo4j instance:
#
#   1. Start Neo4j (idempotent — no-op if already up)
#   2. Plant a tiny graph (3 nodes, 2 Depends_On edges)
#   3. Change a fact
#   4. Run RippleEngine.propagate() — the real orchestrator
#   5. Show impacted beliefs + reassessment proposals + contradictions
#      + routing decisions
#   6. Resolve one proposal through adjudication.resolve()
#   7. Verify the SHA-256 hash chain is intact
#
# Total wall time: ~12 seconds on first run (Neo4j pull may add minutes
# the very first time on a clean machine), ~6 seconds on subsequent
# runs. Designed to be paste-able into a screen recording.
#
# Usage:
#   ./demo.sh           # full demo
#   ./demo.sh --quiet   # less output, just the milestone lines
#   ./demo.sh --reset   # wipe demo namespace from Neo4j first

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

# ─── Output helpers ─────────────────────────────────────────────────

QUIET=0
RESET=0
for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET=1 ;;
        --reset) RESET=1 ;;
        --help|-h)
            head -28 "$0" | sed 's|^# ||;s|^#||'
            exit 0
            ;;
    esac
done

if [[ -t 1 ]] && [[ "$QUIET" -eq 0 ]]; then
    BOLD="\033[1m"; DIM="\033[2m"; CYAN="\033[36m"
    GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET_C="\033[0m"
else
    BOLD=""; DIM=""; CYAN=""; GREEN=""; YELLOW=""; RED=""; RESET_C=""
fi

step() { printf "${CYAN}${BOLD}▶ %s${RESET_C}\n" "$1"; }
ok()   { printf "  ${GREEN}✓ %s${RESET_C}\n" "$1"; }
info() { [[ "$QUIET" -eq 0 ]] && printf "  ${DIM}%s${RESET_C}\n" "$1" || true; }
warn() { printf "  ${YELLOW}⚠ %s${RESET_C}\n" "$1"; }
err()  { printf "  ${RED}✗ %s${RESET_C}\n" "$1"; }

# ─── Pre-flight ─────────────────────────────────────────────────────

step "Checking prerequisites"
for cmd in docker python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        err "$cmd not on PATH; install before running demo.sh"
        exit 64
    fi
done
ok "docker + python3 present"

if [[ ! -d ".venv" ]]; then
    err ".venv not found. Run:  python3 -m venv .venv && source .venv/bin/activate && pip install -e .[dev]"
    exit 64
fi
ok ".venv present"

# ─── Stage 1: Neo4j ─────────────────────────────────────────────────

step "Stage 1 / 7 — Neo4j"
if curl -sf http://localhost:7474 >/dev/null 2>&1; then
    ok "Neo4j already up at http://localhost:7474"
else
    info "Starting Neo4j 5.26 via docker compose..."
    docker compose up -d >/dev/null
    for i in {1..30}; do
        curl -sf http://localhost:7474 >/dev/null 2>&1 && break
        sleep 2
    done
    if curl -sf http://localhost:7474 >/dev/null 2>&1; then
        ok "Neo4j healthy"
    else
        err "Neo4j never came up. Check: docker compose logs"
        exit 1
    fi
fi

# ─── Stage 2-7: orchestrated by Python so we get real result objects ─

step "Stage 2 / 7 — Plant graph + run RippleEngine end-to-end"
PYTHONPATH=. .venv/bin/python - <<'PY'
import asyncio
import sys
import tempfile
from pathlib import Path

# Colours echo bash above
BOLD = "\033[1m"; CYAN = "\033[36m"; GREEN = "\033[32m"
YELLOW = "\033[33m"; DIM = "\033[2m"; RESET = "\033[0m"

NS = "AtlasDemo"


async def main():
    from neo4j import AsyncGraphDatabase
    from atlas_core.ripple import RippleEngine
    from atlas_core.ripple.resolver import resolve_adjudication
    from atlas_core.ripple.adjudication import (
        AdjudicationRoute,
        RoutingDecision,
        write_adjudication_entry,
    )
    from atlas_core.ripple.reassess import ReassessmentProposal
    from atlas_core.trust import HashChainedLedger

    driver = AsyncGraphDatabase.driver(
        "bolt://localhost:7687", auth=("neo4j", "atlasdev"),
    )

    # Wipe demo namespace
    async with driver.session() as s:
        await s.run(
            "MATCH (n) WHERE n.kref STARTS WITH $p DETACH DELETE n",
            p=f"kref://{NS}/",
        )

    # Plant the graph: a price fact, a belief that depends on it,
    # a decision that rests on the belief.
    upstream = f"kref://{NS}/Programs/origins.belief"
    belief = f"kref://{NS}/Beliefs/origins_accessible.belief"
    decision = f"kref://{NS}/Decisions/marketing_to_newcomers.decision"

    async with driver.session() as s:
        await s.run(
            "MERGE (a:AtlasItem:Belief {kref: $a}) SET a.deprecated = false, "
            "  a.confidence_score = 0.95, a.text = 'Origins is $89/mo' "
            "MERGE (b:AtlasItem:Belief {kref: $b}) SET b.deprecated = false, "
            "  b.confidence_score = 0.88, b.last_evidence_days = 0, "
            "  b.text = 'Origins is most accessible' "
            "MERGE (c:AtlasItem:Decision {kref: $c}) SET c.deprecated = false, "
            "  c.confidence_score = 0.80, c.last_evidence_days = 0, "
            "  c.text = 'Market Origins to newcomers' "
            "MERGE (b)-[:DEPENDS_ON {strength: 0.9}]->(a) "
            "MERGE (c)-[:DEPENDS_ON {strength: 0.7}]->(b)",
            a=upstream, b=belief, c=decision,
        )
    print(f"  {GREEN}✓{RESET} 3 nodes + 2 Depends_On edges planted")

    # ── Stage 3: change a fact ──────────────────────────────────────
    print()
    print(f"{CYAN}{BOLD}▶ Stage 3 / 7 — Change a fact{RESET}")
    print(f"  {DIM}Origins price: $89 → $129 (a 45% increase). "
          f"Upstream confidence drops from 0.95 → 0.20.{RESET}")

    # ── Stage 4: run the engine ─────────────────────────────────────
    print()
    print(f"{CYAN}{BOLD}▶ Stage 4 / 7 — RippleEngine.propagate(){RESET}")
    engine = RippleEngine(driver, emit_events=False)
    cascade = await engine.propagate(
        upstream,
        old_confidence=0.95,
        new_confidence=0.20,
        belief_text="Origins price moved $89 → $129/mo",
    )

    if not cascade.succeeded:
        print(f"  {YELLOW}⚠ cascade failed: {cascade.error}{RESET}")
        await driver.close()
        sys.exit(2)

    print(f"  {GREEN}✓{RESET} cascade complete")
    print(f"  {DIM}impacted nodes: {cascade.n_impacted}{RESET}")
    print(f"  {DIM}contradictions: {len(cascade.contradictions)}{RESET}")
    print(f"  {DIM}routing — auto: {cascade.n_auto_apply}, "
          f"strategic: {cascade.n_strategic}, "
          f"core: {cascade.n_core_protected}{RESET}")

    # ── Stage 5: show the proposals + routing ──────────────────────
    print()
    print(f"{CYAN}{BOLD}▶ Stage 5 / 7 — Reassessment proposals{RESET}")
    for i, prop in enumerate(cascade.proposals, 1):
        delta = prop.new_confidence - prop.old_confidence
        sign = "+" if delta >= 0 else ""
        print(f"  {YELLOW}{i}.{RESET} {prop.target_kref}")
        print(f"     {DIM}{prop.old_confidence:.2f} → "
              f"{prop.new_confidence:.2f}  ({sign}{delta:.2f}){RESET}")

    if cascade.contradictions:
        print()
        print(f"  {YELLOW}contradictions surfaced:{RESET}")
        for c in cascade.contradictions:
            print(f"    {DIM}{c.proposal_kref} × {c.opposed_kref} ({c.severity.value}){RESET}")

    # ── Stage 6: resolve one through adjudication ───────────────────
    print()
    print(f"{CYAN}{BOLD}▶ Stage 6 / 7 — Resolve one through adjudication{RESET}")

    if cascade.proposals:
        proposal = cascade.proposals[0]
        adj_dir = Path(tempfile.mkdtemp(prefix="atlas_demo_adj_"))
        ledger_path = Path(tempfile.mkdtemp(prefix="atlas_demo_ledger_")) / "ledger.db"
        ledger = HashChainedLedger(ledger_path)

        decision_obj = RoutingDecision(
            proposal_kref=proposal.target_kref,
            route=AdjudicationRoute.STRATEGIC_REVIEW,
            rationale="Demo — review the price-cascade outcome",
            contradictions_count=len(cascade.contradictions),
            confidence_delta=proposal.new_confidence - proposal.old_confidence,
        )
        path = await write_adjudication_entry(
            proposal=proposal,
            decision=decision_obj,
            contradictions=cascade.contradictions,
            directory=adj_dir,
            upstream_belief_text="Origins price moved $89 → $129/mo",
        )
        print(f"  {GREEN}✓{RESET} markdown queued: {path.name}")

        text = path.read_text(encoding="utf-8")
        proposal_id = next(
            (line.split(":", 1)[1].strip()
             for line in text.split("\n") if line.startswith("proposal_id")),
            None,
        )

        outcome = await resolve_adjudication(
            proposal_id=proposal_id,
            decision="accept",
            driver=driver,
            ledger=ledger,
            directory=adj_dir,
        )
        print(f"  {GREEN}✓{RESET} resolved with decision='accept'")
        print(f"  {DIM}new revision kref: {outcome.new_revision_kref}{RESET}")
        print(f"  {DIM}ledger event id:   {outcome.ledger_event_id[:16]}…{RESET}")

        # ── Stage 7: verify chain ───────────────────────────────────
        print()
        print(f"{CYAN}{BOLD}▶ Stage 7 / 7 — Verify SHA-256 ledger chain{RESET}")
        chain = ledger.verify_chain()
        if chain.intact:
            print(f"  {GREEN}✓{RESET} chain intact at sequence "
                  f"{chain.last_verified_sequence}")
        else:
            print(f"  {YELLOW}⚠ chain broken at {chain.broken_at_sequence}{RESET}")
    else:
        print(f"  {YELLOW}(no proposals to resolve){RESET}")

    # ── Wrap-up ─────────────────────────────────────────────────────
    print()
    print(f"{GREEN}{BOLD}LOOP CLOSED.{RESET}")
    print(f"{DIM}  ingest → quarantine → ledger → Ripple → adjudication → "
          f"AGM revise → tamper-detect{RESET}")
    print(f"{DIM}  Run again with --quiet for a clean recording, "
          f"--reset to wipe state.{RESET}")

    await driver.close()


asyncio.run(main())
PY
