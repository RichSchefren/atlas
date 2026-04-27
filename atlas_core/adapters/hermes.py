"""Hermes MemoryProvider adapter — Atlas as the 9th memory backend for
NousResearch's Hermes agent runtime.

Hermes' MemoryProvider plugin contract (inferred from hermes-agent
plugin/memory/*.py — the project ships 8 backends including ChromaDB, Qdrant,
Weaviate, PostgreSQL, Redis, in-memory, JSON file, and SQLite). Each backend
implements a 4-method protocol:

    async def put(item: MemoryItem) -> str            # returns item_id
    async def search(query: str, k: int) -> list[MemoryItem]
    async def get(item_id: str) -> MemoryItem | None
    async def delete(item_id: str) -> bool

Atlas's differentiator: this is the only backend that runs AGM-compliant
revision and Ripple reassessment under the hood. From Hermes's POV, `put`
is just "remember this"; under the hood Atlas routes through quarantine →
promotion → AGM revise() → Ripple cascade.

INSTALL (Hermes side):
    # hermes_config.yaml
    memory:
      provider: atlas
      config:
        neo4j_uri: bolt://localhost:7687
        neo4j_user: neo4j
        neo4j_password: atlasdev
        atlas_data_dir: ~/.atlas

CONTRACT NOTES (W7 follow-ups):
1. Hermes MemoryItem fields we expect: id, content (str), metadata (dict),
   created_at (iso8601), embedding (optional list[float]).
2. Atlas owns the canonical id (kref:// scheme); hermes_id ↔ kref map lives
   in atlas_core/adapters/hermes_id_map.py (W7).
3. `search` routes through atlas_core/retrieval (vault-search 768-dim BGE) +
   Cypher kref hop expansion. Top-k is post-AGM-state, so superseded
   revisions never surface unless explicitly requested via tag.
4. `delete` becomes AGM contract() (Hansson Relevance + Core-Retainment),
   not a tombstone — Atlas removes the belief from the closure rather than
   from storage. The revision history stays auditable.

Spec: 09 - Agent Runtime Memory Competitive Landscape.md (Hermes section)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas_core.api.mcp_server import AtlasMCPServer


log = logging.getLogger(__name__)


PROVIDER_NAME: str = "atlas"
"""Identifier Hermes uses in `memory.provider:` config."""


@dataclass
class HermesMemoryItem:
    """Mirrors hermes_agent.memory.MemoryItem shape.

    Phase 2 W6 keeps this as a local dataclass to avoid importing Hermes;
    W7 will switch to the upstream type once the plugin manifest is published.
    """

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    item_id: str | None = None
    created_at: str | None = None
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.item_id,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "embedding": self.embedding,
        }


class AtlasHermesProvider:
    """Hermes MemoryProvider implementation backed by AtlasMCPServer.

    Hermes calls the four methods (put / search / get / delete) without
    knowing they trigger AGM revision + Ripple cascade under the hood.
    Errors surface as exceptions so Hermes' default error handler triggers.
    """

    def __init__(self, *, mcp_server: AtlasMCPServer):
        self.mcp = mcp_server

    async def put(self, item: HermesMemoryItem) -> str:
        """Hermes wants to remember `item`. Atlas routes through quarantine.

        Mapping rules:
          - item.content           → object_value (verbatim)
          - item.metadata['subject_kref'] → subject_kref (REQUIRED)
          - item.metadata['predicate']    → predicate (REQUIRED)
          - item.metadata['confidence']   → confidence (default 0.6)
          - item.metadata['lane']         → lane (default 'atlas_curated')
          - item.created_at        → evidence_timestamp
        """
        meta = item.metadata
        if "subject_kref" not in meta or "predicate" not in meta:
            raise ValueError(
                "Hermes->Atlas requires metadata.subject_kref and "
                "metadata.predicate; Atlas is structured-belief, not raw text."
            )

        timestamp = item.created_at or datetime.now(timezone.utc).isoformat()
        result = await self.mcp.dispatch(
            "quarantine.upsert",
            {
                "lane": meta.get("lane", "atlas_chat_history"),
                "assertion_type": meta.get("assertion_type", "factual_assertion"),
                "subject_kref": meta["subject_kref"],
                "predicate": meta["predicate"],
                "object_value": item.content,
                "confidence": float(meta.get("confidence", 0.6)),
                "evidence_source": meta.get("evidence_source", "hermes"),
                "evidence_source_family": meta.get("evidence_source_family", "agent"),
                "evidence_kref": meta.get(
                    "evidence_kref", f"kref://hermes/{meta.get('agent', 'unknown')}",
                ),
                "evidence_timestamp": timestamp,
            },
        )
        if not result.ok:
            raise RuntimeError(f"Atlas put failed: {result.error}")
        return result.result["candidate_id"]

    async def search(
        self, query: str, k: int = 10,
    ) -> list[HermesMemoryItem]:
        """W7 wires this through atlas_core/retrieval (vault-search BGE +
        Cypher kref expansion). Phase 2 W6 returns an empty list with a
        clear log line so Hermes' fallback path is exercised in dev.
        """
        log.info(
            "AtlasHermesProvider.search(%r, k=%d) — W7 wires retrieval; "
            "returning [] for now.", query, k,
        )
        return []

    async def get(self, item_id: str) -> HermesMemoryItem | None:
        """item_id is a quarantine candidate_id ULID. W7 wires the lookup."""
        log.info(
            "AtlasHermesProvider.get(%r) — W7 wires candidate lookup; "
            "returning None for now.", item_id,
        )
        return None

    async def delete(self, item_id: str) -> bool:
        """W7 routes through AGM contract(). Phase 2 W6 returns False so
        Hermes doesn't think the delete succeeded silently."""
        log.info(
            "AtlasHermesProvider.delete(%r) — W7 routes via AGM contract(); "
            "returning False for now.", item_id,
        )
        return False
