"""LLM extractor for Limitless transcripts that the YAML pre-processor
didn't catch.

Spec 07 § 2.2: Limitless files have YAML frontmatter with structured
fields (action_items, decisions, friction_points, projects, people).
The deterministic extractor pulls those. The LLM extractor pulls
*everything else* — assertions buried in the transcript body that
the YAML pre-processor missed.

Spec: PHASE-5-AND-BEYOND.md § 1.4
"""

from __future__ import annotations

import re
from pathlib import Path

from atlas_core.ingestion.extractors.llm_base import (
    LLMExtractionResult,
    LLMExtractor,
)

# Limitless transcripts can be long (1-2 hours of audio). Cap input
# at ~16K chars (~4K tokens) per call to control cost; longer files
# get sliced.
MAX_TRANSCRIPT_CHARS: int = 16_000
MIN_TRANSCRIPT_CHARS: int = 500

_FRONTMATTER = re.compile(r"^---\s*\n.+?\n---\s*\n", re.DOTALL)


class LimitlessLLMExtractor(LLMExtractor):
    prompt_template_name: str = "limitless"

    def extract_from_path(self, path: Path) -> LLMExtractionResult:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return LLMExtractionResult(
                skipped_reason=f"read failed: {exc}",
            )
        return self.extract_from_text(text)

    def extract_from_text(self, text: str) -> LLMExtractionResult:
        body = _FRONTMATTER.sub("", text, count=1).strip()
        if len(body) < MIN_TRANSCRIPT_CHARS:
            return LLMExtractionResult(
                skipped_reason="transcript too short for LLM extraction",
            )
        if len(body) > MAX_TRANSCRIPT_CHARS:
            # Slice the head — Limitless transcripts have action items
            # near the end too, but the head usually carries the most
            # important decisions. Phase 2: slice the tail too.
            body = body[:MAX_TRANSCRIPT_CHARS]
        formatted = self._ensure_template().replace("{transcript}", body)
        return self.call_llm(formatted)
