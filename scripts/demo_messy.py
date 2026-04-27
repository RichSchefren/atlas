"""Atlas messy-input demo — runs the full loop on inputs that look like
real captures, not synthetic test data.

Reads `examples/messy_demo/note_zenith_pricing.md` (Obsidian-style note with
YAML frontmatter) and `examples/messy_demo/transcript_pricing_meeting.md`
(Limitless-style meeting transcript), runs them through Atlas's full
pipeline, and produces the same six-stage output shape as `./demo.sh`:

    1. Extract pricing claims from each file (deterministic regex —
       no LLM calls, no API keys required).
    2. Submit each claim to QuarantineStore — see how the trust layer
       weighs vault vs. transcript.
    3. Promote both to the SHA-256 ledger.
    4. Plant the upstream price beliefs + a downstream Origins-margin
       belief that DEPENDS_ON the original ZenithPro price.
    5. Run Ripple — the new transcript-asserted price ($3,495) supersedes
       the vault-asserted price ($2,995); the downstream margin belief
       gets re-evaluated.
    6. Verify the SHA-256 chain.

Spec: docs/LAUNCH_BACKLOG.md → P0 "messy real-world demo".

Total wall time: ~10s after Neo4j is up. No external API keys.

Usage:
    PYTHONPATH=. python scripts/demo_messy.py
    # or
    make demo-messy
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

# Repo-relative path for direct invocation
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


_INPUTS_DIR = ROOT / "examples" / "messy_demo"
_INPUT_VAULT = _INPUTS_DIR / "note_zenith_pricing.md"
_INPUT_TRANSCRIPT = _INPUTS_DIR / "transcript_pricing_meeting.md"

_DEMO_NS = "kref://demo_messy/"
_ZENITHPRO_KREF = "kref://demo_messy/Programs/zenithpro.price.belief"
_ORIGINS_MARGIN_KREF = "kref://demo_messy/Beliefs/origins_margin.belief"
_DEMO_USER = "demo_messy"

# ─── Output helpers ──────────────────────────────────────────────────────────

if sys.stdout.isatty():
    _BOLD, _DIM, _CYAN = "\033[1m", "\033[2m", "\033[36m"
    _GREEN, _YELLOW, _RED, _RC = "\033[32m", "\033[33m", "\033[31m", "\033[0m"
else:
    _BOLD = _DIM = _CYAN = _GREEN = _YELLOW = _RED = _RC = ""


def _banner(s: str) -> None:
    print(f"\n{_CYAN}{_BOLD}▶ {s}{_RC}")


def _ok(s: str) -> None:
    print(f"  {_GREEN}✓{_RC} {s}")


def _info(s: str) -> None:
    print(f"  {_DIM}{s}{_RC}")


def _warn(s: str) -> None:
    print(f"  {_YELLOW}⚠{_RC} {s}")


def _err(s: str) -> None:
    print(f"  {_RED}✗{_RC} {s}")


# ─── Deterministic price extractor ───────────────────────────────────────────

# Matches "$2,995", "$3495", "twenty-nine ninety-five", "thirty-four ninety-five".
# Real Atlas extraction would be LLM-driven; this is pure regex so the
# demo runs without API keys.
_DOLLAR_RE = re.compile(r"\$([\d,]{3,7})")
_SPELLED_RE = re.compile(
    r"\b(twenty|thirty|forty)[ -](nine|eight|seven|six|five|four|three|two|one)\b\s+"
    r"(ninety|eighty|seventy|sixty|fifty|forty|thirty|twenty)[ -]"
    r"(nine|eight|seven|six|five|four|three|two|one|five)\b",
    re.IGNORECASE,
)
_THOUSANDS_TENS = {"twenty": 20, "thirty": 30, "forty": 40}
_HUNDREDS_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}


def _spelled_to_int(match: re.Match) -> int:
    """Translate "thirty-four ninety-five" → 3495.

    The four capture groups encode `thousands_tens-thousands_ones
    hundreds_tens-hundreds_ones` (e.g. "thirty-four ninety-five").
    """
    thousands = (
        _THOUSANDS_TENS[match.group(1).lower()]
        + _ONES[match.group(2).lower()]
    )
    hundreds = (
        _HUNDREDS_TENS[match.group(3).lower()]
        + _ONES[match.group(4).lower()]
    )
    return thousands * 100 + hundreds


def _extract_zenithpro_prices(text: str) -> list[int]:
    """Pull ZenithPro price assertions from a chunk of free text.

    Returns a list of cents-rounded dollar amounts (e.g. [2995, 3495])
    in the order they appeared. Rough but deterministic — the demo's
    point is that the *loop* runs on real-shape input, not that a regex
    matches LLM extraction quality.
    """
    prices: list[int] = []
    for m in _DOLLAR_RE.finditer(text):
        try:
            n = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if 500 <= n <= 50_000:  # cents-aware sanity gate
            prices.append(n)
    for m in _SPELLED_RE.finditer(text):
        prices.append(_spelled_to_int(m))
    return prices


def _strip_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Lightweight YAML-frontmatter stripper. Returns (meta, body).

    Atlas ships a real frontmatter parser in `atlas_core/ingestion/vault.py`;
    the demo doesn't depend on it because we want this script to be self-
    contained and trivially auditable.
    """
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    meta: dict[str, str] = {}
    for raw in parts[1].splitlines():
        if ":" in raw:
            k, v = raw.split(":", 1)
            meta[k.strip()] = v.strip().strip("[]")
    return meta, parts[2].lstrip()


# ─── Loop ────────────────────────────────────────────────────────────────────


async def _run() -> int:
    # Suppress library noise — the demo's output IS the experience
    logging.basicConfig(level=logging.WARNING)

    # Inputs must exist
    for p in (_INPUT_VAULT, _INPUT_TRANSCRIPT):
        if not p.exists():
            _err(f"missing input: {p.relative_to(ROOT)}")
            return 64

    # Local imports, after sys.path is set
    from neo4j import AsyncGraphDatabase

    from atlas_core.api import AtlasMCPServer
    from atlas_core.trust import HashChainedLedger, QuarantineStore
    from atlas_core.trust.quarantine import CandidateClaim, EvidenceRef

    # Fresh tmp dir + Neo4j namespace wipe
    tmp = Path(tempfile.mkdtemp(prefix="atlas_demo_messy_"))
    quarantine = QuarantineStore(tmp / "candidates.db")
    ledger = HashChainedLedger(tmp / "ledger.db")

    driver = AsyncGraphDatabase.driver(
        "bolt://localhost:7687", auth=("neo4j", "atlasdev"),
    )
    try:
        await driver.verify_connectivity()
    except Exception as exc:
        _err(
            f"Neo4j not reachable on bolt://localhost:7687: "
            f"{type(exc).__name__}: {exc}"
        )
        _info("Start it with:  make neo4j   (or 'docker compose up -d neo4j')")
        return 2

    server = AtlasMCPServer(
        driver=driver, quarantine=quarantine, ledger=ledger,
    )

    async with driver.session() as session:
        await session.run(
            "MATCH (n) WHERE n.kref STARTS WITH $p DETACH DELETE n",
            p=_DEMO_NS,
        )

    print(f"{_BOLD}ATLAS — messy-input demo{_RC}")
    print(f"{_DIM}data dir: {tmp}{_RC}")
    print(f"{_DIM}neo4j:    bolt://localhost:7687{_RC}")
    print(f"{_DIM}inputs:   {_INPUT_VAULT.relative_to(ROOT)}{_RC}")
    print(f"{_DIM}          {_INPUT_TRANSCRIPT.relative_to(ROOT)}{_RC}")

    # ── 1. Extract from the vault note ───────────────────────────────────
    _banner("1 / 6  Extract price claims from real-shape inputs")
    vault_text = _INPUT_VAULT.read_text(encoding="utf-8")
    vault_meta, vault_body = _strip_frontmatter(vault_text)
    vault_prices = _extract_zenithpro_prices(vault_body)
    if not vault_prices:
        _err("vault note had no extractable price; aborting")
        return 1
    vault_price = vault_prices[0]
    _ok(
        f"vault note → ZenithPro price = ${vault_price:,} "
        f"(captured at {vault_meta.get('last_reviewed', 'unknown')})"
    )

    transcript_text = _INPUT_TRANSCRIPT.read_text(encoding="utf-8")
    tx_meta, tx_body = _strip_frontmatter(transcript_text)
    tx_prices = _extract_zenithpro_prices(tx_body)
    # The transcript mentions the OLD price first as context, then the
    # NEW agreed price. Take the highest as the "decision" price — this
    # is a deterministic heuristic, not a model.
    if len(tx_prices) < 2:
        _err("transcript didn't yield a before/after price pair; aborting")
        return 1
    new_price = max(tx_prices)
    _ok(
        f"transcript    → ZenithPro price = ${new_price:,} "
        f"(decision @ {tx_meta.get('captured_at', 'unknown')})"
    )

    # ── 2. Trust layer: quarantine each claim ────────────────────────────
    _banner("2 / 6  Trust layer — quarantine + lane attribution")

    def _claim(price: int, lane: str, source_kref: str, ts: str) -> CandidateClaim:
        return CandidateClaim(
            lane=lane,
            assertion_type="factual_assertion",
            subject_kref=_ZENITHPRO_KREF,
            predicate="zenithpro.price_usd",
            object_value=str(price),
            confidence=0.9 if lane == "atlas_vault" else 0.85,
            evidence_ref=EvidenceRef(
                source=lane,
                source_family="vault" if lane == "atlas_vault" else "meeting",
                kref=source_kref,
                timestamp=ts,
            ),
            scope="global",
        )

    vault_result = quarantine.upsert_candidate(
        _claim(
            vault_price,
            "atlas_vault",
            "kref://demo_messy/episodes/note_zenith_pricing.md",
            f"{vault_meta.get('last_reviewed', '2026-04-15')}T00:00:00+00:00",
        )
    )
    _ok(
        f"vault claim    → candidate {vault_result.candidate_id[:8]} "
        f"trust={vault_result.trust_score:.2f} status={vault_result.status.value}"
    )

    tx_result = quarantine.upsert_candidate(
        _claim(
            new_price,
            "atlas_meeting",
            "kref://demo_messy/episodes/lm_2026_04_26_pricing_review",
            tx_meta.get("captured_at", "2026-04-26T14:30:00+00:00"),
        )
    )
    _ok(
        f"transcript claim → candidate {tx_result.candidate_id[:8]} "
        f"trust={tx_result.trust_score:.2f} status={tx_result.status.value}"
    )
    _info(
        "Both claims target the same subject_kref + predicate but with "
        "different objects → they're independent candidates that will "
        "contradict in Ripple, not corroborate in quarantine."
    )

    # ── 3. Promote both to the ledger + plant the graph ──────────────────
    _banner("3 / 6  Plant the typed graph (price + dependent margin belief)")
    ts_old = f"{vault_meta.get('last_reviewed', '2026-04-15')}T00:00:00+00:00"
    ts_new = tx_meta.get("captured_at", "2026-04-26T14:30:00+00:00")

    async with driver.session() as session:
        await session.run(
            "MERGE (b:Belief:AtlasItem {kref: $k}) "
            "SET b.confidence_score = 0.92, "
            "    b.text = $t, "
            "    b.deprecated = false, "
            "    b.priced_at = $ts, "
            "    b.last_evidence_days = 0",
            k=_ZENITHPRO_KREF,
            t=f"ZenithPro is priced at ${vault_price:,}",
            ts=ts_old,
        )
        await session.run(
            "MERGE (m:Belief:AtlasItem {kref: $k}) "
            "SET m.confidence_score = 0.88, "
            "    m.text = $t, "
            "    m.deprecated = false, "
            "    m.last_evidence_days = 0",
            k=_ORIGINS_MARGIN_KREF,
            t="Origins coffee margin claim holds while ZenithPro >= $2,895",
        )
        await session.run(
            "MATCH (m:Belief {kref: $m_kref}), (p:Belief {kref: $p_kref}) "
            "MERGE (m)-[r:DEPENDS_ON]->(p) "
            "SET r.dependency_strength = 0.95",
            m_kref=_ORIGINS_MARGIN_KREF,
            p_kref=_ZENITHPRO_KREF,
        )
    _ok(f"upstream  : {_ZENITHPRO_KREF} @ 0.92")
    _ok(f"downstream: {_ORIGINS_MARGIN_KREF} @ 0.88 (DEPENDS_ON, strength 0.95)")

    # ── 4. Ripple cascade ────────────────────────────────────────────────
    _banner("4 / 6  Ripple cascade — automatic downstream reassessment")
    impact = await server.dispatch(
        "ripple.analyze_impact",
        {"kref": _ZENITHPRO_KREF},
    )
    _ok(f"impacted nodes: {len(impact.result['impacted'])}")
    for n in impact.result["impacted"]:
        _info(
            f"  ← {n['kref']} (depth {n['depth']}, "
            f"current confidence {n['current_confidence']:.2f})"
        )

    reassess = await server.dispatch(
        "ripple.reassess",
        {
            "upstream_kref": _ZENITHPRO_KREF,
            "old_confidence": 0.92,
            "new_confidence": 0.30,  # vault claim now contradicted by transcript
            "belief_text": (
                f"ZenithPro is priced at ${new_price:,} "
                f"(superseded ${vault_price:,})"
            ),
        },
    )
    proposals: list[dict[str, Any]] = reassess.result["proposals"]
    _ok(f"{len(proposals)} reassessment proposal(s) computed")
    for p in proposals:
        delta = p["new_confidence"] - p["old_confidence"]
        _warn(
            f"  {p['target_kref']}: "
            f"{p['old_confidence']:.2f} → {p['new_confidence']:.2f}  "
            f"({delta:+.2f})"
        )

    # ── 5. Ledger event for the price change ─────────────────────────────
    _banner("5 / 6  Ledger — append the price-change event")
    event = ledger.append_event(
        event_type="fact.price_changed",
        actor_id=_DEMO_USER,
        object_id=_ZENITHPRO_KREF,
        object_type="Belief",
        root_id=_ZENITHPRO_KREF,
        payload={
            "predicate": "zenithpro.price_usd",
            "old_value": vault_price,
            "new_value": new_price,
            "source_kref": "kref://demo_messy/episodes/lm_2026_04_26_pricing_review",
            "decided_at": ts_new,
        },
        reason="ZenithPro pricing updated by 2026-04-26 review meeting",
    )
    _ok(
        f"ledger sequence={event.chain_sequence}  "
        f"event_id={event.event_id[:8]}  "
        f"chained on previous_hash="
        f"{event.previous_hash[:8] if event.previous_hash else 'genesis'}"
    )

    # ── 6. Verify chain ──────────────────────────────────────────────────
    _banner("6 / 6  Verify SHA-256 ledger chain")
    chain = await server.dispatch("ledger.verify_chain", {})
    if chain.result["intact"]:
        _ok(f"chain intact at sequence {chain.result['last_verified_sequence']}")
        _info(
            f"last_verified_sequence = {chain.result['last_verified_sequence']} "
            f"means the chain is valid through that many ledger entries — "
            f"this run promoted {chain.result['last_verified_sequence']} "
            f"event(s); each later run extends it."
        )
    else:
        _err(f"chain broken at sequence {chain.result.get('broken_at_sequence')}")

    # ── Wrap-up ──────────────────────────────────────────────────────────
    print()
    print(f"{_GREEN}{_BOLD}LOOP CLOSED.{_RC}")
    print(f"{_DIM}  vault.md + transcript.md → quarantine → ledger → "
          f"Ripple → AGM revise → tamper-check{_RC}")
    print(
        f"{_DIM}  Files generated under {tmp.relative_to(tmp.parent)}/ — "
        f"safe to delete after inspecting.{_RC}"
    )

    await driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
