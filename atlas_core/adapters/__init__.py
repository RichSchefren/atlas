"""Atlas runtime adapters.

Each adapter wraps AtlasMCPServer in the contract a target runtime expects:

  - claude_code  → JSON-RPC 2.0 over stdio (MCP spec)
  - hermes       → functional SDK-neutral CRUD/retrieval core
  - openclaw     → functional SDK-neutral CRUD/retrieval core

The Hermes and OpenClaw cores provide real SQLite-backed storage, retrieval,
listing, and forgetting without Neo4j. Current upstream-native wrappers are a
separate packaging layer; see docs/RUNTIME_ADAPTERS.md. When Neo4j is enabled,
the same Atlas substrate also exposes AGM revision and Ripple behavior.

Spec: 09 - Agent Runtime Memory Competitive Landscape.md
"""

from atlas_core.adapters.hermes import (
    PROVIDER_NAME as HERMES_PROVIDER_NAME,
)
from atlas_core.adapters.hermes import (
    AtlasHermesProvider,
    HermesMemoryItem,
)
from atlas_core.adapters.openclaw import (
    PLUGIN_NAME as OPENCLAW_PLUGIN_NAME,
)
from atlas_core.adapters.openclaw import (
    PLUGIN_TYPE as OPENCLAW_PLUGIN_TYPE,
)
from atlas_core.adapters.openclaw import (
    PLUGIN_VERSION as OPENCLAW_PLUGIN_VERSION,
)
from atlas_core.adapters.openclaw import (
    AtlasOpenClawPlugin,
)
from atlas_core.adapters.openclaw import (
    Recall as OpenClawRecall,
)
from atlas_core.adapters.openclaw import (
    plugin as openclaw_plugin,
)

__all__ = [
    "AtlasHermesProvider",
    "HermesMemoryItem",
    "HERMES_PROVIDER_NAME",
    "AtlasOpenClawPlugin",
    "OpenClawRecall",
    "OPENCLAW_PLUGIN_NAME",
    "OPENCLAW_PLUGIN_VERSION",
    "OPENCLAW_PLUGIN_TYPE",
    "openclaw_plugin",
]
