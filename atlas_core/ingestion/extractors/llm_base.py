"""Shared scaffolding for LLM-driven extractors.

Every per-stream extractor (vault / limitless / claude_sessions)
inherits this base. Centralizes:
  - Prompt template loading
  - Anthropic client init (lazy, fails-loud without ANTHROPIC_API_KEY)
  - Token-budget gating
  - JSONL output parsing
  - Error containment (one bad row doesn't kill the batch)

Spec: PHASE-5-AND-BEYOND.md § 1.4
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas_core.ingestion.budget import TokenBudget


log = logging.getLogger(__name__)


PROMPT_DIR: Path = Path(__file__).resolve().parent / "prompts"
DEFAULT_LLM_MODEL: str = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS: int = 1500


def load_prompt_template(name: str) -> str:
    """Read prompts/<name>.txt. Returns the template string."""
    path = PROMPT_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt template missing: {path}. Add it under "
            f"atlas_core/ingestion/extractors/prompts/."
        )
    return path.read_text(encoding="utf-8")


@dataclass
class LLMExtractionResult:
    """Outcome of one LLM call. `assertions` is the parsed JSONL output;
    `cost_usd` reports actual spend so callers can audit budget burn."""

    assertions: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    skipped_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.skipped_reason is None


class LLMExtractor:
    """Base class for the three per-stream LLM extractors.

    Subclasses define `prompt_template_name` and override `extract()`
    to wire stream-specific event shapes. The base handles client
    init, budget gating, and JSONL parsing.
    """

    prompt_template_name: str = ""  # subclass sets this

    def __init__(
        self,
        *,
        budget: TokenBudget | None = None,
        model: str = DEFAULT_LLM_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self.budget = budget or TokenBudget()
        self.model = model
        self.max_tokens = max_tokens
        self._client = None
        self._template: str | None = None

    def _ensure_template(self) -> str:
        if self._template is None:
            self._template = load_prompt_template(self.prompt_template_name)
        return self._template

    def _ensure_client(self):
        if self._client is not None:
            return
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY required for LLM extraction. "
                "Set the env var or fall back to deterministic extractors."
            )
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic SDK required") from exc
        self._client = Anthropic(api_key=api_key)

    def call_llm(
        self,
        formatted_prompt: str,
        *,
        estimated_input_tokens: int | None = None,
    ) -> LLMExtractionResult:
        """Fire one Claude Haiku call against the formatted prompt.

        Pre-checks the budget and skips with a clear reason if the
        day is exhausted. Charges the budget on success.
        """
        # Rough estimate: 4 chars per token for the prompt; max_tokens
        # for the output. We don't need precision here — the budget
        # is a safety net, not an accountant.
        if estimated_input_tokens is None:
            estimated_input_tokens = max(1, len(formatted_prompt) // 4)
        estimated_output_tokens = self.max_tokens

        if not self.budget.can_afford(
            estimated_input_tokens, estimated_output_tokens,
        ):
            return LLMExtractionResult(
                skipped_reason=(
                    f"daily budget exhausted "
                    f"(spent ${self.budget.state().spent_usd:.4f} / "
                    f"cap ${self.budget.daily_cap_usd:.2f})"
                ),
            )

        self._ensure_client()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": formatted_prompt}],
        )
        actual_in = response.usage.input_tokens
        actual_out = response.usage.output_tokens
        self.budget.charge(actual_in, actual_out)

        text = response.content[0].text
        assertions = self._parse_jsonl(text)
        from atlas_core.ingestion.budget import estimate_haiku_cost
        return LLMExtractionResult(
            assertions=assertions,
            input_tokens=actual_in,
            output_tokens=actual_out,
            cost_usd=estimate_haiku_cost(actual_in, actual_out),
        )

    @staticmethod
    def _parse_jsonl(text: str) -> list[dict[str, Any]]:
        """One assertion per line. Skip malformed rows but keep the
        rest — partial recovery is better than throwing away the batch."""
        out: list[dict[str, Any]] = []
        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
            except json.JSONDecodeError:
                log.debug("Skipping malformed JSONL row: %s", line[:80])
        return out
