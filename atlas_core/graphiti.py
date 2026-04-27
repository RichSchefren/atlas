"""AtlasGraphiti — main entry point. Subclass of Graphiti that adds Ripple + AGM.

Phase 2 Week 1 scaffold. Ripple, trust layer, ledger are stubs to be filled in
during Weeks 2-4. The integration pattern (subclass + super().add_episode + Ripple
hook) is locked from `06 - Ripple Algorithm Spec.md`.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from graphiti_core import Graphiti

if TYPE_CHECKING:
    from graphiti_core.graphiti import AddEpisodeResults

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
    """Atlas's main entry point. Subclasses Graphiti to add Ripple + AGM-compliant revision.

    Architecturally identical to upstream Graphiti for ingestion. The Atlas-specific
    behavior is the post-extraction hook that triggers Ripple propagation when edges
    are promoted to the trust ledger.

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

    async def add_episode(self, *args, **kwargs) -> AddEpisodeResults:
        """Override Graphiti's add_episode to run Ripple after standard ingestion.

        Sequencing rule: Ripple fires only on facts promoted to the ledger
        (trust = 1.0). Never on quarantined facts. Prevents graph oscillation
        from noisy capture streams (Phase 0 design lock; see Ripple Spec § 4).
        """
        results = await super().add_episode(*args, **kwargs)

        if self.ripple_engine and self.ledger:
            promoted_edges = [
                edge
                for edge in results.edges
                if self.ledger.is_promoted(edge.uuid)
            ]
            invalidated_edges = [
                edge for edge in results.edges if edge.expired_at is not None
            ]

            if promoted_edges:
                log.debug(
                    "Triggering Ripple on %d promoted edges (%d invalidated)",
                    len(promoted_edges),
                    len(invalidated_edges),
                )
                await self.ripple_engine.propagate(
                    new_edges=promoted_edges,
                    invalidated_edges=invalidated_edges,
                    episode=results.episode,
                )

        return results
