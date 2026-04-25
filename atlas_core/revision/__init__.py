"""Atlas AGM-compliant revision module.

Implements Kumiho paper (arxiv:2603.17244) Definitions 7.1-7.8:
  - 7.4 Graph-Native Revision (B * A)
  - 7.5 Graph-Native Contraction (B ÷ A)
  - 7.6 Selection Function (content-based, exhaustive)
  - 7.7 Graph-Native Expansion (B + A)

Atlas adopts the kref:// URI parser as a typed addressable scheme.
"""

from atlas_core.revision.uri import Kref, KrefParseError

__all__ = ["Kref", "KrefParseError"]
