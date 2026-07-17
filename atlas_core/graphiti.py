"""AtlasGraphiti — Graphiti ingestion entry point for Atlas.

Raw Graphiti extraction is intentionally separate from trusted Ripple execution.
The approved-candidate materializer owns the post-promotion Ripple hook because
only it has a ledger event, a stable belief kref, and confidence transition.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from graphiti_core import Graphiti

if TYPE_CHECKING:
    from atlas_core.ripple.engine import RippleEngine
    from atlas_core.trust.ledger import HashChainedLedger
    from atlas_core.trust.quarantine import QuarantineStore


log = logging.getLogger(__name__)


def _default_anthropic_llm_client() -> Any | None:
    """Build a Graphiti-compatible Anthropic LLMClient if ANTHROPIC_API_KEY is set.

    Atlas defaults to Claude rather than OpenAI. We try to import lazily so the module
    still loads in environments without the [anthropic] extra installed.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from graphiti_core.llm_client.anthropic_client import AnthropicClient
        from graphiti_core.llm_client.config import LLMConfig
    except ImportError:
        log.warning(
            "ANTHROPIC_API_KEY is set but graphiti-core[anthropic] is not installed; "
            "falling back to Graphiti's default LLM client."
        )
        return None
    return AnthropicClient(LLMConfig(api_key=api_key, model="claude-haiku-4-5-latest"))


class AtlasGraphiti(Graphiti):
    """Atlas's Graphiti entry point with Atlas's default LLM configuration.

    Raw extracted edges are not trusted facts and never trigger Ripple here.
    ``materialize_approved_candidates`` runs Ripple after ledger promotion.

    AGM-managed edges (SUPERSEDES, DEPENDS_ON, DERIVED_FROM, CONTRADICTS, SUPPORTS)
    bypass Graphiti's LLM-driven `resolve_extracted_edges` to preserve formal
    correctness of the AGM revision operators.

    LLM client default: Atlas uses Anthropic Claude unless one is passed explicitly
    or ANTHROPIC_API_KEY is unset (in which case the upstream Graphiti default
    applies — currently OpenAI, which requires OPENAI_API_KEY).
    """

    def __init__(
        self,
        *args,
        ripple_engine: RippleEngine | None = None,
        quarantine_store: QuarantineStore | None = None,
        ledger: HashChainedLedger | None = None,
        llm_client: Any | None = None,
        **kwargs,
    ):
        if llm_client is None:
            llm_client = _default_anthropic_llm_client()
        super().__init__(*args, llm_client=llm_client, **kwargs)
        self.ripple_engine = ripple_engine
        self.quarantine_store = quarantine_store
        self.ledger = ledger
        if ripple_engine is not None or ledger is not None:
            log.warning(
                "AtlasGraphiti no longer triggers Ripple from raw extracted edges; "
                "run ledger-approved candidates through materialize_approved_candidates"
            )
