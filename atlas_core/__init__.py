"""Atlas — open-source local-first cognitive memory.

Same AGM-compliant belief revision math as commercial state-of-the-art,
running entirely on the user's machine, with automatic downstream
reassessment (Ripple) — the thing nobody else ships.
"""

from __future__ import annotations

__version__ = "0.1.0a1"


def __getattr__(name: str):
    """Lazy re-exports — keeps `atlas_core.ontology` importable without graphiti_core
    pulling in heavy deps just for unit tests of the typed ontology.

    `from atlas_core import AtlasGraphiti` works as expected; importing
    `atlas_core.ontology.person` does not trigger the graphiti_core import.
    """
    if name == "AtlasGraphiti":
        from atlas_core.graphiti import AtlasGraphiti as _AtlasGraphiti
        return _AtlasGraphiti
    raise AttributeError(f"module 'atlas_core' has no attribute {name!r}")


__all__ = ["AtlasGraphiti", "__version__"]
