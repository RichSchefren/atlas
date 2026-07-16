"""SDK-neutral Hermes adapter core backed by Atlas's local memory tools.

The CRUD-shaped interface below was drafted against an older Hermes contract.
It remains useful as a tested adapter core, but current Hermes Agent plugins
subclass ``agent.memory_provider.MemoryProvider`` and use lifecycle hooks such
as ``prefetch`` and ``sync_turn``.  Atlas does not describe this module as a
drop-in current-Hermes plugin; the native wrapper belongs in a separately
versioned integration package.

This core now implements all four operations for real:

    async def put(item: MemoryItem) -> str            # returns item_id
    async def search(query: str, k: int) -> list[MemoryItem]
    async def get(item_id: str) -> MemoryItem | None
    async def delete(item_id: str) -> bool

Basic storage and lexical retrieval use Atlas's SQLite trust store and need no
Neo4j or Docker.  Deployments that enable Neo4j can additionally use AGM
revision, graph lineage, and Ripple reassessment through Atlas's MCP surface.

INSTALL (Hermes side):
    # hermes_config.yaml
    memory:
      provider: atlas
      config:
        neo4j_uri: bolt://localhost:7687
        neo4j_user: neo4j
        neo4j_password: atlasdev
        atlas_data_dir: ~/.atlas

CONTRACT NOTES:
1. Hermes MemoryItem fields we expect: id, content (str), metadata (dict),
   created_at (iso8601), embedding (optional list[float]).
2. Atlas owns the canonical candidate ID returned from `put`.
3. `search` is deterministic local lexical retrieval over non-denied memory.
4. `delete` removes the item from retrieval while preserving its audit row.

Spec: 09 - Agent Runtime Memory Competitive Landscape.md (Hermes section)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas_core.api.mcp_server import AtlasMCPServer


PROVIDER_NAME: str = "atlas"
"""Identifier Hermes uses in `memory.provider:` config."""


@dataclass
class HermesMemoryItem:
    """Mirrors hermes_agent.memory.MemoryItem shape.

    Kept local so the adapter core has no Hermes installation dependency.
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
    """Hermes-shaped adapter core backed by AtlasMCPServer.

    The four operations use Atlas's portable SQLite memory tools. A caller
    connected to a graph-enabled MCP server can separately invoke Atlas's AGM
    and Ripple tools; ordinary CRUD does not pretend to trigger them.
    """

    def __init__(self, *, mcp_server: AtlasMCPServer):
        self.mcp = mcp_server

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> AtlasHermesProvider:
        """Construct the functional SQLite adapter without Neo4j or Docker."""
        from pathlib import Path

        from atlas_core.api import AtlasMCPServer
        from atlas_core.trust import HashChainedLedger, QuarantineStore

        config = config or {}
        data_dir = Path(config.get("atlas_data_dir", str(Path.home() / ".atlas")))
        data_dir = data_dir.expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(mcp_server=AtlasMCPServer(
            driver=None,
            quarantine=QuarantineStore(data_dir / "candidates.db"),
            ledger=HashChainedLedger(data_dir / "ledger.db"),
        ))

    async def put(self, item: HermesMemoryItem) -> str:
        """Hermes wants to remember `item`. Atlas routes through quarantine.

        Mapping rules:
          - item.content           → object_value (verbatim)
          - item.metadata['subject_kref'] → subject_kref (REQUIRED)
          - item.metadata['predicate']    → predicate (REQUIRED)
          - item.metadata['confidence']   → confidence (default 0.6)
          - item.metadata['lane']         → lane (default 'atlas_chat_history')
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
        """Return real SQLite-ranked Atlas memories."""
        result = await self.mcp.dispatch("memory.search", {"query": query, "limit": k})
        if not result.ok:
            raise RuntimeError(f"Atlas search failed: {result.error}")
        return [self._from_memory(row) for row in result.result["memories"]]

    async def get(self, item_id: str) -> HermesMemoryItem | None:
        """Fetch one retrievable memory by Atlas candidate ID."""
        result = await self.mcp.dispatch("memory.get", {"memory_id": item_id})
        if not result.ok:
            raise RuntimeError(f"Atlas get failed: {result.error}")
        row = result.result["memory"]
        return self._from_memory(row) if row else None

    async def delete(self, item_id: str) -> bool:
        """Remove one memory from retrieval while retaining its audit row."""
        result = await self.mcp.dispatch("memory.forget", {"memory_id": item_id})
        if not result.ok:
            raise RuntimeError(f"Atlas delete failed: {result.error}")
        return bool(result.result["forgotten"])

    @staticmethod
    def _from_memory(row: dict[str, Any]) -> HermesMemoryItem:
        return HermesMemoryItem(
            item_id=row["memory_id"],
            content=row["text"],
            created_at=row.get("created_at"),
            metadata={
                "score": row["score"],
                "status": row["status"],
                "lane": row["lane"],
                "subject_kref": row["subject_kref"],
                "predicate": row["predicate"],
                "confidence": row["confidence"],
                "trust_score": row["trust_score"],
            },
        )
