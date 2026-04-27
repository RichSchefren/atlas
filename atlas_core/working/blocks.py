"""MemoryBlock dataclass + token estimation.

A block is one named, size-bounded piece of context that gets pinned
into an LLM's prompt. Letta's standard set is Human / Persona; Atlas
adds CurrentPriorities (auto-populated from open Commitments).

Spec: PHASE-5-AND-BEYOND.md § 4.1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DEFAULT_BLOCK_MAX_TOKENS: int = 1500
"""Sized to fit a typical block in a 16K context window without
crowding out conversational turns. Letta's default is similar."""

DEFAULT_SUMMARIZE_THRESHOLD: float = 0.90
"""Trigger summarization when a block hits this fraction of max."""

DEFAULT_SUMMARIZE_TARGET: float = 0.70
"""Compress to this fraction so we don't immediately re-trigger."""


def estimate_tokens(text: str) -> int:
    """Rough estimate: ~4 chars per token for English. Avoids needing
    a tokenizer dependency for the budget check; the LLM call records
    actual token usage via the budget system."""
    return max(1, len(text) // 4)


@dataclass
class MemoryBlock:
    """One block of working memory.

    Atlas distinguishes blocks from archival storage: blocks are
    pinned in-context for every LLM call this agent makes. Archival
    facts are searched on-demand. The block manager handles the
    handoff (auto-summarize when over limit; flush summaries to
    archival; rebuild the block from current graph state on demand).
    """

    name: str
    content: str
    max_tokens: int = DEFAULT_BLOCK_MAX_TOKENS
    write_policy: str = "human"
    """'human' = only Rich edits; 'auto' = manager rewrites from graph;
    'append' = agents append to it during conversation."""
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(self.content)

    @property
    def utilization(self) -> float:
        """Fraction of max_tokens used [0, 1+]. Above 1.0 means
        over-limit and needs immediate summarization."""
        return self.estimated_tokens / self.max_tokens

    @property
    def needs_summarization(self) -> bool:
        return self.utilization >= DEFAULT_SUMMARIZE_THRESHOLD

    def update_content(self, new_content: str) -> None:
        self.content = new_content
        self.last_updated = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "max_tokens": self.max_tokens,
            "write_policy": self.write_policy,
            "last_updated": self.last_updated,
            "metadata": self.metadata,
            "estimated_tokens": self.estimated_tokens,
            "utilization": self.utilization,
        }
