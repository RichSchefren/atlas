"""LLM extractor for Obsidian vault free-text bodies.

Wraps LLMExtractor with the vault prompt template and the file-body
slicing logic. Skips files where the deterministic extractor already
captured everything (frontmatter-only files don't need LLM).

Spec: PHASE-5-AND-BEYOND.md § 1.4
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from atlas_core.ingestion.extractors.llm_base import (
    LLMExtractionResult,
    LLMExtractor,
)


# Files smaller than this don't have enough body to warrant an LLM call.
MIN_BODY_CHARS: int = 200

# Drop frontmatter and HTML comments before sending to the LLM.
_FRONTMATTER = re.compile(r"^---\s*\n.+?\n---\s*\n", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.+?-->", re.DOTALL)


class VaultLLMExtractor(LLMExtractor):
    prompt_template_name: str = "vault"

    def extract_from_path(self, path: Path) -> LLMExtractionResult:
        """Read the file, strip noise, send body to the LLM."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return LLMExtractionResult(
                skipped_reason=f"read failed: {exc}",
            )
        body = self._strip_to_body(text)
        if len(body) < MIN_BODY_CHARS:
            return LLMExtractionResult(
                skipped_reason="body too short for LLM extraction",
            )
        formatted = self._ensure_template().replace("{note_body}", body)
        return self.call_llm(formatted)

    def extract_from_text(self, body: str) -> LLMExtractionResult:
        """Direct-text variant for testing or already-loaded content."""
        body = self._strip_to_body(body)
        if len(body) < MIN_BODY_CHARS:
            return LLMExtractionResult(
                skipped_reason="body too short for LLM extraction",
            )
        formatted = self._ensure_template().replace("{note_body}", body)
        return self.call_llm(formatted)

    @staticmethod
    def _strip_to_body(text: str) -> str:
        text = _FRONTMATTER.sub("", text, count=1)
        text = _HTML_COMMENT.sub("", text)
        return text.strip()
