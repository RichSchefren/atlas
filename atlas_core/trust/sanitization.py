"""Pre-LLM sanitization pipeline.

Ports the Bicameral pattern (saves 20-60% tokens on real transcripts) and
adapts for Atlas conventions. Strip injected context blocks, untrusted
metadata wrappers, and verbose tool noise BEFORE the content reaches an
LLM extractor — keeps extraction prompts grounded in actual content.

Spec: 07 - Atlas Ingestion Pipeline Spec § 5
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ─── Patterns (compiled once at import) ──────────────────────────────────────

# <atlas-context>...</atlas-context> — Atlas's own context injection blocks.
# Any prior session that prepended Atlas context to a message will leave one
# of these wrappers; Atlas should never re-extract from its own output.
_ATLAS_CONTEXT_BLOCK = re.compile(
    r"<atlas-context>.*?</atlas-context>",
    re.DOTALL | re.IGNORECASE,
)

# <graphiti-context>...</graphiti-context> — Graphiti's injection (we inherit
# the same pattern when Atlas pipes through Graphiti's add_episode).
_GRAPHITI_CONTEXT_BLOCK = re.compile(
    r"<graphiti-context>.*?</graphiti-context>",
    re.DOTALL | re.IGNORECASE,
)

# Untrusted-metadata header lines followed by ```json fenced blocks.
# Pattern: header text matches one of the prefixes, then optional whitespace,
# then a json fence to its closing.
_UNTRUSTED_HEADERS = [
    "Conversation info:",
    "Sender (untrusted metadata):",
    "Replied message (untrusted, for context):",
    "Conversation info (untrusted metadata):",
    "Channel info:",
]
_UNTRUSTED_BLOCK_PATTERNS = [
    re.compile(
        re.escape(h) + r"\s*```(?:json)?\s*.*?```",
        re.DOTALL | re.IGNORECASE,
    )
    for h in _UNTRUSTED_HEADERS
]

# UUID-only lines (from logs / IDs that pollute extraction signal)
_UUID_ONLY_LINE = re.compile(
    r"^\s*[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\s*$",
    re.MULTILINE,
)

# Verbose tool-call noise — Claude Code transcripts include tool result
# wrappers that aren't useful for entity/claim extraction.
_TOOL_RESULT_WRAPPER = re.compile(
    r"<(?:tool_result|function_results)[^>]*>.*?</(?:tool_result|function_results)>",
    re.DOTALL | re.IGNORECASE,
)

# Unicode normalizations: convert directional / typographic characters to
# their ASCII equivalents so LLM tokenization is predictable.
_UNICODE_REPLACEMENTS: dict[str, str] = {
    "→": "->",
    "←": "<-",
    "↑": "^",
    "↓": "v",
    "•": "-",
    "—": "-",  # em-dash
    "–": "-",  # en-dash
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
}

# Whitespace collapse: 3+ consecutive newlines → 2 (paragraph break).
_EXCESS_NEWLINES = re.compile(r"\n{3,}")
# Trailing whitespace on every line
_TRAILING_WS = re.compile(r"[ \t]+\n")


# ─── Functional API ──────────────────────────────────────────────────────────


def strip_atlas_context(content: str) -> str:
    """Remove <atlas-context>...</atlas-context> blocks. Atlas's own injection."""
    return _ATLAS_CONTEXT_BLOCK.sub("", content)


def strip_graphiti_context(content: str) -> str:
    """Remove <graphiti-context>...</graphiti-context> blocks (Bicameral pattern)."""
    return _GRAPHITI_CONTEXT_BLOCK.sub("", content)


def strip_untrusted_metadata(content: str) -> str:
    """Strip header + ```json fenced blocks of untrusted source metadata."""
    out = content
    for pattern in _UNTRUSTED_BLOCK_PATTERNS:
        out = pattern.sub("", out)
    return out


def strip_tool_result_wrappers(content: str) -> str:
    """Remove <tool_result> / <function_results> blocks from Claude Code logs."""
    return _TOOL_RESULT_WRAPPER.sub("", content)


def normalize_punctuation(content: str) -> str:
    """Convert typographic Unicode to ASCII equivalents."""
    out = content
    for src, repl in _UNICODE_REPLACEMENTS.items():
        out = out.replace(src, repl)
    return out


def drop_uuid_only_lines(content: str) -> str:
    """Remove lines containing only a UUID — common in raw log output."""
    return _UUID_ONLY_LINE.sub("", content)


def collapse_whitespace(content: str) -> str:
    """Trim trailing whitespace and collapse 3+ newlines to 2."""
    out = _TRAILING_WS.sub("\n", content)
    out = _EXCESS_NEWLINES.sub("\n\n", out)
    return out.strip("\n")


@dataclass(frozen=True)
class SanitizationStats:
    """Per-call metrics so callers can monitor token-saving effectiveness."""

    input_chars: int
    output_chars: int

    @property
    def chars_saved(self) -> int:
        return self.input_chars - self.output_chars

    @property
    def reduction_ratio(self) -> float:
        if self.input_chars == 0:
            return 0.0
        return self.chars_saved / self.input_chars


def sanitize_for_llm(
    content: str,
    *,
    return_stats: bool = False,
) -> str | tuple[str, SanitizationStats]:
    """The full pre-LLM sanitization pipeline.

    Composition order (matters):
      1. strip_atlas_context        — remove our own injection markers
      2. strip_graphiti_context     — remove inherited Graphiti markers
      3. strip_untrusted_metadata   — remove untrusted-source JSON wrappers
      4. strip_tool_result_wrappers — remove verbose Claude tool blocks
      5. normalize_punctuation      — typographic → ASCII
      6. drop_uuid_only_lines       — strip log noise
      7. collapse_whitespace        — collapse runs

    Per Bicameral profiling: 20-60% token reduction on real transcripts.
    Atlas measures per-call so we can verify the savings on Rich's actual
    streams in Phase 3.

    Args:
        content: raw pre-LLM input
        return_stats: when True, also return SanitizationStats

    Returns:
        sanitized content (str), OR (sanitized, stats) tuple if return_stats=True
    """
    input_chars = len(content)

    out = strip_atlas_context(content)
    out = strip_graphiti_context(out)
    out = strip_untrusted_metadata(out)
    out = strip_tool_result_wrappers(out)
    out = normalize_punctuation(out)
    out = drop_uuid_only_lines(out)
    out = collapse_whitespace(out)

    if return_stats:
        return out, SanitizationStats(input_chars=input_chars, output_chars=len(out))
    return out
