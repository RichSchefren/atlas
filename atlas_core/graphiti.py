"""AtlasGraphiti — main entry point. Subclass of Graphiti that adds Ripple + AGM.

Phase 2 Week 1 scaffold. Ripple, trust layer, ledger are stubs to be filled in
during Weeks 2-4. The integration pattern (subclass + super().add_episode + Ripple
hook) is locked from `06 - Ripple Algorithm Spec.md`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from graphiti_core import Graphiti

if TYPE_CHECKING:
    from graphiti_core.graphiti import AddEpisodeResults

    from atlas_core.ripple.engine import RippleEngine
    from atlas_core.trust.ledger import HashChainedLedger
    from atlas_core.trust.quarantine import QuarantineStore


log = logging.getLogger(__name__)


class AtlasGraphiti(Graphiti):
    """Atlas's main entry point. Subclasses Graphiti to add Ripple + AGM-compliant revision.

    Architecturally identical to upstream Graphiti for ingestion. The Atlas-specific
    behavior is the post-extraction hook that triggers Ripple propagation when edges
    are promoted to the trust ledger.

    AGM-managed edges (SUPERSEDES, DEPENDS_ON, DERIVED_FROM, CONTRADICTS, SUPPORTS)
    bypass Graphiti's LLM-driven `resolve_extracted_edges` to preserve formal
    correctness of the AGM revision operators.
    """

    def __init__(
        self,
        *args,
        ripple_engine: Optional[RippleEngine] = None,
        quarantine_store: Optional[QuarantineStore] = None,
        ledger: Optional[HashChainedLedger] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
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
