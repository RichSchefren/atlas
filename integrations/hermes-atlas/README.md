# Atlas Native Memory for Hermes Agent

This package is a native memory provider for the current Hermes Agent `MemoryProvider` lifecycle. It is not an adapter stub: completed turns are stored in SQLite, later turns automatically retrieve relevant memory, and Hermes receives working search/get/list/forget tools.

## What ships

- Current Hermes `agent.memory_provider.MemoryProvider` subclass
- Discovery from `$HERMES_HOME/plugins/atlas`
- Automatic current-query prefetch plus next-turn background warming
- Nonblocking turn capture with ordered background writes
- Profile and platform-user isolation, plus optional exact session filters
- Restart-persistent SQLite storage
- Search, get, list, and audit-preserving forget tools
- Session-switch, pre-compression, session-end, shutdown, config, and backup hooks
- No Neo4j, Docker, embeddings, API key, or network service

This portable tier stores retrievable memory. Atlas's optional graph lineage, AGM canonical revision, and Ripple reassessment remain separate higher-tier capabilities; the native Hermes provider does not pretend that forgetting a retrieved item rewrites already-promoted graph state.

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

## Storage and isolation

The default database is inside the active profile home:

```text
$HERMES_HOME/atlas/data/atlas-<profile>.sqlite3
```

Rows are also scoped by `<profile>:<platform-user>` and record the exact Hermes session ID. Search and list span sessions by default for long-term recall; pass `session_id` to filter exactly. Different Hermes profiles never share a default database.

Because default state lives under `$HERMES_HOME`, normal `hermes backup` already captures it and `backup_paths()` correctly returns an empty list. If `data_dir` or `ATLAS_HERMES_DATA_DIR` points outside the Hermes home, Atlas reports that directory through `backup_paths()` for Hermes's external-path backup flow.

## Configuration

Run `hermes memory setup` to configure the fields exposed by the provider:

- `data_dir`: optional custom storage root
- `prefetch_limit`: automatic recall count, 1–20 (default 5)
- `capture_turns`: persist primary-agent completed turns (default true)
- `max_turn_chars`: per-turn storage cap (default 24,000)

Configuration is written to `$HERMES_HOME/atlas/config.json`. `ATLAS_HERMES_DATA_DIR` overrides `data_dir` for deployment automation.

Subagents, cron runs, and flush contexts can still read memory, but Atlas disables automatic turn capture when Hermes initializes the provider with a non-primary `agent_context`.

## Uninstall

Disable the provider first, then remove only its plugin directory:

```bash
hermes memory off
rm -rf "${HERMES_HOME:-$HOME/.hermes}/plugins/atlas"
```

Memory data remains under `$HERMES_HOME/atlas/data` so uninstalling code does not silently destroy user history.
