"""LLM-driven extractors for free-text content.

The deterministic extractors in atlas_core/ingestion/ pull
frontmatter / YAML / structured fields. These LLM extractors handle
free-text bodies — the actual content of writing.

Each module wires Claude Haiku 4.5 against a per-stream prompt
template. Token budget enforcement gates LLM calls behind the
ATLAS_DAILY_LLM_BUDGET_USD env var (default $5/day).

Spec: PHASE-5-AND-BEYOND.md § 1.4
"""

from atlas_core.ingestion.extractors.llm_base import (
    LLMExtractor,
    LLMExtractionResult,
    load_prompt_template,
)
from atlas_core.ingestion.extractors.llm_claude_sessions import (
    ClaudeSessionLLMExtractor,
)
from atlas_core.ingestion.extractors.llm_limitless import (
    LimitlessLLMExtractor,
)
from atlas_core.ingestion.extractors.llm_vault import VaultLLMExtractor

__all__ = [
    "LLMExtractor",
    "LLMExtractionResult",
    "load_prompt_template",
    "VaultLLMExtractor",
    "LimitlessLLMExtractor",
    "ClaudeSessionLLMExtractor",
]
