"""Auto-summarizer for blocks that exceed their token threshold.

When a block hits 90% of max_tokens, fire one Claude Haiku call to
compress it to ~70%. The compressor preserves the most-cited entity
references — those are the load-bearing tokens.

Spec: PHASE-5-AND-BEYOND.md § 4.1
"""

from __future__ import annotations

import logging
import os

from atlas_core.ingestion.budget import TokenBudget
from atlas_core.working.blocks import (
    DEFAULT_SUMMARIZE_TARGET,
    MemoryBlock,
)

log = logging.getLogger(__name__)


DEFAULT_LLM_MODEL: str = "claude-haiku-4-5-20251001"


SUMMARIZER_PROMPT: str = """Compress this working-memory block from
the agent named {persona_name} for the user named {human_name}.

Current block content (~{current_tokens} tokens, max {max_tokens}):
---
{content}
---

Compress to roughly {target_tokens} tokens. Rules:
- PRESERVE every mention of named entities (people, programs,
  decisions, projects). Those are the load-bearing references.
- DROP transitions, hedging language, repeated reassurances.
- KEEP imperative facts ("Sarah owns the launch") over descriptive
  paragraphs.
- Maintain the same voice and POV as the original.

Reply with ONLY the compressed block content. No commentary, no
preamble, no markdown wrappers.
"""


class AutoSummarizer:
    """Compresses blocks when they exceed the summarize threshold.

    Lazy Anthropic init, budget-gated. Returns the original block
    unchanged when budget is exhausted (we'd rather have a slightly-
    over-limit block than lose its content).
    """

    def __init__(
        self,
        *,
        budget: TokenBudget | None = None,
        model: str = DEFAULT_LLM_MODEL,
    ):
        self.budget = budget or TokenBudget()
        self.model = model
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY required for block auto-summarization"
            )
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic SDK required") from exc
        self._client = Anthropic(api_key=api_key)

    def summarize(
        self,
        block: MemoryBlock,
        *,
        human_name: str = "the user",
        persona_name: str = "Atlas",
    ) -> MemoryBlock:
        """Returns a NEW MemoryBlock with summarized content. The
        original is never mutated — caller decides whether to
        replace it in the manager."""
        target_tokens = int(block.max_tokens * DEFAULT_SUMMARIZE_TARGET)
        est_in = block.estimated_tokens + 300
        est_out = target_tokens + 100

        if not self.budget.can_afford(est_in, est_out):
            log.warning(
                "Auto-summarize skipped (budget exhausted) — "
                "block %s remains over limit at %d tokens",
                block.name, block.estimated_tokens,
            )
            return block

        prompt = (
            SUMMARIZER_PROMPT
            .replace("{persona_name}", persona_name)
            .replace("{human_name}", human_name)
            .replace("{current_tokens}", str(block.estimated_tokens))
            .replace("{max_tokens}", str(block.max_tokens))
            .replace("{target_tokens}", str(target_tokens))
            .replace("{content}", block.content)
        )

        self._ensure_client()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=est_out,
            messages=[{"role": "user", "content": prompt}],
        )
        actual_in = response.usage.input_tokens
        actual_out = response.usage.output_tokens
        self.budget.charge(actual_in, actual_out)

        new_content = response.content[0].text.strip()
        return MemoryBlock(
            name=block.name,
            content=new_content,
            max_tokens=block.max_tokens,
            write_policy=block.write_policy,
            metadata={
                **block.metadata,
                "summarized_from_tokens": block.estimated_tokens,
                "summarized_at_input_tokens": actual_in,
                "summarized_at_output_tokens": actual_out,
            },
        )
