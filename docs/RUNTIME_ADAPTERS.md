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

### Portable cognitive service — Hermes today

The native Hermes package also ships a managed, profile-scoped localhost
service. It stores facts and beliefs, immutable revisions, `depends_on` edges,
lineage, audit events, and persisted Ripple reassessment proposals without
Neo4j or Docker. The service owns AGM/Ripple semantics once; Hermes is an
authenticated HTTP client and does not reimplement the formula or graph walk.

This is a real but deliberately bounded cognitive wedge:

- `atlas_memory_store` creates or revises a fact/belief idempotently;
- `atlas_memory_depend` records a dependency;
- a contradictory revision persists downstream proposals without mutating the
  dependent belief;
- cognitive records participate in automatic recall, search, list, get,
  audit-preserving forget, backup, and restart;
- one managed service is fixed to one Hermes profile/platform/user scope.

The black-box service suite exercises the public authenticated HTTP boundary,
including 49 AGM scenario IDs and the canonical A-to-B Ripple example. The
10k-item/20k-edge gate persists 9,999 proposals below the two-second p95
threshold. See `integrations/cognitive-service/` and
`.github/workflows/cognitive-service.yml`.

OpenClaw does **not** claim this cognitive tier yet. Its native package remains
the working portable retrieval package until a thin service client passes the
same host and conformance gates.

### Full property-graph tier — Neo4j

Neo4j remains the broader Atlas graph deployment for the typed ontology,
canonical ledger projection, graph adjudication workflows, and existing
Cypher-backed MCP tools. Docker is the documented local setup, not the only
deployment: Neo4j Desktop, a native service, or Aura can provide the Bolt
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
3. Hermes and OpenClaw users can install working native retrieval packages
   without Neo4j.
4. Hermes users can use the bundled managed cognitive service for the bounded
   AGM/Ripple wedge without Neo4j or Docker.
5. OpenClaw remains retrieval-only until its service client passes the same
   corpus; teams needing the broader graph/ledger/adjudication stack use the
   Neo4j tier.

The native and service acceptance standards are enforced in
`.github/workflows/hermes-native.yml`,
`.github/workflows/openclaw-native.yml`, and
`.github/workflows/cognitive-service.yml`.
