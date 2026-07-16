# Atlas Native Memory for Hermes Agent

This package is a native memory provider for the current Hermes Agent `MemoryProvider` lifecycle. It is not an adapter stub: completed turns are stored in SQLite, later turns automatically retrieve relevant memory, and Hermes receives working search/get/list/forget tools.

## What ships

- Current Hermes `agent.memory_provider.MemoryProvider` subclass
- Discovery from `$HERMES_HOME/plugins/atlas`
- Automatic current-query prefetch plus next-turn background warming
- Nonblocking turn capture with ordered background writes
- Profile and platform-user isolation, plus optional exact session filters
- Restart-persistent SQLite storage
- Search, get, list, audit-preserving forget, cognitive store, and dependency tools
- Managed localhost cognitive service for immutable revisions, dependency traversal,
  persisted Ripple reassessment proposals, and one authoritative semantics owner
- Session-switch, pre-compression, session-end, shutdown, config, and backup hooks
- No Neo4j, Docker, embeddings, third-party API key, or non-local network service

The native provider now includes Atlas's portable AGM/Ripple wedge through a
bundled, authenticated localhost sidecar. Explicitly stored facts and beliefs
receive immutable revision lineage, declared dependencies, automatic recall,
and persisted reassessment proposals when a caller marks a revision as
contradictory. The authoritative service—not Hermes-specific Python or SQLite
statements—owns confidence arithmetic, traversal, contradiction persistence,
routing, and idempotency. Neo4j remains optional for Atlas's broader graph tier.

## Install

From a clone of Atlas:

```bash
./integrations/hermes-atlas/install.sh
```

PowerShell:

```powershell
.\integrations\hermes-atlas\install.ps1
```

The installers copy the provider to `$HERMES_HOME/plugins/atlas` (default `~/.hermes/plugins/atlas`) and run:

```bash
hermes memory setup atlas
```

Use `--no-activate` (PowerShell: `-NoActivate`) to copy without changing the active provider. Hermes allows only one external memory provider at a time.

## Verify

```bash
hermes memory status
hermes doctor
```

Start Hermes, complete a turn containing a distinctive fact, exit cleanly, restart, and ask about that fact. Atlas also exposes:

- `atlas_memory_search`
- `atlas_memory_get`
- `atlas_memory_list`
- `atlas_memory_forget`
- `atlas_memory_store`
- `atlas_memory_depend`

`atlas_memory_store` accepts confidence and evidence age as integer parts per
million / whole days. The cognitive service computes exact integer-ppm results;
Hermes and SQLite transport and persist them without reinterpretation.
Create a fact or belief without `memory_id`; revise it by passing the stable ID
returned from creation. `revision_reason` is required with `memory_id` and is
rejected on create so it is never silently discarded. A
contradictory revision returns its committed cascade and proposals synchronously.
`atlas_memory_get` returns the cognitive state,
including current revision, lineage, dependencies, and proposals,
after restart.

By default Atlas derives a collision-resistant localhost port from the complete
Hermes profile/platform/user scope plus the resolved Hermes home, creates a
separate bearer token and database for that installation and scope, launches the
bundled stdlib service, and verifies the exact scope and service version before
every operation. The managed process is stopped on a clean Hermes shutdown and
re-launched against the same database on restart. Each launch exposes an
authenticated owner instance. Another client with the same installation, token,
scope, and service version attaches without ownership and cannot stop the healthy
shared process. If that process becomes unavailable, an attached client may
launch and own its replacement. A parent watchdog stops the sidecar if its owner
Hermes process exits without a clean shutdown. Different profiles or Hermes
installations do not attach merely because another Atlas service is running.
If an owner exits between health verification and an operation, the client
fails over and retries that request once on transport unavailability only.
Create, revise, dependency, and forget operations are replay-safe at the
authoritative service boundary.

Managed token/port state is published without a persistent lock: Atlas writes
and fsyncs a secure scope-specific temp file, then atomically hard-links it into
the previously absent final path. A crash before publication leaves only a
harmless complete temp; a crash after publication leaves a complete final file.
Fresh contender temps are never required for correctness or removed. Temps more
than one hour old are lazily removed on a later constructor pass, leaving zero
retained stale files and bytes for that scope after cleanup. The state directory
is mode `0700` and the final file is `0600` on POSIX systems.

For an externally managed local service, set `cognitive_url` and
`cognitive_expected_scope` through `hermes memory setup atlas`, and provide a
32-character-or-longer `ATLAS_COGNITIVE_TOKEN`. Atlas accepts only HTTP loopback
addresses and rejects scope or version mismatches. It never silently falls back
to a different service.

If the cognitive service is temporarily unavailable, legacy SQLite
search/get/list/prefetch results remain available. Tool responses mark
`degraded: true` and include `cognitive_error`; automatic recall includes the
same degraded-state notice instead of suppressing local memory.

Ripple traversal is deterministic. At a convergent node, the current service
selects one deterministic affected upstream path; it does not aggregate deltas
from multiple converging supports into a combined proposal.

## Storage and isolation

The default database is inside the active profile home:

```text
$HERMES_HOME/atlas/data/atlas-<profile>-<identity-hash>.db
$HERMES_HOME/atlas/data/cognitive-service-<scope-hash>.db
```

Both files deliberately use the exact `.db` suffix recognized by pinned Hermes.
`hermes backup` therefore snapshots each live WAL database through
`sqlite3.backup()` and excludes its transient `-wal` and `-shm` files. The
integration has not had a public release using the earlier development-only
`.sqlite3` names, so this first-release package does not add an unproven filename
migration path.

Rows are scoped by a SHA-256 digest of the exact profile identity, platform,
primary user ID, and alternate stable user ID, and record the exact Hermes
session ID. The readable filename includes a collision-resistant identity
suffix, so distinct host identifiers cannot collapse onto one scope. Search
and list span sessions by default for long-term recall; pass `session_id` to
filter exactly. Different Hermes profiles never share a default database.

Because default state lives under `$HERMES_HOME`, normal `hermes backup` captures
both databases and `backup_paths()` returns an empty list. If `data_dir` or
`ATLAS_HERMES_DATA_DIR` points outside the Hermes home, Atlas reports that
directory through `backup_paths()` for Hermes's external-path backup flow.

## Configuration

Run `hermes memory setup` to configure the fields exposed by the provider:

- `data_dir`: optional custom storage root
- `prefetch_limit`: automatic recall count, 1–20 (default 5)
- `capture_turns`: persist primary-agent completed turns (default true)
- `max_turn_chars`: per-turn storage cap (default 24,000)
- `cognitive_url`: optional explicitly managed HTTP loopback service URL
- `cognitive_expected_scope`: required exact profile scope with `cognitive_url`
- `cognitive_token`: secret bearer token read from `ATLAS_COGNITIVE_TOKEN`

Configuration is written to `$HERMES_HOME/atlas/config.json`. `ATLAS_HERMES_DATA_DIR` overrides `data_dir` for deployment automation.

Subagents, cron runs, and flush contexts can still read memory, but Atlas disables automatic turn capture when Hermes initializes the provider with a non-primary `agent_context`.

## Uninstall

Disable the provider first, then remove only its plugin directory:

```bash
hermes memory off
rm -rf "${HERMES_HOME:-$HOME/.hermes}/plugins/atlas"
```

Memory data remains under `$HERMES_HOME/atlas/data` so uninstalling code does not silently destroy user history.
