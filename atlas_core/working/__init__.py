"""Atlas working memory — Letta-style block manager.

Tier 4: Atlas as the COMPLETE memory layer (long-term + working).
Without this tier, Atlas covers long-term storage but agents still
need Letta or Mem0 for in-context working memory. With it, Atlas
is the only memory layer agents need.

Spec: PHASE-5-AND-BEYOND.md § 4
"""

from atlas_core.working.auto_summarizer import AutoSummarizer
from atlas_core.working.blocks import (
    DEFAULT_BLOCK_MAX_TOKENS,
    MemoryBlock,
    estimate_tokens,
)
from atlas_core.working.manager import AssembledContext, WorkingMemoryManager
from atlas_core.working.standard import (
    build_human_block,
    build_persona_block,
    standard_block_set,
)

__all__ = [
    "AssembledContext",
    "AutoSummarizer",
    "DEFAULT_BLOCK_MAX_TOKENS",
    "MemoryBlock",
    "WorkingMemoryManager",
    "build_human_block",
    "build_persona_block",
    "estimate_tokens",
    "standard_block_set",
]
