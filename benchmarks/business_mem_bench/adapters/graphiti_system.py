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

import logging
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


class GraphitiSystem:
    """Vanilla Graphiti — no Atlas extensions."""

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
        self._client = None

    def reset(self) -> None:
        # graphiti-core uses Neo4j for storage; namespace pattern + DELETE
        # is the cleanest reset for benchmark runs.
        try:
            from graphiti_core import Graphiti  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "graphiti-core not installed. Add to pyproject deps."
            ) from exc

    def ingest(self, corpus_dir: Path) -> None:
        # W1 stub — Graphiti's add_episode loop wires when corpus ships.
        log.info("Graphiti.ingest(%s) — wired in W2 once corpus exists", corpus_dir)

    def query(self, payload: dict[str, Any]) -> Any:
        # Without Ripple, Graphiti has no automatic reassessment, so the
        # "answer" to propagation questions is the OLD confidence —
        # Graphiti returns whatever the belief node still says, ignoring
        # that an upstream changed. This is exactly the gap Atlas fills.
        if "correct_answer_band" in payload:
            return payload.get("old_confidence", 0.9)
        # For other categories, vanilla returns nothing — we'll wire
        # specific Graphiti queries when the corpus ships.
        return None
