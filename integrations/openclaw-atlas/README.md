# Atlas Memory for OpenClaw

This package is the native current-OpenClaw integration for Atlas portable memory. It is not a stub: it registers four working tools, stores memory in OpenClaw's profile-local SQLite state database, retrieves by deterministic lexical ranking, injects bounded recall, and redacts forgotten content while preserving an audit tombstone.

It does not require Neo4j, Docker, Python, an embedding provider, or a background daemon.

## Install

Install a release tarball from this directory:

```bash
openclaw plugins install ./atlas-memory-openclaw-0.1.0.tgz
openclaw plugins inspect atlas-memory --runtime --json
```

Verify the release artifact first with `shasum -a 256 -c CHECKSUMS.sha256`.

To build from source before OpenClaw 2026.7.2 is published to npm, install the local development dependencies and link an exact OpenClaw source checkout as the optional peer:

```bash
npm install --omit=optional
ln -s /path/to/openclaw node_modules/openclaw
npm test
npm pack
```

The verified host fixture is commit `d830fda0893bb0a716f015478269d344eba7a6f7` running OpenClaw 2026.7.2. Do not replace the peer link with copied SDK declarations; the build is intended to typecheck against the real public SDK export.

Select it as the memory plugin in the active profile:

```json5
{
  plugins: {
    slots: { memory: "atlas-memory" },
    entries: {
      "atlas-memory": {
        enabled: true,
        config: {
          scope: "agent",
          autoRecall: true,
          autoCapture: false,
          recallLimit: 3,
          captureMaxChars: 800,
        },
      },
    },
  },
}
```

Restart the gateway after installation or configuration changes because OpenClaw treats plugin metadata as process-stable.

## Tools

- `memory_search({ query, limit? })` searches active memories in the current scope. Results are labeled untrusted historical data.
- `memory_get({ memoryId })` fetches one active memory by exact id in the current scope.
- `memory_store({ text, tags? })` stores a durable fact, preference, or decision. Equivalent active text is idempotent. Prompt-like instructions are rejected.
- `memory_forget({ memoryId, reason? })` immediately removes memory content from retrieval and redacts the stored text. Atlas retains only the id, scope, timestamps, reason, and SHA-256 content hash as an audit tombstone.

`memory_forget` changes this portable plugin store only. It does not rewrite an external Atlas Neo4j graph or an independently exported ledger.

## Recall and capture safety

Auto-recall is on by default. It returns at most three matches and injects them inside an `atlas_memory_context` envelope that explicitly identifies them as untrusted historical data. Memory text is escaped and capped before prompt injection.

Auto-capture is off by default and must be enabled deliberately. When enabled, it examines user messages only, captures at most two bounded items after a successful turn, requires an explicit preference/fact/decision signal, rejects known prompt-instruction patterns, and deduplicates normalized text.

OpenClaw protects conversation history from third-party hooks. If you enable `autoCapture`, also grant the plugin that explicit access in its entry (next to `enabled` and `config`):

```json5
hooks: { allowConversationAccess: true }
```

Leave that permission absent when `autoCapture` is false; Atlas does not register the conversation-history hook in the default mode.

## Isolation and persistence

- **Profile:** OpenClaw places its shared SQLite database under the active profile's state directory. Different `--profile` or `OPENCLAW_STATE_DIR` values therefore use different databases.
- **Agent:** every record carries the host-provided agent id; tools and hooks retrieve only the current agent's records.
- **Session:** set `scope: "session"` to additionally bind every record to the current session key/id. The default `agent` scope supports long-term recall across conversations for one agent.
- **Restart:** state is committed by OpenClaw's SQLite plugin-state owner and survives plugin/gateway process restart.

The store rejects new entries at 10,000 records rather than silently evicting durable memory.

## Architecture boundary

The plugin imports only `openclaw/plugin-sdk/plugin-entry`. It calls `registerMemoryCapability`, registers tool factories and modern lifecycle hooks, and uses Node's built-in `node:sqlite` driver. The database lives at `plugins/atlas-memory/atlas.sqlite` under the active OpenClaw state directory. Atlas owns record semantics, schema, transactions, and shutdown cleanup; OpenClaw supplies the profile environment and lifecycle callback.
