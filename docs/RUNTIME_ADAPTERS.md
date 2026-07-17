# Runtime integrations: what is real today

Atlas once described adapter-shaped stubs as integrations. The current release
has executable, separately installable surfaces for Hermes, OpenClaw, and
GBrain, with protected upstream-host evidence.

## Shared cognitive boundary

One Python service in `integrations/cognitive-service/` owns cognitive
semantics. It stores immutable fact/belief revisions, confidence, dependencies,
audit events, and persisted Ripple reassessment proposals. Host packages are
thin authenticated transport/lifecycle clients; cognition is not reimplemented
in TypeScript, host plugins, or SQL.

The service:

- binds only to loopback and requires a private bearer token on every route;
- fixes one profile/agent/session/brain-source scope at launch;
- uses Python's standard library and SQLite;
- needs no Neo4j, Docker, embedding provider, or API key;
- passes the 49 AGM scenario ids, canonical dependency cascade, restart,
  idempotency, authentication, scope isolation, and 10k-item performance gates.

Neo4j remains optional for Atlas's broader typed property graph, canonical
ledger projection, Cypher MCP tools, and adjudication workflows.

## Hermes

`integrations/hermes-atlas/` subclasses the current Hermes `MemoryProvider`.
It implements host lifecycle, recall, capture, backup, managed service startup
and shutdown, cognitive create/revise, dependencies, audit, and forget. Linux
and Windows CI load it through pinned Hermes commit
`b5bd0ef38b538627a0e5d2cbe5d3eef2c38ec792`.

## OpenClaw

`integrations/openclaw-atlas/` is a TypeScript `kind: memory` plugin using only
OpenClaw's public plugin SDK. Package 0.2.0 exposes:

- `memory_search`, `memory_get`, and `memory_store`;
- `memory_revise`, which appends lineage and runs Ripple;
- `memory_depend`, which creates weighted support edges;
- `memory_audit` and `memory_forget`.

New records live in the cognitive service. The 0.1.0 profile-local SQLite store
is retained as a read/redact compatibility source, not as a second cognitive
owner. The normal gateway owns the service pool; standalone OpenClaw tool
bridges safely start/attach on first call.

Protected Linux and Windows jobs build pinned OpenClaw commit
`d830fda0893bb0a716f015478269d344eba7a6f7`, install only the checksum-pinned
tarball, load it through the real CLI, and invoke all seven tools through the
real host bridge. Passing requires a dependency and nonempty Ripple proposal.

## GBrain

GBrain is a memory system and MCP server, not an agent host. Its plugin-v1
contract can add definitions but cannot declare tools, so Atlas does not claim
a fictional native tool plugin. `integrations/gbrain-atlas/` is an independent
CLI bridge over GBrain's public `put_page`, `get_page`, `search`, and
`get_brain_identity` MCP operations.

GBrain remains the markdown/page system of record. Atlas hashes brain id,
source id, and slug into a stable cognitive identity, then adds confidence,
lineage, dependencies, audit, and Ripple. Brain and source tenancy axes remain
separate, remote MCP trust rules remain GBrain-owned, and cross-source Atlas
dependencies fail closed.

Protected CI pins GBrain commit
`26d2f8abfc0e7c6fead5ea89b6494ce8c3cf737f` (0.42.61.0), initializes its
zero-server PGLite backend on Ubuntu, installs only the Atlas tarball, and
drives the real `gbrain serve` lifecycle through create, dependency, revision,
Ripple, get, audit, search, and status. Windows runs the package/service bridge
test. The pinned upstream marks PGLite incompatible on macOS 26 Apple Silicon;
that platform uses GBrain's native Postgres option, while Atlas itself still
adds no server dependency.

## SDK-neutral portable cores

`atlas_core.adapters.hermes` and `atlas_core.adapters.openclaw` remain
functional Python-shaped cores for custom runtimes. Run:

```bash
PYTHONPATH=. python scripts/demo_runtime_adapters.py
```

That proof covers local SQLite store/search/get/list/forget with a dead Neo4j
endpoint. It is useful for custom integration work, but it is not substituted
for the native host proofs above.

## Acceptance files

- `.github/workflows/cognitive-service.yml`
- `.github/workflows/hermes-native.yml`
- `.github/workflows/openclaw-native.yml`
- `.github/workflows/gbrain-native.yml`

Package-specific install and verification commands are in each integration's
README.
