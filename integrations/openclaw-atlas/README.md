# Atlas cognitive memory for OpenClaw

`@atlas-memory/openclaw` is a native OpenClaw `kind: memory` plugin with seven
working tools. It now uses Atlas's bundled cognitive service for new memories:
immutable revisions, confidence changes, dependencies, Ripple reassessment,
audit lineage, retrieval, and forget are executable inside OpenClaw. The prior
profile-local SQLite store remains readable only as a compatibility source for
memories created by package 0.1.0.

Atlas requires no Neo4j, Docker, embedding provider, or API key. The managed
sidecar binds to loopback, requires a private bearer token, fixes one
agent/session scope at launch, and uses Python's standard library plus SQLite.

## Requirements

- OpenClaw 2026.7.2 or newer
- Node.js 22.22.3, 24.15+, or 25.9+
- Python 3.10+

The protected host fixture is OpenClaw commit
`d830fda0893bb0a716f015478269d344eba7a6f7`.

## Install

```bash
shasum -a 256 -c CHECKSUMS.sha256
openclaw plugins install ./atlas-memory-openclaw-0.2.0.tgz
openclaw config set plugins.slots.memory atlas-memory
openclaw plugins inspect atlas-memory --runtime --json
```

Restart the gateway after installation or configuration changes. OpenClaw
treats plugin metadata as process-stable.

Default configuration:

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
          // pythonCommand: "/absolute/path/to/python3",
        },
      },
    },
  },
}
```

Set `pythonCommand` only when `python3` is not on PATH (Windows defaults to
`python`).

## Tools

- `memory_search` searches cognitive memory plus read-only 0.1.0 legacy data.
- `memory_get` returns current content, confidence, dependencies, and proposal
  metadata when the id is cognitive.
- `memory_store` creates a fact or belief with confidence and an immutable
  initial revision.
- `memory_revise` appends a revision, changes confidence, and automatically
  runs Ripple reassessment.
- `memory_depend` declares a weighted support dependency.
- `memory_audit` returns full lineage, tags, and audit events.
- `memory_forget` deprecates cognitive content while retaining audit lineage;
  any matching legacy record is redacted.

Retrieved text is explicitly labeled untrusted historical data. Prompt-like
instructions are rejected at storage. Auto-recall escapes and caps content.
Auto-capture is off by default; if enabled, also grant OpenClaw's explicit
conversation-history permission:

```json5
hooks: { allowConversationAccess: true }
```

## Isolation and lifecycle

Each OpenClaw profile stores Atlas state under its own plugin state directory.
The configured scope creates one managed service per agent or per session.
Stable loopback ports and token files allow concurrent callers to attach to
one exact-scope owner without crossing profiles. The normal gateway registers
a plugin service and stops owned sidecars during shutdown. OpenClaw's
standalone MCP tool bridge does not start plugin services, so each tool also
performs a safe lazy attach/start on first use.

## Verification

```bash
npm ci --omit=optional
ln -s /path/to/pinned/openclaw node_modules/openclaw
npm test
npm pack
```

Protected CI uses exact Node 22.22.3 on Linux and Windows, builds the real
pinned OpenClaw public SDK, verifies reproducible tarball bytes, installs only
the tarball through the real CLI, and invokes all seven tools through the real
host MCP bridge. The host proof creates two memories, declares a dependency,
revises its support, requires a nonempty Ripple proposal set, audits, searches,
retrieves the revised value, and forgets a record.
