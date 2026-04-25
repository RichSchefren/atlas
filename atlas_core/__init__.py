"""Atlas — open-source local-first cognitive memory.

Same AGM-compliant belief revision math as commercial state-of-the-art,
running entirely on the user's machine, with automatic downstream
reassessment (Ripple) — the thing nobody else ships.
"""

__version__ = "0.1.0a1"

# Re-exports for the public API
from atlas_core.graphiti import AtlasGraphiti

__all__ = ["AtlasGraphiti", "__version__"]
