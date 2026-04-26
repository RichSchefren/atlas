"""EntityResolver — three-stage cascade: alias → fuzzy → LLM fallback.

Public entry point for the resolution layer. Every extractor calls
`resolver.resolve(surface, kind)` instead of building krefs by hand.

Resolution order (each layer falls through on miss):
  1. Exact alias hit (case-insensitive YAML lookup)         — confidence 1.0
  2. Fuzzy match above FUZZY_ACCEPT_FLOOR (rapidfuzz WRatio) — confidence 0.88-1.0
  3. LLM fallback (Claude Haiku, cached aggressively)       — confidence 0.5-0.95
  4. No match → caller decides whether to mint a new kref or skip

Spec: PHASE-5-AND-BEYOND.md § 1.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Union

from atlas_core.resolution.aliases import AliasDictionary, AliasMatch
from atlas_core.resolution.fuzzy import FuzzyEntityMatcher, FuzzyMatch
from atlas_core.resolution.llm_fallback import (
    LLMEntityResolver,
    LLMMatch,
    NoMatch,
)


log = logging.getLogger(__name__)


@dataclass
class ResolvedEntity:
    """Unified return shape across all three layers."""

    kref: str
    surface: str
    confidence: float
    source: str  # "alias_dictionary" | "fuzzy" | "llm_fallback"
    rationale: str = ""


class EntityResolver:
    """The resolution cascade. Construct once, share across extractors."""

    def __init__(
        self,
        *,
        aliases: AliasDictionary | None = None,
        enable_llm_fallback: bool = True,
    ):
        self.aliases = aliases or AliasDictionary()
        self.fuzzy = FuzzyEntityMatcher(self.aliases)
        self.enable_llm = enable_llm_fallback
        self._llm: LLMEntityResolver | None = None  # lazy

    def _ensure_llm(self) -> LLMEntityResolver:
        if self._llm is None:
            self._llm = LLMEntityResolver(self.aliases)
        return self._llm

    async def resolve(
        self,
        surface: str,
        kind: str = "Person",
    ) -> ResolvedEntity | NoMatch:
        """Run the three-stage cascade. Returns the first non-None match.

        `kind` is the entity type we're resolving (Person, Program,
        Client, etc.) — used to filter the LLM-fallback candidate pool.
        """
        if not surface or not surface.strip():
            return NoMatch(
                surface=surface, rationale="empty surface", should_create_new=False,
            )

        # Stage 1: exact alias
        alias_match: Optional[AliasMatch] = self.aliases.lookup(surface)
        if alias_match is not None:
            return ResolvedEntity(
                kref=alias_match.kref,
                surface=alias_match.surface,
                confidence=alias_match.confidence,
                source=alias_match.source,
            )

        # Stage 2: fuzzy
        fuzzy_match: Optional[FuzzyMatch] = self.fuzzy.lookup(surface)
        if fuzzy_match is not None:
            # Promote the alias dictionary so future hits are exact.
            # Cheap learning loop — Atlas gets smarter every miss.
            self.aliases.add(fuzzy_match.kref, surface)
            return ResolvedEntity(
                kref=fuzzy_match.kref,
                surface=fuzzy_match.surface,
                confidence=fuzzy_match.confidence,
                source=fuzzy_match.source,
                rationale=f"fuzzy match against {fuzzy_match.matched_alias!r}",
            )

        # Stage 3: LLM fallback
        if not self.enable_llm:
            return NoMatch(
                surface=surface,
                rationale="alias + fuzzy missed; LLM fallback disabled",
                should_create_new=True,
            )

        llm_result = await self._ensure_llm().resolve(surface, kref_kind=kind)
        if isinstance(llm_result, LLMMatch):
            self.aliases.add(llm_result.kref, surface)
            return ResolvedEntity(
                kref=llm_result.kref,
                surface=surface,
                confidence=llm_result.confidence,
                source=llm_result.source,
                rationale=llm_result.rationale,
            )
        return llm_result  # NoMatch from LLM (NEW or AMBIGUOUS)

    def add_alias(self, kref: str, surface: str) -> None:
        """Convenience — surface for callers that learn from external
        signal (e.g., a graph operator inserts a kref and wants to
        register its primary name as the first alias)."""
        self.aliases.add(kref, surface)

    def save(self) -> None:
        """Persist learned aliases to disk."""
        self.aliases.save()
