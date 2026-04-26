"""OpenClaw memory plugin adapter — Atlas as a memory backend in
OpenClaw's plugin architecture (363K stars, plugin manifest at
github.com/OpenClawIO/openclaw/blob/main/docs/plugins/memory.md inferred).

OpenClaw plugin contract (memory subtype):
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

OpenClaw is more conversational than Hermes — it expects raw text as
the storage primitive. Atlas wraps that by auto-extracting subject_kref +
predicate via LLM (W7), with a deterministic fallback that uses the agent
session id as the subject and 'said' as the predicate.

Spec: 09 - Agent Runtime Memory Competitive Landscape.md (OpenClaw section)
      Plugin manifest: contract sketched here, validated against upstream W7.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from atlas_core.api.mcp_server import AtlasMCPServer


log = logging.getLogger(__name__)


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
    timestamp: Optional[str] = None


class AtlasOpenClawPlugin:
    """OpenClaw memory plugin backed by AtlasMCPServer.

    Differs from Hermes adapter in that OpenClaw passes raw text and expects
    the plugin to handle structuring. We auto-derive subject + predicate
    from session metadata + a default 'said' predicate; W7 swaps in LLM
    extraction when an extractor is configured.
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
        """W7 wires through retrieval layer (BGE + kref hop). Phase 2 W6
        returns empty list — OpenClaw falls back to in-context memory."""
        log.info(
            "AtlasOpenClawPlugin.recall(%r, k=%d) — W7 wires retrieval; "
            "returning [] for now.", query, k,
        )
        return []

    async def forget(self, memory_id: str) -> bool:
        """W7 wires AGM contract(). Phase 2 W6 returns False so OpenClaw
        knows the deletion didn't actually happen."""
        log.info(
            "AtlasOpenClawPlugin.forget(%r) — W7 wires AGM contract; "
            "returning False for now.", memory_id,
        )
        return False

    async def list_memories(
        self, filter: Optional[dict[str, Any]] = None,
    ) -> list[Recall]:
        """List quarantine candidates by agent_id (filter['agent_id'])."""
        result = await self.mcp.dispatch(
            "quarantine.list_pending",
            {"limit": (filter or {}).get("limit", 50)},
        )
        if not result.ok:
            return []
        agent_id = (filter or {}).get("agent_id")
        rows = result.result["candidates"]
        if agent_id:
            rows = [
                r for r in rows
                if f"openclaw/Agents/{agent_id}" in r["subject_kref"]
            ]
        return [
            Recall(
                memory_id=r["candidate_id"],
                text=r["object_value"],
                score=float(r.get("trust_score", 0.0)),
                metadata={
                    "lane": r["lane"],
                    "subject_kref": r["subject_kref"],
                    "predicate": r["predicate"],
                },
                timestamp=r.get("created_at"),
            )
            for r in rows
        ]


def plugin(config: dict[str, Any]) -> AtlasOpenClawPlugin:
    """OpenClaw plugin entrypoint. `openclaw load atlas-memory` calls this.

    config keys:
      neo4j_uri / neo4j_user / neo4j_password — Neo4j connection
      atlas_data_dir                          — for candidates.db + ledger.db
    """
    from pathlib import Path

    from neo4j import AsyncGraphDatabase

    from atlas_core.api import AtlasMCPServer
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    data_dir = Path(config.get("atlas_data_dir", str(Path.home() / ".atlas")))
    data_dir.mkdir(parents=True, exist_ok=True)

    driver = AsyncGraphDatabase.driver(
        config.get("neo4j_uri", "bolt://localhost:7687"),
        auth=(
            config.get("neo4j_user", "neo4j"),
            config.get("neo4j_password", "atlasdev"),
        ),
    )
    quarantine = QuarantineStore(data_dir / "candidates.db")
    ledger = HashChainedLedger(data_dir / "ledger.db")
    server = AtlasMCPServer(
        driver=driver, quarantine=quarantine, ledger=ledger,
    )
    return AtlasOpenClawPlugin(mcp_server=server)
