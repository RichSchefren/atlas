"""Atlas retrieval — wraps vault-search + Cypher graph walks.

The vault-search daemon (port 9878) handles 24/7 GPU-accelerated
semantic search across Rich's 41K+ Obsidian files. Atlas delegates
text retrieval there rather than reinventing it.

Spec: PHASE-5-AND-BEYOND.md § 1.6
"""

from atlas_core.retrieval.vault_search import (
    DEFAULT_VAULT_SEARCH_URL,
    VaultSearchClient,
    VaultSearchHit,
)

__all__ = [
    "DEFAULT_VAULT_SEARCH_URL",
    "VaultSearchClient",
    "VaultSearchHit",
]
