"""Atlas entity resolution — alias → fuzzy → LLM cascade.

Spec: PHASE-5-AND-BEYOND.md § 1.3
"""

from atlas_core.resolution.aliases import (
    DEFAULT_ALIAS_PATH,
    AliasDictionary,
    AliasMatch,
)
from atlas_core.resolution.fuzzy import (
    FUZZY_ACCEPT_FLOOR,
    FuzzyEntityMatcher,
    FuzzyMatch,
)
from atlas_core.resolution.llm_fallback import (
    LLMEntityResolver,
    LLMMatch,
    NoMatch,
    ResolutionCache,
)
from atlas_core.resolution.resolver import EntityResolver, ResolvedEntity

__all__ = [
    "AliasDictionary",
    "AliasMatch",
    "DEFAULT_ALIAS_PATH",
    "FuzzyEntityMatcher",
    "FuzzyMatch",
    "FUZZY_ACCEPT_FLOOR",
    "LLMEntityResolver",
    "LLMMatch",
    "NoMatch",
    "ResolutionCache",
    "EntityResolver",
    "ResolvedEntity",
]
