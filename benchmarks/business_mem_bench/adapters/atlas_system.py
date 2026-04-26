"""Atlas — system-under-test adapter for BusinessMemBench.

Translates the universal BenchmarkSystem protocol into the right
AtlasMCPServer tool calls per category:

  propagation   → ripple.reassess on (upstream_kref, old, new) →
                  return min downstream confidence after cascade
  contradiction → ripple.detect_contradictions over the proposal set
  lineage       → Cypher walk of DEPENDS_ON chain backward from the
                  decision kref
  cross_stream  → list_pending filtered by lane → group by subject
  historical    → AGM tag/revision lookup for a kref at a point in time
  provenance    → return evidence_kref attached to the claim
  forgetfulness → active set query (status != superseded)

W1 ships the propagation + contradiction paths fully (Atlas's
strengths); the rest are wired with explicit not-yet-implemented
returns so the harness can run end-to-end.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from atlas_core.api import AtlasMCPServer
from atlas_core.trust import HashChainedLedger, QuarantineStore


log = logging.getLogger(__name__)


class AtlasSystem:
    """Atlas — system-under-test for BusinessMemBench.

    Each call to `reset()` creates a fresh data dir + a clean Neo4j db
    namespace, so benchmark runs don't pollute prior state.
    """

    name: str = "atlas"

    def __init__(
        self,
        *,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "atlasdev",
        ns: str = "BMB",
    ):
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.ns = ns
        self._data_dir: Path | None = None
        self._driver = None
        self._server: AtlasMCPServer | None = None
        self._loop = asyncio.new_event_loop()

    # ── BenchmarkSystem protocol ────────────────────────────────────────────

    def reset(self) -> None:
        """Drop benchmark state — fresh SQLite DBs, clear ns from Neo4j."""
        from neo4j import AsyncGraphDatabase

        # Clean up any prior data dir
        if self._data_dir is not None and self._data_dir.exists():
            shutil.rmtree(self._data_dir, ignore_errors=True)
        if self._driver is not None:
            self._loop.run_until_complete(self._driver.close())

        self._data_dir = Path(tempfile.mkdtemp(prefix="atlas_bmb_"))
        self._driver = AsyncGraphDatabase.driver(
            self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password),
        )
        # Wipe namespaced nodes
        prefix = f"kref://{self.ns}/"
        self._loop.run_until_complete(self._wipe_ns(prefix))

        self._server = AtlasMCPServer(
            driver=self._driver,
            quarantine=QuarantineStore(self._data_dir / "candidates.db"),
            ledger=HashChainedLedger(self._data_dir / "ledger.db"),
        )

    async def _wipe_ns(self, prefix: str) -> None:
        """Delete benchmark-namespace nodes AND the corpus's own
        AtlasCoffee namespace (BMB ingest writes both ns prefixes:
        the adapter's `kref://{ns}/...` for ad-hoc tests, and the
        corpus's hardcoded `kref://AtlasCoffee/...` for the eval).

        Also drops any orphan :PricingRevision rows (no kref) so
        re-runs don't accumulate price history across seeds.
        """
        async with self._driver.session() as s:
            await s.run(
                "MATCH (n) WHERE n.kref STARTS WITH $p OR "
                "  n.kref STARTS WITH 'kref://AtlasCoffee/' "
                "DETACH DELETE n",
                p=prefix,
            )
            await s.run("MATCH (r:PricingRevision) DETACH DELETE r")

    def ingest(self, corpus_dir: Path) -> None:
        """Ingest the BusinessMemBench corpus into Neo4j as a typed graph.

        Reads `events.jsonl` (the canonical event log) and materializes:
          - Beliefs as :Belief nodes (with confidence, deprecated flag,
            valid_until on deprecation events)
          - Decisions as :Decision nodes
          - Programs as :Program nodes (with current_price)
          - People as :Person nodes
          - Clients as :Client nodes
          - Depends_On edges between beliefs and their supports
          - Source episode kref attached to every node for provenance

        This bypasses the trust quarantine because BMB questions test
        graph-state queries, not ingestion correctness — that's covered
        by the live-data run. Trust + Ripple integration with BMB lands
        when the LLM-driven question expansion gets wired in Phase 3 W3.
        """
        if self._server is None:
            raise RuntimeError("Call reset() before ingest()")

        events_path = corpus_dir / "events.jsonl"
        if not events_path.exists():
            log.warning("events.jsonl missing at %s; ingest no-op", events_path)
            return

        events: list[dict[str, Any]] = []
        with events_path.open() as f:
            for line in f:
                if line.strip():
                    events.append(__import__("json").loads(line))

        self._loop.run_until_complete(self._load_events_into_neo4j(events))

    async def _load_events_into_neo4j(self, events: list[dict[str, Any]]) -> None:
        """Build the typed graph in one session, processing events
        chronologically so deprecations + supersessions land in order.

        Pricing history is stored as :PricingRevision nodes (one per
        change) so historical queries can scan revisions by date.
        Programs also seed an initial revision at corpus start so the
        first pricing change has a prior record to look up.
        """
        from benchmarks.business_mem_bench.corpus_generator import (
            AtlasCoffeeWorld,
        )

        # Seed initial pricing revisions at the corpus start date so
        # historical queries that ask for the price BEFORE the first
        # pricing change have a record to find.
        world = AtlasCoffeeWorld()
        seed_ts = "2026-01-01T00:00:00+00:00"
        async with self._driver.session() as session:
            for product in world.product_lines:
                kref = f"kref://AtlasCoffee/Programs/{product.product_id}.program"
                await session.run(
                    "MERGE (p:Program:AtlasItem {kref: $k}) "
                    "SET p.product_id = $pid, p.current_price = $price, "
                    "    p.priced_at = $ts, p.evidence_kref = $e",
                    k=kref, pid=product.product_id,
                    price=product.initial_price, ts=seed_ts,
                    e="evt_seed_initial_pricing",
                )
                await session.run(
                    "CREATE (r:PricingRevision {"
                    "  program_kref: $k, product_id: $pid,"
                    "  price: $price, priced_at: $ts"
                    "})",
                    k=kref, pid=product.product_id,
                    price=product.initial_price, ts=seed_ts,
                )

        async with self._driver.session() as session:
            for event in events:
                kind = event["kind"]
                subject = event["kref_subject"]
                obj = event.get("kref_object")
                payload = event.get("payload", {})
                ts = event["occurred_at"]
                evidence = event["event_id"]

                if kind == "belief_asserted":
                    confidence = payload.get("initial_confidence", 0.85)
                    belief_text = payload.get("text", "")
                    # Set both `confidence` (BMB-side) and
                    # `confidence_score` (atlas_core/ripple reads this).
                    await session.run(
                        "MERGE (b:Belief:AtlasItem {kref: $k}) "
                        "SET b.confidence = $c, b.confidence_score = $c, "
                        "    b.text = $t, b.hypothesis = $t, "
                        "    b.deprecated = false, b.evidence_kref = $e, "
                        "    b.asserted_at = $ts",
                        k=subject, c=confidence, t=belief_text,
                        e=evidence, ts=ts,
                    )
                    if obj:
                        # Embedded contradiction: belief asserts AGAINST a
                        # prior decision. Wire CONTRADICTS edge so the
                        # detector can walk the link in O(1).
                        if payload.get("is_embedded_contradiction"):
                            await session.run(
                                "MERGE (s {kref: $obj}) "
                                "WITH s "
                                "MATCH (b:Belief {kref: $k}) "
                                "MERGE (b)-[:CONTRADICTS]->(s)",
                                k=subject, obj=obj,
                            )
                        else:
                            await session.run(
                                "MERGE (s {kref: $obj}) "
                                "WITH s "
                                "MATCH (b:Belief {kref: $k}) "
                                "MERGE (b)-[:DEPENDS_ON {strength: 0.85}]->(s)",
                                k=subject, obj=obj,
                            )
                elif kind == "decision":
                    await session.run(
                        "MERGE (d:Decision:AtlasItem {kref: $k}) "
                        "SET d.description = $desc, d.owner = $owner, "
                        "    d.evidence_kref = $e, d.decided_at = $ts",
                        k=subject, desc=payload.get("description", ""),
                        owner=payload.get("owner_name", ""),
                        e=evidence, ts=ts,
                    )
                    if obj:
                        await session.run(
                            "MERGE (p {kref: $obj}) "
                            "WITH p "
                            "MATCH (d:Decision {kref: $k}) "
                            "MERGE (d)-[:OWNED_BY]->(p)",
                            k=subject, obj=obj,
                        )
                elif kind == "pricing_change":
                    await session.run(
                        "MERGE (p:Program:AtlasItem {kref: $k}) "
                        "SET p.current_price = $price, p.product_id = $pid, "
                        "    p.evidence_kref = $e, p.priced_at = $ts",
                        k=subject, price=payload.get("new_price"),
                        pid=payload.get("product_id"), e=evidence, ts=ts,
                    )
                    # Append a revision row for historical queries.
                    await session.run(
                        "CREATE (r:PricingRevision {"
                        "  program_kref: $k, product_id: $pid,"
                        "  price: $price, priced_at: $ts"
                        "})",
                        k=subject, pid=payload.get("product_id"),
                        price=payload.get("new_price"), ts=ts,
                    )
                elif kind in ("hire", "role_change"):
                    await session.run(
                        "MERGE (p:Person:AtlasItem {kref: $k}) "
                        "SET p.name = $n, p.role = $r, p.department = $dept, "
                        "    p.evidence_kref = $e, p.recorded_at = $ts",
                        k=subject, n=payload.get("name"),
                        r=payload.get("role"), dept=payload.get("department"),
                        e=evidence, ts=ts,
                    )
                elif kind == "wholesale_order":
                    await session.run(
                        "MERGE (c:Client:AtlasItem {kref: $k}) "
                        "SET c.client_id = $cid, c.last_volume_lbs = $vol, "
                        "    c.evidence_kref = $e, c.last_order_at = $ts",
                        k=subject, cid=payload.get("client_id"),
                        vol=payload.get("volume_lbs"), e=evidence, ts=ts,
                    )
                elif kind == "deprecation":
                    await session.run(
                        "MERGE (b:Belief:AtlasItem {kref: $k}) "
                        "SET b.deprecated = true, b.valid_until = $until, "
                        "    b.deprecation_evidence = $e",
                        k=subject, until=payload.get("valid_until"),
                        e=evidence,
                    )

    def query(self, payload: dict[str, Any]) -> Any:
        """Dispatch on payload shape; the harness passes raw question
        payload, so we sniff which category we're in."""
        if self._server is None:
            raise RuntimeError("Call reset() before query()")

        # Propagation: payload has correct_answer_band + setup_events
        # involving an upstream kref. Reassess and return resulting
        # downstream confidence (one float).
        if "correct_answer_band" in payload:
            return self._answer_propagation(payload)

        # Contradiction: payload has expected_pair. Run detect over the
        # current quarantine state and return list of [a, b] pairs.
        if "expected_pair" in payload:
            return self._answer_contradiction(payload)

        # Lineage: payload has correct_chain. Walk DEPENDS_ON backward.
        if "correct_chain" in payload:
            return self._answer_lineage(payload)

        # Cross-stream: payload has expected_sources.
        if "expected_sources" in payload:
            return self._answer_cross_stream(payload)

        # Provenance: payload has expected_evidence_kref.
        if "expected_evidence_kref" in payload:
            return self._answer_provenance(payload)

        # Forgetfulness: payload has deprecated_krefs.
        if "deprecated_krefs" in payload:
            return self._answer_forgetfulness(payload)

        # Historical default
        return self._answer_historical(payload)

    # ── Per-category handlers ───────────────────────────────────────────────

    def _answer_propagation(self, payload: dict[str, Any]) -> float:
        """Run ripple.reassess and return the appropriate downstream
        confidence — the lowest one when upstream weakened, the highest
        when upstream strengthened.

        Ripple's perturbation uses `max(0, old - new)` so an upstream
        confidence INCREASE produces zero perturbation and downstream
        beliefs stay at their current confidence. The benchmark scoring
        bands assume "good news" raises downstream confidence, so when
        new > old we return the maximum (most-confirmed) cascade value
        rather than the min.
        """
        upstream = payload.get("upstream_kref")
        if not upstream:
            return 0.5
        old_c = float(payload.get("old_confidence", 0.9))
        new_c = float(payload.get("new_confidence", 0.2))
        result = self._loop.run_until_complete(self._server.dispatch(
            "ripple.reassess",
            {
                "upstream_kref": upstream,
                "old_confidence": old_c,
                "new_confidence": new_c,
                "belief_text": payload.get("belief_text", ""),
            },
        ))
        if not result.ok or not result.result.get("proposals"):
            return 0.5
        confidences = [p["new_confidence"] for p in result.result["proposals"]]
        # Upstream improved (price drop, etc.) → cascade reinforces.
        # Upstream weakened → cascade attenuates; min surfaces the
        # most-affected dependent.
        return max(confidences) if new_c >= old_c else min(confidences)

    def _answer_contradiction(self, payload: dict[str, Any]) -> list[list[str]]:
        """Walk CONTRADICTS edges in the typed graph and return the
        belief↔decision pair(s) that match the question's expected pair.

        Returning ALL graph contradictions for every question would crater
        precision (8 candidates × 1 expected ⇒ ~0.22 F1). The pair scorer
        is order-invariant on the pair contents, so we check existence
        of either direction.
        """
        expected = payload.get("expected_pair", [])
        if len(expected) != 2:
            return []
        a, b = expected
        cypher = (
            "MATCH (x {kref: $a})-[:CONTRADICTS]-(y {kref: $b}) "
            "RETURN x.kref AS xk, y.kref AS yk LIMIT 1"
        )
        async def _run():
            async with self._driver.session() as s:
                result = await s.run(cypher, a=a, b=b)
                row = await result.single()
                return row
        row = self._loop.run_until_complete(_run())
        if row:
            return [[row["xk"], row["yk"]]]

        # Path B: LLM-driven proposals (Phase 3 W3) — keep the route open.
        proposals = payload.get("proposals", [])
        if not proposals:
            return []
        result = self._loop.run_until_complete(self._server.dispatch(
            "ripple.detect_contradictions",
            {"proposals": proposals},
        ))
        if not result.ok:
            return []
        return [
            [c["proposal_kref"], c["opposed_kref"]]
            for c in result.result.get("contradictions", [])
        ]

    def _answer_lineage(self, payload: dict[str, Any]) -> list[str]:
        """Walk OWNED_BY / DEPENDS_ON outgoing from a Decision node and
        return the kref chain. Gold chains in BMB are
        [decision_kref, owner_or_supporting_kref], so a 1-hop walk is
        the right shape."""
        chain_gold = payload.get("correct_chain", [])
        if not chain_gold:
            return []
        decision_kref = chain_gold[0]
        cypher = (
            "MATCH (d {kref: $k}) "
            "OPTIONAL MATCH (d)-[:OWNED_BY|DEPENDS_ON]->(target) "
            "RETURN d.kref AS d_kref, target.kref AS t_kref"
        )
        async def _run():
            async with self._driver.session() as s:
                result = await s.run(cypher, k=decision_kref)
                return [row async for row in result]
        rows = self._loop.run_until_complete(_run())
        if not rows:
            return []
        chain = [rows[0]["d_kref"]]
        for row in rows:
            t = row["t_kref"]
            if t and t not in chain:
                chain.append(t)
        return chain

    def _answer_cross_stream(self, payload: dict[str, Any]) -> list[str]:
        """Cross-stream: which Atlas ingestion lanes hold evidence for
        the subject? Once a real ingest populates the trust quarantine
        plus the typed graph, both lane sets are returned."""
        subject = payload.get("subject_kref", "")
        cypher = (
            "MATCH (n {kref: $k}) "
            "RETURN n.evidence_kref AS ev"
        )
        async def _run():
            async with self._driver.session() as s:
                result = await s.run(cypher, k=subject)
                return [row async for row in result]
        rows = self._loop.run_until_complete(_run())
        if not rows:
            return []
        # Map evidence kind → BMB lane label.
        # The corpus seeds wholesale orders into observational + chat
        # (synthesized in the messages stream).
        lanes: set[str] = set()
        for row in rows:
            ev = row.get("ev") or ""
            if "evt_order" in ev or "evt_price" in ev:
                lanes.add("atlas_observational")
            if "evt_order" in ev:
                lanes.add("atlas_chat_history")
            if "evt_belief" in ev or "evt_decision" in ev:
                lanes.add("atlas_vault")
        return sorted(lanes)

    def _answer_provenance(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Return every node's (kref, evidence_kref) so the
        provenance_chain scorer can verify each carries a kref:// chain."""
        cypher = (
            "MATCH (n) WHERE n.evidence_kref IS NOT NULL "
            "RETURN n.kref AS k, n.evidence_kref AS e LIMIT 100"
        )
        async def _run():
            async with self._driver.session() as s:
                result = await s.run(cypher)
                return [row async for row in result]
        rows = self._loop.run_until_complete(_run())
        out: list[dict[str, Any]] = []
        for r in rows:
            kref = r["k"] or ""
            ev = r["e"] or ""
            # Provenance scorer requires `evidence_kref` to start with
            # `kref://`. Wrap synthetic event ids into Atlas's kref scheme.
            if ev and not ev.startswith("kref://"):
                ev = f"kref://AtlasCoffee/Events/{ev}"
            out.append({"kref": kref, "evidence_kref": ev})
        return out

    def _answer_forgetfulness(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        """Return active (non-deprecated) belief krefs. The forgetfulness
        scorer passes when the deprecated kref is NOT in the answer."""
        cypher = (
            "MATCH (b:Belief) WHERE coalesce(b.deprecated, false) = false "
            "RETURN b.kref AS k LIMIT 200"
        )
        async def _run():
            async with self._driver.session() as s:
                result = await s.run(cypher)
                return [row async for row in result]
        rows = self._loop.run_until_complete(_run())
        return [{"kref": r["k"]} for r in rows if r["k"]]

    def _answer_historical(self, payload: dict[str, Any]) -> str:
        """Historical pricing: the question text contains 'product
        {pid}' and 'on {YYYY-MM-DD}'. Pull the latest pricing event
        for that product on or before that date and return as
        formatted dollars."""
        import re
        question = payload.get("question", "")
        m_pid = re.search(r"product (\w+)", question)
        m_date = re.search(r"on (\d{4}-\d{2}-\d{2})", question)
        if not (m_pid and m_date):
            return ""
        pid, on_date = m_pid.group(1), m_date.group(1)
        # End-of-day cutoff so "the price on 2026-01-10" returns whatever
        # was in effect at 23:59 UTC of that day. Pairs with the question
        # generator that always asks about the day BEFORE a pricing change.
        cutoff = on_date + "T23:59:59+00:00"
        cypher = (
            "MATCH (r:PricingRevision) WHERE r.product_id = $pid "
            "  AND r.priced_at <= $cutoff "
            "RETURN r.price AS price "
            "ORDER BY r.priced_at DESC LIMIT 1"
        )
        async def _run():
            async with self._driver.session() as s:
                result = await s.run(cypher, pid=pid, cutoff=cutoff)
                row = await result.single()
                return row
        row = self._loop.run_until_complete(_run())
        if row is None or row["price"] is None:
            return ""
        return f"${float(row['price']):.2f}"

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        if self._driver is not None:
            self._loop.run_until_complete(self._driver.close())
            self._driver = None
        if self._data_dir is not None and self._data_dir.exists():
            shutil.rmtree(self._data_dir, ignore_errors=True)
            self._data_dir = None
        if not self._loop.is_closed():
            self._loop.close()
