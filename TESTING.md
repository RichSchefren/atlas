# Testing Atlas

Five concrete things you can do to break Atlas. Pick whichever depth suits how much time you have. Every path ends in a structured GitHub issue template that auto-routes the finding to the right area of the codebase.

If anything goes red, file the issue **with the matching template** — the title prefix `[tester-finding]` is automatic from the template choice. Don't email me with traces; I want them in issues so they're searchable for the next tester.

---

## 5-minute path: smoke test (most testers should start here)

```bash
git clone https://github.com/RichSchefren/atlas && cd atlas
docker compose up -d                         # Neo4j 5.26 with APOC
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
PYTHONPATH=. pytest tests/ -v                # 318 passed expected
```

**If RED:** file an issue using the **"Tester report — smoke test"** template. Copy the failing pytest line. Include `python --version` and your OS.

**Most likely failure modes:**
- Neo4j didn't come up cleanly (check `docker compose ps`)
- Python <3.10 (Atlas uses `list[X]` / `X | None` syntax)
- Apple Silicon arm64 vs x86_64 wheel mismatch on a dependency

---

## 2-minute path: watch the loop close

After the 5-minute install above:

```bash
PYTHONPATH=. python scripts/demo_loop.py
```

You should see seven banners:

1. Plant the upstream belief
2. Plant the downstream belief
3. Fact change announcement
4. Ripple cascade — automatic reassessment
5. Adjudication queue — strategic conflict
6. Rich resolves — accept the reassessment
7. verify_chain — tamper detection

Final output: **"intact ✓ last_verified_sequence = 1"** + **"LOOP CLOSED"**.

**If anything diverges:** file the **"Tester report — loop demo"** template. Note which stage broke and paste the full output.

---

## 30-second path: run the benchmark

```bash
PYTHONPATH=. python scripts/run_bmb.py
```

Expected matrix (149 questions):

| System  | Overall  | Notes                                      |
|---------|----------|--------------------------------------------|
| Vanilla | 0.000    | floor; if non-zero, the harness is broken  |
| Graphiti| 0.711    | typed graph baseline                       |
| Atlas   | **1.000**| 149/149 perfect, all 7 categories          |
| Mem0    | SKIP     | unless `OPENAI_API_KEY` is set             |
| Letta   | SKIP     | unless `OPENAI_API_KEY` is set             |
| Memori  | SKIP     | unless `MEMORI_API_KEY` is set             |
| Kumiho  | SKIP     | (no public Python client yet)              |
| MemPalace| SKIP    | (not yet pinned)                           |

**If Atlas drops below 0.90** or **Vanilla scores non-zero** or **Graphiti collapses**, file the **"Tester report — BusinessMemBench"** template. CI gates merge at Atlas ≥ 0.90, so a regression below that is real news.

---

## 10-minute path: live ingest from your own data

Point Atlas at your actual capture stack. **Read-only against your data** — Atlas never writes to your vault or DB.

```bash
ATLAS_VAULT_ROOT=~/Documents/Obsidian \
  PYTHONPATH=. python scripts/first_real_run.py
```

Inspect what landed:

```bash
sqlite3 ~/.atlas/candidates.db \
  "SELECT lane, status, COUNT(*) FROM candidates GROUP BY lane, status"
```

**Sane results:** vault content goes to `atlas_vault` lane, all in `requires_approval` status (medium-risk default). Limitless transcripts go to `atlas_observational`. Total cycle <30 seconds for ~5K files.

**If candidates land in wrong lanes / get wrong krefs / cursor doesn't advance**, file the **"Tester report — live ingest"** template.

---

## 30-minute path: Claude Code adapter wire-level

The MCP stdio bridge is the most likely place to find bugs that don't show up in unit tests — it talks JSON-RPC over a real subprocess. Run the wire-level suite:

```bash
PYTHONPATH=. pytest tests/integration/test_claude_code_stdio.py -v
```

**OR** wire it into your actual Claude Code session. Edit `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "atlas": {
      "command": "python",
      "args": ["-m", "atlas_core.adapters.claude_code"],
      "env": {
        "PYTHONPATH": "/path/to/your/atlas/checkout",
        "ATLAS_NEO4J_URI": "bolt://localhost:7687",
        "ATLAS_NEO4J_USER": "neo4j",
        "ATLAS_NEO4J_PASSWORD": "atlasdev",
        "ATLAS_QUARANTINE_DB": "/Users/<you>/.atlas/candidates.db",
        "ATLAS_LEDGER_DB": "/Users/<you>/.atlas/ledger.db"
      }
    }
  }
}
```

Restart Claude Code. Type `/mcp` — you should see `atlas` listed with 8 tools. Try `Use the atlas tool to verify the chain.` Claude should call `ledger.verify_chain` and report `intact: true`.

**If Claude Code can't find the server, returns 0 tools, or any tool call fails**, file the **"Tester report — Claude Code MCP adapter"** template.

---

## What I'd love a tester to find

Honest priorities:

1. **AGM compliance regressions** on hardware I haven't tested (Linux x86_64, ARM Linux). The 49/49 passes on M3 Mac; if it goes red on a Ubuntu CI runner that's news. CI exercises this — green builds at https://github.com/RichSchefren/atlas/actions.
2. **Ingestion edge cases** — what happens with malformed YAML frontmatter? Empty Limitless files? Symlinked vault? Unicode in krefs?
3. **Resolver race conditions** — if you fire `adjudication.resolve` twice for the same proposal_id, what happens? (Should error, but I haven't proven it.)
4. **The bench score-shape** — does the matrix print correctly on a 80-column terminal? On Windows? On a Linux server with no UTF-8 locale?

---

## What I do NOT need a tester to find right now

- Style nits (we'll do those before 1.0)
- "What if you supported X?" feature ideas (open Discussions, not issues)
- "The README has a typo" (PRs welcome, but those don't block ship)
- Performance benchmarks beyond what's in `paper/` already (Phase 5 work)

---

## Reach me

GitHub issues are the channel. Email rich@strategicprofits.com only for security findings (see SECURITY.md).
