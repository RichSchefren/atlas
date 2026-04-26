"""Atlas adapters — drop-in plugins for agent runtimes.

Each adapter wraps AtlasMCPServer in the contract a target runtime expects:

  - claude_code  → JSON-RPC 2.0 over stdio (MCP spec)
  - hermes       → MemoryProvider protocol (NousResearch hermes-agent)
  - openclaw     → Memory plugin (OpenClawIO/openclaw)

All three share the same Atlas backend, so AGM revision and Ripple
cascade behavior are identical across runtimes — Atlas is the substrate,
runtimes are the consumer.

Spec: 09 - Agent Runtime Memory Competitive Landscape.md
"""

from atlas_core.adapters.hermes import (
    PROVIDER_NAME as HERMES_PROVIDER_NAME,
    AtlasHermesProvider,
    HermesMemoryItem,
)
from atlas_core.adapters.openclaw import (
    PLUGIN_NAME as OPENCLAW_PLUGIN_NAME,
    PLUGIN_TYPE as OPENCLAW_PLUGIN_TYPE,
    PLUGIN_VERSION as OPENCLAW_PLUGIN_VERSION,
    AtlasOpenClawPlugin,
    Recall as OpenClawRecall,
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
