"""Vanilla baseline — no memory, no retrieval. Establishes the floor.

This is the system every other system has to beat. If a memory system
doesn't outperform vanilla, it's not actually doing memory work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class VanillaSystem:
    """Returns None for every query — the no-memory floor."""

    name: str = "vanilla_no_memory"

    def reset(self) -> None:
        pass

    def ingest(self, corpus_dir: Path) -> None:
        pass

    def query(self, payload: dict[str, Any]) -> Any:
        return None
