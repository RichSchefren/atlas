# Atlas cognitive service

This is Atlas's authoritative portable AGM/Ripple service. It is a local
sidecar, not an embedded adapter and not a remote dependency. One Python
implementation owns revision, contraction, dependency traversal, Ripple
confidence updates, contradiction routing, and idempotency. SQLite stores the
state; SQL does not contain cognitive branching.

The service is deliberately explicit about its boundary:

- binds only to `127.0.0.1` or `::1`;
- requires a bearer token on every route, including health;
- is fixed to one profile scope at launch;
- rejects a caller-supplied `scope_id`;
- requires idempotency keys for create, revise, and cascade;
- persists immutable revisions, dependencies, audit events, and proposals;
- needs no Neo4j, Docker, embedding model, or API key.

## Run directly

```bash
export ATLAS_COGNITIVE_TOKEN="replace-with-at-least-32-random-characters"
python integrations/cognitive-service/server.py \
  --db ~/.atlas/cognitive.sqlite3 \
  --scope my-profile \
  --port 8741
```

Then call the versioned API with `Authorization: Bearer …`. The complete route
and idempotency contract is in `contract.json`.

Native Hermes users do not normally start this command themselves. The Atlas
Hermes provider bundles the service, derives a stable per-install/profile
loopback port, creates a private token file, verifies the exact scope and
service version, and starts/stops the sidecar with the provider lifecycle.

## Verification

```bash
python -m pytest -q tests/service
python tests/service/performance_service_gate.py --iterations 20
```

The black-box tests communicate only through authenticated HTTP. They cover
the 49 AGM scenario IDs, the canonical A-to-B Ripple cascade, Unicode scalar
ordering, restart persistence, idempotency conflicts, wrong-token rejection,
and launch-fixed scope. The performance gate uses 10,000 items, 20,000
dependency edges, and 9,999 returned and persisted proposals; p95 must remain
below two seconds.

OpenClaw does not claim this cognitive service yet. Its existing native Atlas
package remains a real retrieval integration until a thin client passes this
same corpus inside the pinned OpenClaw host.
