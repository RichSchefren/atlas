# Install modes

Atlas is one codebase with three good ways to install it. Pick the one that
matches *why* you want to run it; each mode pulls in just what that path
needs and skips the rest.

| Mode | Who it's for | Time to first running loop | Cost |
|---|---|---|---|
| **Researcher / dev** | You're reading the source, running benchmarks, contributing PRs | ~5 min | $0 |
| **Obsidian power-user** | You have a vault and want Atlas watching it for contradictions | ~10 min | $0–$1/day in API calls if you turn on LLM extraction |
| **Agent-runtime integration** | You're building on Hermes / OpenClaw / Claude Code and want a memory backend with belief revision | ~10 min | $0 |

Each section is self-contained — you should not need to read the others to
get going.

---

## Mode 1 — Researcher / dev

You want to read the source, run the benchmarks, reproduce the AGM
compliance suite, file PRs, or extend the algorithm. This is the same path
the test suite takes; if `make test` passes for you, you're done.

```bash
git clone https://github.com/RichSchefren/atlas && cd atlas
make setup        # creates .venv, installs -e .[dev], adds ruff
make neo4j        # starts the Neo4j 5.26 container with APOC
make doctor       # confirms 9/9 environment checks pass
make test         # 461 tests, ~12 seconds
```

What you get:
- All deterministic code paths (no LLM calls, no API keys required).
- The full Ripple cascade, AGM operators, trust quarantine, hash-chained
  ledger, and the 13 MCP tools.
- The 49-scenario AGM compliance suite (`make bench-agm`).
- The BusinessMemBench head-to-head matrix
  (`make bench-bmb` — runs the three measurable adapters; the five that
  need API keys are honestly skipped, not faked).
- Both demos: `make demo` (synthetic loop) + `make demo-messy` (real-shape
  vault note + transcript).

What you skip:
- LLM-driven extraction (deterministic regex / frontmatter only).
- Sentence-transformer embeddings (Atlas reads the user's existing
  vault-search daemon when one exists; otherwise retrieval is graph-only).
- Mem0 / Letta benchmark clients (Atlas vs. Graphiti vs. Vanilla still
  runs; the other rows show as `skipped`).

Where to look first if you're trying to learn the codebase:
- `atlas_core/ripple/engine.py` — the orchestrator
- `atlas_core/revision/agm.py` — the AGM operators
- `tests/integration/test_agm_compliance.py` — the 49-scenario proof
- `docs/PROPOSAL_VS_MUTATION.md` — what each method is allowed to do

---

## Mode 2 — Obsidian power-user

You have an Obsidian vault (or any folder of markdown). You want Atlas to
watch it, extract pricing / decisions / dependencies as they appear, and
surface contradictions when something downstream becomes suspect.

```bash
git clone https://github.com/RichSchefren/atlas && cd atlas
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[llm]    # adds the Anthropic SDK for LLM extraction
make neo4j               # starts Neo4j 5.26 with APOC
make doctor              # confirms environment is ready
```

Tell Atlas where your vault is:

```bash
export ATLAS_VAULT_DIR="$HOME/Obsidian/MyVault"
export ANTHROPIC_API_KEY="sk-ant-..."   # for LLM extraction; ~$0.50/day light usage
```

Run the full pipeline once to seed (the daemon module runs one ingestion cycle per invocation; loop it with `cron` or a shell `while`/`sleep` for continuous capture):

```bash
PYTHONPATH=. python -m atlas_core.daemon.cycle
```

This walks the vault, quarantines new claims, promotes corroborated ones to
the ledger, and runs Ripple on each promotion. The adjudication queue
appears as markdown files under `~/.atlas/adjudication/` — open that folder
in Obsidian alongside your main vault, and resolved entries archive to
`~/.atlas/adjudication/archive/`.

What you get:
- LLM-driven extraction from free-text notes (uses Claude via the
  Anthropic SDK pulled in by `[llm]`).
- Real propagation against your own beliefs — not synthetic graphs.
- The Obsidian adjudication queue rendered as markdown you can grep,
  diff, and resolve in your editor of choice.

What you skip:
- Continuous capture daemons (Limitless, Fireflies, Screenpipe, Claude
  Code logs, iMessage). Those exist as extractors in
  `atlas_core/ingestion/`, but enabling them needs platform-specific
  setup beyond this doc — see `atlas_core/ingestion/<source>.py` for the
  per-source notes.
- Sentence-transformer embeddings. If you have the
  vault-search daemon running, Atlas's retrieval delegates to it; if not,
  you'll see graph-only retrieval which is enough for the propagation
  loop but weaker for fuzzy semantic queries.

To stop watching: `pkill -f "atlas_core.daemon.cycle"` (the daemon is a
plain Python process, no system services to uninstall).

---

## Mode 3 — Agent-runtime integration

You're building on Hermes, OpenClaw, Claude Code, or any MCP-speaking
client, and you want Atlas as the memory backend that handles
belief-revision under the hood.

```bash
git clone https://github.com/RichSchefren/atlas && cd atlas
python3 -m venv .venv && source .venv/bin/activate
pip install -e .         # core only — no LLM, no embeddings
make neo4j
make doctor
```

Pick the adapter for your runtime:

### Claude Code (MCP, stdio)

Add Atlas to `~/.claude/.mcp.json` (the canonical Claude Code MCP config — see the comment block in `atlas_core/adapters/claude_code.py` for the authoritative example):

```json
{
  "mcpServers": {
    "atlas": {
      "command": "python",
      "args": ["-m", "atlas_core.adapters.claude_code"],
      "env": {
        "ATLAS_NEO4J_URI": "bolt://localhost:7687",
        "ATLAS_NEO4J_USER": "neo4j",
        "ATLAS_NEO4J_PASSWORD": "atlasdev",
        "ATLAS_QUARANTINE_DB": "${HOME}/.atlas/candidates.db",
        "ATLAS_LEDGER_DB": "${HOME}/.atlas/ledger.db"
      }
    }
  }
}
```

Restart Claude Code; Atlas's tools appear in the MCP tool list.

Atlas exposes the 13 MCP tools (`ripple.analyze_impact`,
`ripple.reassess`, `ripple.detect_contradictions`, `adjudication.queue`,
`adjudication.resolve`, `quarantine.upsert`, `quarantine.list_pending`,
`ledger.verify_chain`, `working_memory.assemble`, `lineage.walk`,
`sharing.grant`, `sharing.revoke`, `sharing.list_grants`). Read-only vs
mutation classification is in [`docs/PROPOSAL_VS_MUTATION.md`](PROPOSAL_VS_MUTATION.md).

### Hermes

```python
# In your Hermes agent config:
from atlas_core.adapters.hermes import AtlasHermesProvider

agent = Hermes(
    memory_provider=AtlasHermesProvider(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="atlasdev",
    ),
    ...
)
```

Atlas registers as the 9th MemoryProvider in the Hermes ecosystem and is
the only one that ships AGM-compliant revision.

### OpenClaw

```python
# Programmatic install — point your OpenClaw runtime at the plugin factory:
from atlas_core.adapters.openclaw import plugin as atlas_plugin

atlas = atlas_plugin({
    "neo4j_uri": "bolt://localhost:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "atlasdev",
})  # returns AtlasOpenClawPlugin
```

Or, if your OpenClaw build supports declarative manifests:

```yaml
plugins:
  - name: atlas-memory
    type: memory
    module: atlas_core.adapters.openclaw
    factory: plugin
```

What you get:
- The full Ripple cascade behind whatever interface your runtime
  expects.
- Read-only tools (analyze_impact, reassess, detect_contradictions,
  list_pending, verify_chain, assemble, lineage_walk, list_grants) that
  your agent can call freely without confirm-gating.
- Mutation tools (`adjudication.resolve`, `quarantine.upsert`,
  `sharing.{grant,revoke}`) that you should wire to a confirm step in
  your runtime — these are the methods that actually change Atlas's
  state.

What you skip:
- The Obsidian-style markdown adjudication queue (it still works, but
  most agent runtimes prefer the gRPC / MCP tool surface for
  resolution).
- Domain-specific extraction wired to your team's transcripts (build
  your own ingestion pipeline above the `quarantine.upsert` MCP tool —
  that's the supported integration seam).

---

## Switching modes

The modes are not exclusive. Researcher → Obsidian: just `pip install
.[llm]` and set the env vars. Obsidian → Agent-runtime: install the
adapter and point your runtime at the same Neo4j instance. The data dir
(`~/.atlas/`) and the Neo4j namespace are shared across modes by default,
so you can run the synthetic demo, then start watching your vault, then
plug Claude Code in — all against the same belief graph.

If you want isolation per mode (different Neo4j databases, different
data dirs), set `NEO4J_URI` and the `--data-dir` flag on
`atlas_core.daemon.cycle`. The default is shared because that's what
most users want; isolation is opt-in.

---

## What if I'm none of these?

You probably want **researcher / dev** mode first — it's the cheapest
($0, ~5 min, zero ongoing cost) and lets you run the demos to decide
whether Atlas matches what you're trying to build. The other two modes
require commitment that's only worth making once you've seen the loop
close.
