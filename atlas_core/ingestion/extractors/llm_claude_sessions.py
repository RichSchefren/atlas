"""LLM extractor for Claude Code session JSONLs.

The deterministic extractor (atlas_core/ingestion/claude_sessions.py)
captures Rich's user prompts verbatim. This LLM extractor reads BOTH
sides of the conversation — Rich's prompts AND Claude's responses —
and pulls out the decisions Rich actually made.

Spec: PHASE-5-AND-BEYOND.md § 1.4
"""

from __future__ import annotations

import json
from pathlib import Path

from atlas_core.ingestion.extractors.llm_base import (
    LLMExtractionResult,
    LLMExtractor,
)


# One Claude session can be long; we slice into ~16K char windows.
MAX_CONVERSATION_CHARS: int = 16_000
MIN_CONVERSATION_CHARS: int = 400


class ClaudeSessionLLMExtractor(LLMExtractor):
    prompt_template_name: str = "claude_sessions"

    def extract_from_jsonl(self, path: Path) -> LLMExtractionResult:
        """Read the JSONL session file, format as Rich/Claude exchange,
        send to the LLM."""
        try:
            convo = self._build_conversation_text(path)
        except OSError as exc:
            return LLMExtractionResult(
                skipped_reason=f"read failed: {exc}",
            )
        return self.extract_from_text(convo)

    def extract_from_text(self, conversation: str) -> LLMExtractionResult:
        if len(conversation) < MIN_CONVERSATION_CHARS:
            return LLMExtractionResult(
                skipped_reason="conversation too short for LLM extraction",
            )
        if len(conversation) > MAX_CONVERSATION_CHARS:
            conversation = conversation[:MAX_CONVERSATION_CHARS]
        formatted = self._ensure_template().replace("{conversation}", conversation)
        return self.call_llm(formatted)

    @staticmethod
    def _build_conversation_text(path: Path) -> str:
        """Convert the session JSONL into a readable Rich/Claude transcript.

        Skips file-history-snapshots, attachments, system rows, and
        rows whose content is just noise prefixes (local-command-caveat,
        system-reminder)."""
        lines: list[str] = []
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                rtype = row.get("type")
                if rtype not in {"user", "assistant"}:
                    continue
                msg = row.get("message")
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", rtype)
                text = ClaudeSessionLLMExtractor._extract_text(msg.get("content"))
                if not text or text.startswith((
                    "<local-command-",
                    "<command-",
                    "<system-reminder>",
                    "<bash-",
                )):
                    continue
                lines.append(f"{role.upper()}: {text[:1500]}")
        return "\n\n".join(lines)

    @staticmethod
    def _extract_text(content) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            return "\n".join(p for p in parts if p).strip()
        return ""
