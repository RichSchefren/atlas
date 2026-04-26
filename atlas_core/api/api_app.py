"""Module-level FastAPI app for uvicorn / launchd to import.

uvicorn loads `atlas_core.api.api_app:app` and serves it on
localhost:9879. The app is constructed at import time using env-
configured Neo4j + trust storage paths so the launchd plist can
spawn it without a wrapper script.

Spec: PHASE-5-AND-BEYOND.md § 1.1
"""

from __future__ import annotations

import os
from pathlib import Path


def _build_app():
    from neo4j import AsyncGraphDatabase

    from atlas_core.api import AtlasMCPServer, create_http_app
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    data_dir = Path(os.environ.get(
        "ATLAS_DATA_DIR", str(Path.home() / ".atlas"),
    ))
    data_dir.mkdir(parents=True, exist_ok=True)

    driver = AsyncGraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "atlasdev"),
        ),
    )
    quarantine = QuarantineStore(data_dir / "candidates.db")
    ledger = HashChainedLedger(data_dir / "ledger.db")
    server = AtlasMCPServer(
        driver=driver, quarantine=quarantine, ledger=ledger,
    )
    return create_http_app(mcp_server=server)


app = _build_app()
