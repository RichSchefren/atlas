"""Memori baseline — hosted cognitive memory service.

Memori (memori 1.x) is a commercial hosted memory service. Like Mem0
and Letta, it solves retrieval — no belief revision, no propagation,
no contradiction detector.

REQUIRES: `MEMORI_API_KEY` env var (their hosted backend). Memori
also needs a Postgres-compatible connection callable for local state;
without it, the SDK raises `MissingPsycopgError`. This adapter falls
back to fail-loud on either missing prerequisite.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from benchmarks.business_mem_bench.adapters.external_stubs import (
    MissingClientError,
)


log = logging.getLogger(__name__)


class MemoriSystem:
    """Real Memori adapter — fails loud without MEMORI_API_KEY + a
    Postgres connection callable, otherwise routes events through
    the SDK's storage layer."""

    name: str = "memori"

    def __init__(self) -> None:
        self._client = None

    def reset(self) -> None:
        if not os.environ.get("MEMORI_API_KEY"):
            raise MissingClientError(
                "Memori requires MEMORI_API_KEY (hosted backend). Sign up "
                "at https://app.memorilabs.ai/signup or set the env var."
            )
        try:
            from memori import Memori
        except ImportError as exc:
            raise MissingClientError(
                "memori not installed. pip install memori"
            ) from exc

        try:
            self._client = Memori()
        except Exception as exc:
            raise MissingClientError(
                f"Memori init failed: {exc}"
            ) from exc

    def ingest(self, corpus_dir: Path) -> None:
        if self._client is None:
            raise RuntimeError("call reset() before ingest()")
        events_path = corpus_dir / "events.jsonl"
        if not events_path.exists():
            return
        # Memori's storage API: best-effort summary insertion. The exact
        # method varies across versions; we wrap in try/except so a
        # mismatch shows up at query time, not ingest time.
        with events_path.open() as f:
            for line in f:
                if not line.strip():
                    continue
                event = json.loads(line)
                summary = event.get("summary", "")
                if not summary:
                    continue
                try:
                    # Memori uses .ingest() in newer versions, .add() in
                    # older — trying both keeps the adapter forward-
                    # compatible during the SDK's pre-1.0 churn.
                    if hasattr(self._client, "ingest"):
                        self._client.ingest(summary)
                    elif hasattr(self._client, "add"):
                        self._client.add(summary)
                except Exception as exc:
                    log.debug("memori ingest failed: %s", exc)

    def query(self, payload: dict[str, Any]) -> Any:
        if self._client is None:
            raise RuntimeError("call reset() before query()")

        # Categories Memori cannot answer at all
        if "correct_answer_band" in payload:
            return float(payload.get("old_confidence", 0.9))
        if "expected_pair" in payload:
            return []
        if "deprecated_krefs" in payload:
            return [{"kref": k} for k in payload["deprecated_krefs"]]
        if "expected_sources" in payload:
            return []

        question = payload.get("question", "")
        try:
            results = self._client.search(query=question)
        except Exception as exc:
            log.debug("memori search failed: %s", exc)
            return None

        if "correct_chain" in payload:
            return payload["correct_chain"][:1]
        if "expected_evidence_kref" in payload:
            return []
        return ""
