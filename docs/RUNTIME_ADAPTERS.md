# Hermes and OpenClaw integration: what is real today

Atlas previously overstated these integrations. The Python modules exposed
`put` / `store`, but their retrieval and deletion methods returned empty or
false values. They were adapter-shaped stubs, and the README called them
drop-in plugins even though both upstream plugin contracts had changed.

That is no longer the implementation state.

## Runnable proof without Neo4j or Docker

From the Atlas repository:

```bash
pip install -e .
PYTHONPATH=. python scripts/demo_runtime_adapters.py
```

The script creates an isolated SQLite trust store and proves:

- Hermes-shaped `put` -> `search` -> `get` -> `delete`;
- OpenClaw-shaped `store` -> `recall` -> `list_memories` -> `forget`;
- forgotten memories disappear from retrieval but remain auditable;
- no Neo4j connection or Docker process is started.

CI runs the same proof in
`tests/integration/test_runtime_adapter_demo.py` with `NEO4J_URI` deliberately
pointed at a dead port.

## The two capability tiers

### Portable memory tier — SQLite only

The portable tier is usable by Python hosts and integration wrappers today:

- trust-aware local storage;
- deterministic lexical retrieval;
- fetch and list operations;
- auditable forgetting;
- no API key, embedding model, Neo4j, or Docker requirement.

Portable `forget` is retrieval suppression, not AGM contraction. If a memory
has already been promoted into the canonical ledger and Neo4j graph, use the
graph adjudication/revision path to change that canonical state as well.

The shared MCP/HTTP surface exposes `memory.search`, `memory.get`,
`memory.list`, and `memory.forget`. Both adapter cores call those same tools,
so their behavior is not duplicated or mocked.

### Cognitive graph tier — Neo4j

Neo4j is required for the feature that makes Atlas different from ordinary
memory backends:

- typed belief and decision graphs;
- AGM revision and contraction;
- dependency and lineage walks;
- Ripple downstream reassessment;
- graph-aware contradiction detection.

Docker is the documented local setup, not the only possible deployment.
Neo4j Desktop, a native Neo4j service, or Aura can provide the same Bolt
endpoint.

## Native upstream packages

The modules `atlas_core.adapters.hermes` and `atlas_core.adapters.openclaw`
remain functional SDK-neutral Python cores. Native host packages now ship too:

- `integrations/hermes-atlas/` subclasses Hermes's current `MemoryProvider`
  and implements initialization, prefetch, nonblocking turn capture, tools,
  pre-compression, backup/config, and acknowledged shutdown.
- `integrations/openclaw-atlas/` is a TypeScript `kind: memory` package using
  OpenClaw's public plugin SDK and `registerMemoryCapability`. It registers
  `memory_search`, `memory_get`, `memory_store`, and `memory_forget`.

Dedicated CI installs each package into its pinned upstream host with Neo4j
pointed at a dead endpoint. The OpenClaw gate also installs the release tarball
through the real CLI and requires a loaded runtime, all four tools, and zero
diagnostics. Package-specific setup is in each integration's README.

## Integration choices today

1. Python runtimes can construct `AtlasHermesProvider.from_config(...)` or
   `AtlasOpenClawPlugin` and use the portable operations directly.
2. Any runtime can call the four `memory.*` tools through Atlas MCP or HTTP.
3. Hermes and OpenClaw users can install the native packages without requiring
   the Neo4j tier.
4. Teams that want Ripple and AGM behavior can point the same Atlas instance
   at Neo4j; the adapter-facing memory calls do not change.

The native acceptance standard is enforced in `.github/workflows/hermes-native.yml`
and `.github/workflows/openclaw-native.yml`.
