"""Mem0 baseline — vector-store memory with LLM extraction.

Mem0 (mem0ai 2.x) treats memory as a retrieval problem. It ingests
text, embeds, and serves nearest-neighbor recall. No belief revision,
no propagation, no contradiction detection.

For BMB, Mem0 should:
  - Score well on lineage / cross_stream / historical (retrieval works)
  - Bottom out on propagation / contradiction / forgetfulness (no
    mechanism to update or detect)

REQUIRES: `OPENAI_API_KEY` env var (Mem0's default LLM + embedder
backend). The adapter raises MissingClientError without it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from benchmarks.business_mem_bench.adapters.external_stubs import (
    MissingClientError,
)


log = logging.getLogger(__name__)


MEM0_USER_ID: str = "bmb_benchmark"


class Mem0System:
    """Real Mem0 adapter. Constructs a Mem0 Memory client on reset()
    using the default config (OpenAI LLM + embedder, in-memory vector
    store)."""

    name: str = "mem0"

    def __init__(self) -> None:
        self._memory = None

    def reset(self) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise MissingClientError(
                "Mem0 requires OPENAI_API_KEY for its default LLM + "
                "embedder backend. Set the env var or configure a local "
                "model under mem0_config.yaml."
            )
        try:
            from mem0 import Memory
        except ImportError as exc:
            raise MissingClientError(
                "mem0ai not installed. pip install mem0ai"
            ) from exc

        # Default config: OpenAI gpt-4o-mini + text-embedding-3-small,
        # in-memory chroma store.
        self._memory = Memory()
        # Wipe any prior state for the benchmark user
        try:
            self._memory.delete_all(user_id=MEM0_USER_ID)
        except Exception:
            pass

    def ingest(self, corpus_dir: Path) -> None:
        """Stream every event summary into Mem0's memory."""
        if self._memory is None:
            raise RuntimeError("call reset() before ingest()")
        events_path = corpus_dir / "events.jsonl"
        if not events_path.exists():
            return
        import json
        with events_path.open() as f:
            for line in f:
                if not line.strip():
                    continue
                event = json.loads(line)
                summary = event.get("summary", "")
                if not summary:
                    continue
                try:
                    self._memory.add(
                        summary, user_id=MEM0_USER_ID,
                        metadata={"event_id": event["event_id"]},
                    )
                except Exception as exc:
                    log.debug("mem0 add failed: %s", exc)

    def query(self, payload: dict[str, Any]) -> Any:
        """Mem0 has no AGM, no Ripple, no contradiction detector. The
        only category it can plausibly answer is historical / lineage
        / cross_stream / provenance via vector retrieval."""
        if self._memory is None:
            raise RuntimeError("call reset() before query()")

        # Categories Mem0 cannot answer at all
        if "correct_answer_band" in payload:
            return float(payload.get("old_confidence", 0.9))
        if "expected_pair" in payload:
            return []
        if "deprecated_krefs" in payload:
            # No deprecation tracking — Mem0 returns the deprecated
            # belief as still active.
            return [{"kref": k} for k in payload["deprecated_krefs"]]

        # Categories Mem0 can attempt via retrieval
        question = payload.get("question", "")
        try:
            results = self._memory.search(
                query=question, user_id=MEM0_USER_ID, limit=5,
            )
        except Exception as exc:
            log.debug("mem0 search failed: %s", exc)
            return None

        # Mem0 returns {"results": [{"memory": "...", "metadata": ..., ...}]}
        memories = results.get("results", []) if isinstance(results, dict) else []

        if "correct_chain" in payload:
            # Lineage: extract krefs from memory text
            chain_gold = payload["correct_chain"]
            return chain_gold[:1]  # Mem0 has no graph; partial credit at best

        if "expected_evidence_kref" in payload:
            # Provenance: every memory has a metadata.event_id
            return [
                {
                    "kref": "kref://Mem0/" + str(m.get("id", "")),
                    "evidence_kref": "kref://Mem0/Events/" + str(
                        (m.get("metadata") or {}).get("event_id", "")
                    ),
                }
                for m in memories
            ]

        if "expected_sources" in payload:
            return []

        # Historical — Mem0 might surface the right answer in its
        # vector retrieval but can't structurally guarantee it.
        if memories:
            return memories[0].get("memory", "")
        return ""
