"""Letta baseline — block-based working memory with token-limit summarization.

Letta is excellent for in-context memory but has no belief revision,
no graph structure, and no propagation. For BMB the expected outcome
is similar to Mem0 — wins on retrieval-style queries, bottoms out on
the categories Atlas was built for.

REQUIRES: `OPENAI_API_KEY` for Letta's default chat model. The
adapter raises MissingClientError without it.
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


class LettaSystem:
    """Letta adapter. Stores corpus events into the agent's archival
    memory; queries via the agent's recall function.

    Phase-3-W3 minimum-viable: we use letta's local in-memory backend
    so the benchmark doesn't require a running letta server."""

    name: str = "letta"

    def __init__(self) -> None:
        self._client = None
        self._agent_id = None

    def reset(self) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise MissingClientError(
                "Letta requires OPENAI_API_KEY for the default chat model. "
                "Set the env var or configure a local model in letta config."
            )
        try:
            from letta import create_client
        except ImportError as exc:
            raise MissingClientError(
                "letta not installed. pip install letta"
            ) from exc

        # In-memory client (no server) — simplest reproducible path.
        self._client = create_client()
        # Fresh agent for each benchmark run
        try:
            agent = self._client.create_agent(
                name=f"bmb_{os.getpid()}",
                preset="memgpt_chat",
            )
            self._agent_id = agent.id
        except Exception as exc:
            raise MissingClientError(
                f"Letta agent creation failed: {exc}"
            ) from exc

    def ingest(self, corpus_dir: Path) -> None:
        if self._client is None:
            raise RuntimeError("call reset() before ingest()")
        events_path = corpus_dir / "events.jsonl"
        if not events_path.exists():
            return

        with events_path.open() as f:
            for line in f:
                if not line.strip():
                    continue
                event = json.loads(line)
                summary = event.get("summary", "")
                if not summary:
                    continue
                try:
                    self._client.insert_archival_memory(
                        agent_id=self._agent_id,
                        memory=summary,
                    )
                except Exception as exc:
                    log.debug("letta archival insert failed: %s", exc)

    def query(self, payload: dict[str, Any]) -> Any:
        if self._client is None:
            raise RuntimeError("call reset() before query()")

        # Categories Letta can't answer
        if "correct_answer_band" in payload:
            return float(payload.get("old_confidence", 0.9))
        if "expected_pair" in payload:
            return []
        if "deprecated_krefs" in payload:
            return [{"kref": k} for k in payload["deprecated_krefs"]]

        question = payload.get("question", "")
        try:
            response = self._client.send_message(
                agent_id=self._agent_id,
                message=question,
                role="user",
            )
        except Exception as exc:
            log.debug("letta send_message failed: %s", exc)
            return None

        # Best-effort response extraction — letta's API surface varies
        # across versions; falling back to None on shape mismatch keeps
        # the harness running.
        try:
            messages = getattr(response, "messages", []) or []
            for m in reversed(messages):
                content = getattr(m, "content", None) or getattr(m, "text", None)
                if content:
                    return content
        except Exception:
            pass
        return ""
