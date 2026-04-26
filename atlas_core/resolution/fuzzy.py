"""Fuzzy entity matcher — second stop in resolution after the alias
dictionary returns no exact hit.

Uses rapidfuzz (Levenshtein-class similarity) over the alias
dictionary's known surfaces. Returns the best match if its score
exceeds FUZZY_ACCEPT_FLOOR; below the floor, returns None and the
caller falls through to the LLM fallback.

Spec: PHASE-5-AND-BEYOND.md § 1.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process

from atlas_core.resolution.aliases import AliasDictionary, AliasMatch


log = logging.getLogger(__name__)


# Conservative floor — we'd rather miss a fuzzy match and fall
# through to LLM than create a wrong canonical mapping.
FUZZY_ACCEPT_FLOOR: float = 88.0
"""rapidfuzz scores 0-100. Below this, we don't trust the match."""

FUZZY_AMBIGUOUS_FLOOR: float = 75.0
"""Below this, fall through cleanly. Between AMBIGUOUS and ACCEPT,
return None but log so callers can promote to LLM fallback."""


@dataclass
class FuzzyMatch:
    """Carrier shape — same fields as AliasMatch but `source='fuzzy'`."""

    kref: str
    surface: str
    matched_alias: str
    confidence: float  # in [0.0, 1.0]
    source: str = "fuzzy"


class FuzzyEntityMatcher:
    """Wraps rapidfuzz over the AliasDictionary's known surfaces.

    Build the matcher once at startup; lookups are O(N) over known
    aliases, which is fine for N < 10K (Rich-scale).
    """

    def __init__(self, aliases: AliasDictionary):
        self.aliases = aliases

    def lookup(self, surface: str) -> Optional[FuzzyMatch]:
        """Return the best fuzzy hit if confidence ≥ FUZZY_ACCEPT_FLOOR.

        rapidfuzz.process.extractOne uses WRatio by default (combination
        of partial / token-set / token-sort scorers). Robust against
        case, word reordering, and minor typos.
        """
        if not surface:
            return None

        # Build the candidate pool: every known alias surface.
        # We index by lowercase to match the alias dictionary's own
        # case-insensitive lookup contract.
        candidates: dict[str, str] = {}
        for kref in self.aliases.known_krefs():
            for s in self.aliases.all_surfaces_for(kref):
                candidates[s] = kref

        if not candidates:
            return None

        match = process.extractOne(
            surface,
            list(candidates.keys()),
            scorer=fuzz.WRatio,
        )
        if match is None:
            return None

        matched_surface, score, _ = match
        if score < FUZZY_AMBIGUOUS_FLOOR:
            return None
        if score < FUZZY_ACCEPT_FLOOR:
            log.debug(
                "Fuzzy %r → %r at %.1f (below ACCEPT floor %.1f); "
                "punt to LLM fallback",
                surface, matched_surface, score, FUZZY_ACCEPT_FLOOR,
            )
            return None

        return FuzzyMatch(
            kref=candidates[matched_surface],
            surface=surface,
            matched_alias=matched_surface,
            confidence=score / 100.0,
        )
