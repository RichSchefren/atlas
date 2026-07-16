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

## Upstream compatibility boundary

The modules `atlas_core.adapters.hermes` and
`atlas_core.adapters.openclaw` are functional SDK-neutral adapter cores. They
are not currently installable native plugins for the latest upstream runtimes.

Current Hermes Agent expects a Python plugin that subclasses
`agent.memory_provider.MemoryProvider` and implements lifecycle hooks including
`initialize`, `prefetch`, `sync_turn`, tool schemas, tool dispatch, and
`shutdown` ([upstream contract](https://github.com/NousResearch/hermes-agent/blob/main/agent/memory_provider.py)). Atlas's older four-method class is the working persistence and
retrieval core a native wrapper can call, but it is not that wrapper.

Current OpenClaw expects a TypeScript package built on its plugin SDK, with a
memory manifest and `registerMemoryCapability`. A Python `plugin(config)`
factory cannot be loaded directly by current OpenClaw. Atlas's Python class is
the tested storage/retrieval core, not the final npm package. See OpenClaw's
[plugin SDK overview](https://docs.openclaw.ai/plugins/sdk-overview).

Until those native packages are built and tested inside the actual upstream
processes, Atlas will not label them drop-in integrations. Native packaging is
tracked in [#27 for Hermes](https://github.com/RichSchefren/atlas/issues/27)
and [#26 for OpenClaw](https://github.com/RichSchefren/atlas/issues/26).

## Integration choices today

1. Python runtimes can construct `AtlasHermesProvider.from_config(...)` or
   `AtlasOpenClawPlugin` and use the portable operations directly.
2. Any runtime can call the four `memory.*` tools through Atlas MCP or HTTP.
3. Hermes and OpenClaw plugin authors can wrap the portable surface without
   requiring the Neo4j tier.
4. Teams that want Ripple and AGM behavior can point the same Atlas instance
   at Neo4j; the adapter-facing memory calls do not change.

The acceptance standard for future native packages is a real upstream-process
round trip: capture a turn, retrieve it in a later turn, fetch it by ID, forget
it, and prove it no longer appears—all in both Hermes Agent and OpenClaw CI.
