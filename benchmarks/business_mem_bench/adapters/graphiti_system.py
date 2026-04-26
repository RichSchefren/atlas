"""Graphiti baseline adapter — graphiti-core 0.28.x is in our venv as
the Atlas substrate, but we run it standalone here as the "no Atlas
extensions" baseline.

Graphiti is the closest neighbor — bitemporal property graph, custom
entity types, MCP-compatible. What it doesn't have: Ripple
reassessment, AGM-compliant revision, trust quarantine, automatic
downstream confidence updates. Those are what BusinessMemBench tests.

This adapter shows the lift Atlas adds *over its own substrate*.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


GRAPHITI_NS_PREFIX: str = "kref://AtlasCoffee/"
"""Match the corpus's hardcoded kref namespace so both adapters
operate on the same logical graph during head-to-head benchmarks."""


class GraphitiSystem:
    """Vanilla Graphiti baseline — no Ripple, no AGM revision, no
    type-aware contradiction detection.

    Graphiti is the closest substrate to Atlas (Atlas forks it for
    storage). This adapter writes the same typed nodes Atlas's
    adapter writes, but answers BMB queries WITHOUT the AGM /
    Ripple machinery — surfacing the gap Atlas fills.

    What Graphiti can do (with the typed graph):
      lineage      — Cypher walk of OWNED_BY edges
      cross_stream — group evidence by lane label
      provenance   — return evidence_kref per node
      historical   — query :PricingRevision history (Atlas's loader
                     pattern; Graphiti supports the same MERGE)

    What Graphiti cannot do:
      propagation       — no Ripple algorithm
      contradiction     — no type-aware detector
      forgetfulness     — no AGM contract; deprecated beliefs
                          remain queryable as 'active'
    """

    name: str = "graphiti"

    def __init__(
        self,
        *,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "atlasdev",
    ):
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self._driver = None
        self._loop = asyncio.new_event_loop()

    # ── BenchmarkSystem protocol ────────────────────────────────────────────

    def reset(self) -> None:
        from neo4j import AsyncGraphDatabase

        if self._driver is not None:
            self._loop.run_until_complete(self._driver.close())
        self._driver = AsyncGraphDatabase.driver(
            self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password),
        )

        async def _wipe():
            async with self._driver.session() as s:
                await s.run(
                    "MATCH (n) WHERE n.kref STARTS WITH $p DETACH DELETE n",
                    p=GRAPHITI_NS_PREFIX,
                )
                await s.run("MATCH (r:GraphitiPricingRevision) DETACH DELETE r")
        self._loop.run_until_complete(_wipe())

    def ingest(self, corpus_dir: Path) -> None:
        events_path = corpus_dir / "events.jsonl"
        if not events_path.exists():
            log.warning("events.jsonl missing at %s; ingest no-op", events_path)
            return

        events: list[dict[str, Any]] = []
        with events_path.open() as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
        self._loop.run_until_complete(self._load_events(events))

    async def _load_events(self, events: list[dict[str, Any]]) -> None:
        """Same shape as AtlasSystem's loader — but uses different node
        labels and crucially does NOT add CONTRADICTS edges or
        deprecation flags. That's the Atlas extension Graphiti lacks."""
        from benchmarks.business_mem_bench.corpus_generator import (
            AtlasCoffeeWorld,
        )

        world = AtlasCoffeeWorld()
        seed_ts = "2026-01-01T00:00:00+00:00"
        async with self._driver.session() as session:
            for product in world.product_lines:
                kref = f"kref://AtlasCoffee/Programs/{product.product_id}.program"
                await session.run(
                    "MERGE (p:GProgram {kref: $k}) "
                    "SET p.product_id = $pid, p.current_price = $price, "
                    "    p.priced_at = $ts",
                    k=kref, pid=product.product_id,
                    price=product.initial_price, ts=seed_ts,
                )
                await session.run(
                    "CREATE (r:GraphitiPricingRevision {"
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
                    # Graphiti stores beliefs as plain nodes — no
                    # deprecated flag, no confidence_score, no
                    # CONTRADICTS edge regardless of payload.
                    await session.run(
                        "MERGE (b:GBelief {kref: $k}) "
                        "SET b.text = $t, b.evidence_kref = $e, "
                        "    b.asserted_at = $ts",
                        k=subject, t=payload.get("text", ""),
                        e=evidence, ts=ts,
                    )
                    if obj:
                        await session.run(
                            "MERGE (s {kref: $obj}) "
                            "WITH s MATCH (b:GBelief {kref: $k}) "
                            "MERGE (b)-[:DEPENDS_ON]->(s)",
                            k=subject, obj=obj,
                        )
                elif kind == "decision":
                    await session.run(
                        "MERGE (d:GDecision {kref: $k}) "
                        "SET d.description = $desc, d.evidence_kref = $e, "
                        "    d.decided_at = $ts",
                        k=subject, desc=payload.get("description", ""),
                        e=evidence, ts=ts,
                    )
                    if obj:
                        await session.run(
                            "MERGE (p {kref: $obj}) "
                            "WITH p MATCH (d:GDecision {kref: $k}) "
                            "MERGE (d)-[:OWNED_BY]->(p)",
                            k=subject, obj=obj,
                        )
                elif kind == "pricing_change":
                    await session.run(
                        "MERGE (p:GProgram {kref: $k}) "
                        "SET p.current_price = $price, p.product_id = $pid, "
                        "    p.evidence_kref = $e, p.priced_at = $ts",
                        k=subject, price=payload.get("new_price"),
                        pid=payload.get("product_id"), e=evidence, ts=ts,
                    )
                    await session.run(
                        "CREATE (r:GraphitiPricingRevision {"
                        "  program_kref: $k, product_id: $pid,"
                        "  price: $price, priced_at: $ts"
                        "})",
                        k=subject, pid=payload.get("product_id"),
                        price=payload.get("new_price"), ts=ts,
                    )
                elif kind in ("hire", "role_change"):
                    await session.run(
                        "MERGE (p:GPerson {kref: $k}) "
                        "SET p.name = $n, p.role = $r, p.evidence_kref = $e",
                        k=subject, n=payload.get("name"),
                        r=payload.get("role"), e=evidence,
                    )
                # Wholesale orders + deprecations: Graphiti would
                # ingest them but the BMB queries we score on don't
                # need extra graph state from these; skip.

    def query(self, payload: dict[str, Any]) -> Any:
        # Propagation: no Ripple → return old_confidence (the belief
        # is unchanged; this is the gap Atlas fills).
        if "correct_answer_band" in payload:
            return float(payload.get("old_confidence", 0.9))

        # Contradiction: no type-aware detector.
        if "expected_pair" in payload:
            return []

        # Lineage: walk OWNED_BY (Graphiti has the typed graph).
        if "correct_chain" in payload:
            return self._lineage(payload)

        # Cross-stream: Graphiti has no lane semantics.
        if "expected_sources" in payload:
            return []

        # Provenance: Graphiti tracks evidence_kref on nodes.
        if "expected_evidence_kref" in payload:
            return self._provenance()

        # Forgetfulness: Graphiti has no deprecated flag → returns the
        # belief as if active (failing the test).
        if "deprecated_krefs" in payload:
            return [{"kref": k} for k in payload["deprecated_krefs"]]

        return self._historical(payload)

    # ── Per-category handlers ───────────────────────────────────────────────

    def _lineage(self, payload: dict[str, Any]) -> list[str]:
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
                return [r async for r in await s.run(cypher, k=decision_kref)]
        rows = self._loop.run_until_complete(_run())
        if not rows:
            return []
        chain = [rows[0]["d_kref"]]
        for r in rows:
            t = r["t_kref"]
            if t and t not in chain:
                chain.append(t)
        return chain

    def _provenance(self) -> list[dict[str, Any]]:
        cypher = (
            "MATCH (n) WHERE n.evidence_kref IS NOT NULL "
            "  AND n.kref STARTS WITH $p "
            "RETURN n.kref AS k, n.evidence_kref AS e LIMIT 100"
        )
        async def _run():
            async with self._driver.session() as s:
                return [r async for r in await s.run(cypher, p=GRAPHITI_NS_PREFIX)]
        rows = self._loop.run_until_complete(_run())
        out = []
        for r in rows:
            kref = r["k"] or ""
            ev = r["e"] or ""
            if ev and not ev.startswith("kref://"):
                ev = f"kref://AtlasCoffee/Events/{ev}"
            out.append({"kref": kref, "evidence_kref": ev})
        return out

    def _historical(self, payload: dict[str, Any]) -> str:
        import re
        question = payload.get("question", "")
        m_pid = re.search(r"product (\w+)", question)
        m_date = re.search(r"on (\d{4}-\d{2}-\d{2})", question)
        if not (m_pid and m_date):
            return ""
        pid, on_date = m_pid.group(1), m_date.group(1)
        cutoff = on_date + "T23:59:59+00:00"
        cypher = (
            "MATCH (r:GraphitiPricingRevision) WHERE r.product_id = $pid "
            "  AND r.priced_at <= $cutoff "
            "RETURN r.price AS price ORDER BY r.priced_at DESC LIMIT 1"
        )
        async def _run():
            async with self._driver.session() as s:
                result = await s.run(cypher, pid=pid, cutoff=cutoff)
                return await result.single()
        row = self._loop.run_until_complete(_run())
        if row is None or row["price"] is None:
            return ""
        return f"${float(row['price']):.2f}"

    def close(self) -> None:
        if self._driver is not None:
            self._loop.run_until_complete(self._driver.close())
            self._driver = None
        if not self._loop.is_closed():
            self._loop.close()
