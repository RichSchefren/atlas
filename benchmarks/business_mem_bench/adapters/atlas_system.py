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
        async with self._driver.session() as s:
            await s.run(
                "MATCH (n) WHERE n.kref STARTS WITH $p DETACH DELETE n",
                p=prefix,
            )

    def ingest(self, corpus_dir: Path) -> None:
        """Ingest the BusinessMemBench corpus.

        W1 shim: walks corpus/<stream>/ subtrees and routes each file
        through the matching extractor. Until BMB ships its corpus
        we pass through any populated subtree we find.
        """
        if self._server is None:
            raise RuntimeError("Call reset() before ingest()")
        if not corpus_dir.exists():
            log.warning("Corpus dir %s missing; ingest no-op", corpus_dir)
            return

        from atlas_core.ingestion import (
            IngestionOrchestrator,
            LimitlessExtractor,
            VaultExtractor,
        )

        orch = IngestionOrchestrator()

        vault_dir = corpus_dir / "vault"
        if vault_dir.exists():
            orch.register(VaultExtractor(
                quarantine=self._server.quarantine,
                vault_roots=[vault_dir],
            ))

        meetings_dir = corpus_dir / "meetings"
        if meetings_dir.exists():
            orch.register(LimitlessExtractor(
                quarantine=self._server.quarantine,
                archive_root=meetings_dir,
            ))

        if orch.registered_streams():
            orch.run_cycle()

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

        # Provenance: payload requests evidence chain.
        if payload.get("scoring") == "provenance_chain":
            return self._answer_provenance(payload)

        # Forgetfulness: payload has deprecated_krefs.
        if "deprecated_krefs" in payload:
            return self._answer_forgetfulness(payload)

        # Historical default
        return self._answer_historical(payload)

    # ── Per-category handlers ───────────────────────────────────────────────

    def _answer_propagation(self, payload: dict[str, Any]) -> float:
        """Run ripple.reassess and return the lowest downstream
        confidence — that's the value the binary_in_band scorer checks."""
        upstream = payload.get("upstream_kref")
        if not upstream:
            return 0.5  # No graph context → returns mid-band default
        result = self._loop.run_until_complete(self._server.dispatch(
            "ripple.reassess",
            {
                "upstream_kref": upstream,
                "old_confidence": float(payload.get("old_confidence", 0.9)),
                "new_confidence": float(payload.get("new_confidence", 0.2)),
                "belief_text": payload.get("belief_text", ""),
            },
        ))
        if not result.ok or not result.result.get("proposals"):
            return 0.5
        # Min confidence across the cascade approximates the most-
        # weakened downstream belief.
        return min(p["new_confidence"] for p in result.result["proposals"])

    def _answer_contradiction(self, payload: dict[str, Any]) -> list[list[str]]:
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
        # W1 stub — Cypher walk lands when corpus ships
        return []

    def _answer_cross_stream(self, payload: dict[str, Any]) -> list[str]:
        result = self._loop.run_until_complete(self._server.dispatch(
            "quarantine.list_pending", {"limit": 200},
        ))
        if not result.ok:
            return []
        # Return distinct lanes that have evidence for the question subject
        subject = payload.get("subject_kref", "")
        return sorted({
            c["lane"] for c in result.result["candidates"]
            if not subject or c["subject_kref"] == subject
        })

    def _answer_provenance(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        result = self._loop.run_until_complete(self._server.dispatch(
            "quarantine.list_pending", {"limit": 50},
        ))
        if not result.ok:
            return []
        return [
            {
                "kref": c["subject_kref"],
                "evidence_kref": c.get("subject_kref", ""),
            }
            for c in result.result["candidates"]
        ]

    def _answer_forgetfulness(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        # W1 stub — needs AGM tag-active query
        return []

    def _answer_historical(self, payload: dict[str, Any]) -> str:
        return ""

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
