"""Prove Hermes/OpenClaw adapter CRUD + retrieval without Neo4j or Docker.

Run from the repository root:

    PYTHONPATH=. python scripts/demo_runtime_adapters.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from atlas_core.adapters import (
    AtlasHermesProvider,
    AtlasOpenClawPlugin,
    HermesMemoryItem,
)
from atlas_core.api import AtlasMCPServer
from atlas_core.trust import HashChainedLedger, QuarantineStore


async def run_demo() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-adapters-") as tmp:
        data_dir = Path(tmp)
        server = AtlasMCPServer(
            driver=None,
            quarantine=QuarantineStore(data_dir / "candidates.db"),
            ledger=HashChainedLedger(data_dir / "ledger.db"),
        )
        hermes = AtlasHermesProvider(mcp_server=server)
        openclaw = AtlasOpenClawPlugin(mcp_server=server)

        hermes_id = await hermes.put(HermesMemoryItem(
            content="The Atlas launch webinar is Thursday at 2 PM",
            metadata={
                "subject_kref": "kref://Atlas/Events/launch.event",
                "predicate": "schedule.start",
                "confidence": 0.85,
                "lane": "atlas_chat_history",
            },
        ))
        openclaw_id = await openclaw.store(
            "Richard prefers concise weekly status reports",
            metadata={
                "agent_id": "chief_of_staff",
                "session_id": "demo",
                "predicate": "pref.reporting_style",
                "confidence": 0.85,
            },
        )

        hermes_hits = await hermes.search("Atlas webinar Thursday", k=3)
        openclaw_hits = await openclaw.recall("concise status reports", k=3)
        fetched = await hermes.get(hermes_id)
        forgotten = await openclaw.forget(openclaw_id)
        after_forget = await openclaw.recall("concise status reports", k=3)

        assert [hit.item_id for hit in hermes_hits] == [hermes_id]
        assert [hit.memory_id for hit in openclaw_hits] == [openclaw_id]
        assert fetched is not None and fetched.content.endswith("2 PM")
        assert forgotten is True and after_forget == []

        print("Atlas portable runtime-adapter proof")
        print("  backend: SQLite only (Neo4j/Docker not started)")
        print(f"  Hermes:   put={hermes_id} search=1 get=ok")
        print(f"  OpenClaw: store={openclaw_id} recall=1 forget=ok")
        print("  result: PASS — storage and retrieval are functional, not stubs")


if __name__ == "__main__":
    asyncio.run(run_demo())
