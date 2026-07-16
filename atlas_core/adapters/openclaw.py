"""SDK-neutral OpenClaw adapter core backed by Atlas local memory tools.

The Python protocol below was drafted against an earlier inferred OpenClaw
contract. Current OpenClaw memory plugins are TypeScript packages built on the
official plugin SDK and ``registerMemoryCapability``. This module is therefore
a tested integration core, not a claim of current native plugin packaging.

The adapter operations are real and need no Neo4j or Docker:
    plugin.json:
      {
        "name": "atlas-memory",
        "version": "0.1.0",
        "type": "memory",
        "entrypoint": "atlas_core.adapters.openclaw:plugin"
      }

    Plugin object protocol:
      def init(config: dict) -> Plugin
      async def store(text: str, metadata: dict) -> str   # → memory_id
      async def recall(query: str, k: int = 5) -> list[Recall]
      async def forget(memory_id: str) -> bool
      async def list_memories(filter: dict | None) -> list[Recall]

    Recall = dataclass(memory_id, text, score, metadata, timestamp)

OpenClaw is more conversational than Hermes, so Atlas deterministically maps
raw text to an agent/session subject and a configurable predicate. Storage,
retrieval, listing, and forgetting run against the local SQLite trust store.
Neo4j remains optional for Atlas's graph revision and Ripple features.

Spec: 09 - Agent Runtime Memory Competitive Landscape.md (OpenClaw section)
      Plugin manifest: contract sketched here, validated against upstream W7.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas_core.api.mcp_server import AtlasMCPServer


PLUGIN_NAME: str = "atlas-memory"
PLUGIN_VERSION: str = "0.1.0"
PLUGIN_TYPE: str = "memory"


@dataclass
class Recall:
    """OpenClaw's recall result shape."""

    memory_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str | None = None


class AtlasOpenClawPlugin:
    """OpenClaw-shaped adapter core backed by AtlasMCPServer.

    It accepts raw text and deterministically derives subject + predicate from
    session metadata. Native current-OpenClaw packaging lives outside this
    Python protocol.
    """

    def __init__(self, *, mcp_server: AtlasMCPServer):
        self.mcp = mcp_server

    async def store(self, text: str, metadata: dict[str, Any]) -> str:
        """Atlas-side: route to quarantine.upsert with deterministic mapping.

        Required metadata keys: agent_id (string), session_id (string).
        Optional: confidence, lane, predicate.
        """
        agent_id = metadata.get("agent_id", "unknown")
        session_id = metadata.get("session_id", "unknown")
        timestamp = metadata.get(
            "timestamp", datetime.now(timezone.utc).isoformat(),
        )

        result = await self.mcp.dispatch(
            "quarantine.upsert",
            {
                "lane": metadata.get("lane", "atlas_chat_history"),
                "assertion_type": metadata.get(
                    "assertion_type", "factual_assertion",
                ),
                "subject_kref": metadata.get(
                    "subject_kref",
                    f"kref://openclaw/Agents/{agent_id}.agent",
                ),
                "predicate": metadata.get("predicate", "said"),
                "object_value": text,
                "confidence": float(metadata.get("confidence", 0.5)),
                "evidence_source": f"openclaw:{session_id}",
                "evidence_source_family": "agent",
                "evidence_kref": (
                    f"kref://openclaw/Sessions/{session_id}.session"
                ),
                "evidence_timestamp": timestamp,
            },
        )
        if not result.ok:
            raise RuntimeError(f"Atlas store failed: {result.error}")
        return result.result["candidate_id"]

    async def recall(self, query: str, k: int = 5) -> list[Recall]:
        """Return real SQLite-ranked Atlas memories."""
        result = await self.mcp.dispatch("memory.search", {"query": query, "limit": k})
        if not result.ok:
            raise RuntimeError(f"Atlas recall failed: {result.error}")
        return [self._from_memory(row) for row in result.result["memories"]]

    async def forget(self, memory_id: str) -> bool:
        """Remove one memory from retrieval while retaining its audit row."""
        result = await self.mcp.dispatch("memory.forget", {"memory_id": memory_id})
        if not result.ok:
            raise RuntimeError(f"Atlas forget failed: {result.error}")
        return bool(result.result["forgotten"])

    async def list_memories(
        self, filter: dict[str, Any] | None = None,
    ) -> list[Recall]:
        """List retrievable memories, optionally filtered by agent ID."""
        result = await self.mcp.dispatch("memory.list", {
            "limit": (filter or {}).get("limit", 50),
            **({"lane": filter["lane"]} if filter and filter.get("lane") else {}),
        })
        if not result.ok:
            raise RuntimeError(f"Atlas list failed: {result.error}")
        agent_id = (filter or {}).get("agent_id")
        rows = result.result["memories"]
        if agent_id:
            rows = [
                r for r in rows
                if f"openclaw/Agents/{agent_id}" in r["subject_kref"]
            ]
        return [self._from_memory(row) for row in rows]

    @staticmethod
    def _from_memory(row: dict[str, Any]) -> Recall:
        return Recall(
            memory_id=row["memory_id"],
            text=row["text"],
            score=float(row["score"]),
            metadata={
                "status": row["status"],
                "lane": row["lane"],
                "subject_kref": row["subject_kref"],
                "predicate": row["predicate"],
                "confidence": row["confidence"],
                "trust_score": row["trust_score"],
            },
            timestamp=row.get("created_at"),
        )


def plugin(config: dict[str, Any]) -> AtlasOpenClawPlugin:
    """Construct the functional SQLite adapter core.

    config keys:
      atlas_data_dir — for candidates.db + ledger.db

    This factory does not claim to be OpenClaw's current TypeScript plugin SDK
    entrypoint. It exists for Python hosts and contract-level testing.
    """
    from pathlib import Path

    from atlas_core.api import AtlasMCPServer
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    data_dir = Path(
        config.get("atlas_data_dir", str(Path.home() / ".atlas")),
    ).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    quarantine = QuarantineStore(data_dir / "candidates.db")
    ledger = HashChainedLedger(data_dir / "ledger.db")
    server = AtlasMCPServer(
        driver=None, quarantine=quarantine, ledger=ledger,
    )
    return AtlasOpenClawPlugin(mcp_server=server)
