# Atlas

> **Open-source local-first cognitive memory — alpha.** Implements AGM-compliant belief revision on a property graph. Adds a propagation engine — Ripple — that recomputes downstream beliefs when an upstream fact changes. Runs entirely on your laptop.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://github.com/RichSchefren/atlas/actions/workflows/test.yml/badge.svg)](https://github.com/RichSchefren/atlas/actions/workflows/test.yml)
[![AGM Compliance](https://img.shields.io/badge/AGM-49%2F49%20at%20100%25-brightgreen.svg)](docs/AGM_COMPLIANCE.md)
[![Status: alpha](https://img.shields.io/badge/Status-alpha-orange.svg)]()

> **Alpha:** the propagation loop works end-to-end (`./demo.sh` proves it in 12 seconds). Ingestion and entity resolution on truly unstructured text are still maturing — see `atlas_core/ingestion/` for the prompts we're iterating on.

---

## See it work in 12 seconds

```bash
git clone https://github.com/RichSchefren/atlas && cd atlas
docker compose up -d
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
./demo.sh
```

The `./demo.sh` command runs the entire loop end-to-end, visibly:

1. Plants a tiny graph (3 nodes, 2 `Depends_On` edges)
2. Changes a fact (Origins coffee price: $89 → $129)
3. Calls `RippleEngine.propagate()` — the real orchestrator
4. Shows reassessment proposals, contradictions, and routing decisions
5. Resolves one through `adjudication.resolve()` (real AGM revise)
6. Verifies the SHA-256 hash chain

Every line is real Neo4j + real ledger. No mocks. ~6s on subsequent runs. **This is the front door — if it doesn't impress, nothing else will.**

### What you should see

The last lines of `./demo.sh` should look like this — if they don't, file an issue:

```text
[3/6] Triggering Ripple cascade ...
        impacted nodes:               1
        reassessment proposals:       1
        contradictions:               0

[4/6] Resolving via AGM revise() ...
        belief.confidence_score:      0.88 -> 0.77

[5/6] Verifying ledger ...
        chain intact:                 True
        last_verified_sequence:       1   (the 1 fact promoted to ledger this run)

[6/6] LOOP CLOSED.
```

`last_verified_sequence: 1` looks small because the demo plants exactly one promotion-eligible fact and verifies the chain holds with one entry — every later run extends the chain and the number grows. The point is the chain *intact*, not the count.

### What Atlas is not

To save you time:

- **Not a chatbot memory UI.** Atlas is a graph + an engine. The "UI" is whatever your agent runtime (Claude Code, Hermes, OpenClaw, your own MCP client) exposes. The Obsidian adjudication queue is markdown, not a chat interface.
- **Not just vector search.** There's an embedding-aware retrieval layer, but Atlas's primary index is the typed `Depends_On` graph. Vector-only systems can retrieve old context; Atlas reassesses what depended on it. ([Worked example with stale-belief failure mode →](docs/WHY_VECTOR_IS_NOT_ENOUGH.md))
- **Not yet a Letta replacement.** Atlas does not run agent loops. It plugs into agent runtimes as a memory backend. If you want an agent stack with memory built in, Letta or Hermes is the right answer; Atlas slots underneath.
- **Not yet automatic free-text understanding at scale.** The ingestion pipeline works on real Limitless / Fireflies / Claude transcripts, but extraction quality on truly unstructured text is uneven and improving — see `atlas_core/ingestion/extractors/` for the prompt set we're iterating on.

### Who Atlas is for, today

The strongest early users are:

- **Agent / tool builders** who need a memory backend with belief-revision semantics (MCP server, Hermes plugin, OpenClaw plugin all ship in `atlas_core/adapters/`).
- **Power users with Obsidian / transcripts / vaults** who want their meetings + screen + chat captures cross-checked for emergent contradictions.
- **Local-first AI builders** who can't or won't ship user data to a cloud memory service.
- **Researchers** working on belief revision, AGM compliance, or non-monotonic reasoning who want a reproducible, instrumented baseline.

Three concrete shapes the loop solves:

1. **Pricing change invalidates positioning.** A program's price changes from $89 to $129. Every "value claim" belief that quoted $89 gets a reassessment proposal — you don't discover the gap mid-call.
2. **Partner / person status change.** A team member changes role or leaves. Every Decision and Commitment that depended on their owning a deliverable surfaces in the adjudication queue with a confidence drop, not just a "stale" warning.
3. **Deadline slips.** A milestone moves three weeks. Every Project belief that downstream-depended on the old date (resourcing assumptions, risk score, dependent commitments) gets re-evaluated — and the contradictions that emerge route to Obsidian for you to resolve.

### Look at the graph yourself

After running `./demo.sh`, open `http://localhost:7474` (default password `atlasdev`) and run any of these:

```cypher
// Show the dependency edges Atlas walks during Ripple
MATCH (downstream)-[r:DEPENDS_ON]->(upstream)
RETURN downstream.kref, upstream.kref, r.dependency_strength
LIMIT 25;

// Show every belief and its current confidence
MATCH (b:Belief)
RETURN b.kref, b.confidence_score, b.deprecated
ORDER BY b.confidence_score DESC;

// Show the AGM revision history of a single belief
MATCH (root:AtlasItem)-[:REVISED_TO|SUPERSEDES*0..]->(rev)
WHERE root.kref = 'kref://AtlasCoffee/Beliefs/origins_value.belief'
RETURN rev.revision_index, rev.content, rev.revision_reason
ORDER BY rev.revision_index;

// Show the contradictions detector found
MATCH (a)-[r:CONTRADICTS]->(b)
RETURN a.kref, b.kref, r.detected_at;
```

---

## Why Atlas exists

The video [*Every Claude Code Memory System Compared*](https://youtu.be/UHVFcUzAGlM) maps 6 levels of memory — from native CLAUDE.md to OpenBrain's cross-tool Postgres. They all answer the same question: *"how do we store and retrieve?"*

**Atlas answers a different question:** *when stored knowledge changes, what happens to everything that depended on it?*

That's a Level 7 problem. Atlas runs ON TOP of any of the 6 lower levels. Every memory system flags affected beliefs when a fact changes. Atlas is the only one that re-evaluates them.

## What Atlas does that nothing else does

You have a vault. Maybe Obsidian, maybe Notion, maybe just markdown in a folder. Plus your meetings get transcribed (Limitless, Fireflies, Otter), plus your screen gets captured (Screenpipe, Rewind), plus you talk to Claude or ChatGPT all day. Together that's hundreds of files and tens of thousands of facts about your work.

**The problem we focus on:** when one of those facts changes — a price changes, a partner exits, a deadline slips — *every belief that depended on the old fact is now suspect*. Today, you have to chase the cascade in your head. Atlas tries to do it for you.

We're not aware of another open-source system that ships propagation as a first-class primitive; if you know of one, please file an issue — we want to compare honestly.

| When a fact changes... | Typical memory systems | Atlas (alpha) |
|---|---|---|
| Detect what's affected | Vector-similarity heuristic | `Depends_On` graph walk via `RippleEngine.analyze_impact()` |
| Re-evaluate downstream beliefs | Not exposed as a primitive | `RippleEngine.propagate()` — additive-with-damping confidence updates |
| Surface emergent contradictions | Not exposed | Type-aware detector (`atlas_core/ripple/contradiction.py`) |
| Route strategic conflicts to human | Not exposed | Obsidian markdown queue + `adjudication.resolve()` |
| Audit what was decided and why | Limited | Hash-chained SHA-256 ledger with `verify_chain()` |
| Forget deprecated beliefs cleanly | Not exposed | AGM `contract()` removes from closure, preserves history |

Verify any row above by reading the cited module or running `./demo.sh`.

### The technical claim, for people who care about the math

Atlas implements AGM belief revision (Alchourrón-Gärdenfors-Makinson 1985) on a property graph. The seven postulates K\*2-K\*6 plus Hansson's Relevance and Core-Retainment all hold — verified by 49 scenarios against live Neo4j 5.26. Same compliance Kumiho's commercial paper claims, but as fully open-source local-first code anyone can audit. The full per-scenario reproducibility artifact is at [`docs/AGM_COMPLIANCE.md`](docs/AGM_COMPLIANCE.md) (machine-readable rows in [`benchmarks/agm_compliance/runs/baseline.json`](benchmarks/agm_compliance/runs/baseline.json)).

### Detailed comparison vs other memory systems

If you're shopping memory backends for an agent system, here's how Atlas stacks up against the named alternatives:

| | Atlas | Kumiho | Graphiti | Mem0 | Letta | Memori |
|---|---|---|---|---|---|---|
| Open-source | ✅ Apache 2.0 | ❌ commercial | ✅ | ✅ | ✅ | ✅ |
| Local-first (no cloud) | ✅ | ❌ requires kumiho.io | ✅ | partial | ✅ | ✅ |
| AGM-compliant revision (K\*2–K\*6) | ✅ 49/49 @ 100% | ✅ 49/49 @ 100% | ❌ | ❌ | ❌ | ❌ |
| Hansson Relevance + Core-Retainment | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Hash-chained tamper-detection ledger | ✅ SHA-256 | partial | ❌ | ❌ | ❌ | ❌ |
| **Automatic downstream reassessment (Ripple)** | ✅ | ❌ flag-only | ❌ | ❌ | ❌ | ❌ |
| Domain-typed business ontology shipped | ✅ 8 entity types | ❌ | ❌ | ❌ | ❌ | partial |
| Continuous multi-stream ingestion | ✅ 6 streams | ❌ SDK only | ❌ | ❌ | ❌ | partial |
| Hermes / OpenClaw / Claude Code adapters | ✅ all 3 | partial | ❌ | partial | ❌ | ❌ |

#### What Atlas does *worse* (today)

The table above lists what Atlas does that the alternatives don't. The other half of an honest comparison: here's what they currently do *better*, and where you should reach for them instead of Atlas.

| Concern | What we'd reach for instead | Why |
|---|---|---|
| Pure-retrieval throughput on large corpora | Mem0, a hosted vector DB | Atlas reads embeddings, but the typed graph + Ripple bookkeeping adds latency a vector-only path doesn't pay. If retrieval-quality alone is your bottleneck, a flat vector index will be faster. |
| Conversational chat memory ("remember what I said in this thread") | Letta, Memori | Atlas is built around long-lived business beliefs and dependencies. For "the user mentioned a cat in turn 3, surface that in turn 47" you want a system designed for conversation state. |
| Managed hosted service, support contract, SOC 2 | Kumiho's commercial cloud | Atlas is open-source local-first. There is no "Atlas Inc." with a sales team. If your buying process needs a vendor on the other end, Atlas isn't that yet. |
| Plug-and-play with zero-config setup | Mem0, Letta | Atlas wants you to think about your domain — it ships the AGM operators, not a "just call `add_memory()`" facade. The opinionated typed ontology is power for some users and friction for others. |
| Real-time multi-user concurrency at scale | A managed graph platform (Neo4j Aura, AuraDB) | Atlas's local-first stance means a single Neo4j instance per user. Multi-tenant Tier 5 work is in progress; production-grade concurrency tuning is not the alpha's focus. |
| Natural-language extraction quality on truly unstructured text | LLM-tuned extractors maintained by a larger team | The extractors in `atlas_core/ingestion/extractors/` work on real Limitless / Fireflies / Claude transcripts but quality is uneven — see the alpha framing in the hero. Improving extraction is on the roadmap; if you need state-of-the-art entity extraction *today*, build a richer extraction layer above Atlas's quarantine API. |

If your shopping criteria match any row in the *worse* table, use the alternative. Atlas exists for the case where dependency-driven belief revision is load-bearing — and it's better to admit the tradeoffs than to over-claim and lose your trust the moment you hit one.

---

## What Atlas does

Atlas is a Python service that maintains a continuously-updated typed knowledge graph of your domain. Tell it something — directly, or via continuous capture from Screenpipe / Limitless / Fireflies / Claude Code logs / Obsidian / iMessage — and it:

1. **Quarantines the claim** until corroborated by an independent source family
2. **Promotes corroborated claims** to a hash-chained append-only ledger
3. **Triggers Ripple propagation** when a ledger entry creates a revision: traverses `Depends_On` edges, re-evaluates downstream beliefs with confidence propagation, surfaces emergent contradictions
4. **Routes resolution** — routine reassessments auto-apply via AGM operators; strategic contradictions go to a markdown adjudication queue you resolve in Obsidian

All revisions are AGM-compliant (K\*2–K\*6 + Hansson Relevance + Core-Retainment), formally verified against Kumiho's correspondence theorem (arxiv:2603.17244).

---

## Cost ($/month at steady state)

Honest accounting. Atlas's cost story shifts dramatically between v0.1.0a1 (today) and the post-Tier-1 system:

**v0.1.0a1 (today): ≈ $0/month.**
- Extractors are 100% deterministic — frontmatter parsing, YAML readers, regex pattern matching. No LLM calls.
- Ripple's `HeuristicReassessor` (default) does no LLM call; it's a closed-form damped formula. The `LLMReassessor` exists but is opt-in and not the default.
- Neo4j 5.26 runs locally in Docker. SQLite ledger is local. No telemetry, no cloud, no API keys.
- The only ongoing cost is the electricity to keep your machine on.

**Post-Tier-1.4 (LLM-driven extraction lands): bounded by your token budget.**
- LLM extraction will fire on free-text vault content, transcript bodies, Claude session decisions. The default prompt is sized for Claude Haiku 4.5: ≈ 800 input + 200 output tokens per claim.
- For Rich's actual data (one-author, ~10K events/week): ≈ $0.02-0.05 per claim × ~2K novel claims/week = **$40-100/month** at default settings.
- A token budget knob (`ATLAS_DAILY_LLM_BUDGET_USD`, defaults to $5/day) hard-stops extraction when the daily budget is exceeded. Worst case is $150/month even if the corpus explodes.
- A Ripple cascade triggered by an adjudication.resolve fires *one* LLM call per downstream node when the LLMReassessor is enabled — not per cascade. Rich-scale: <50 cascades/week × ≤10 downstream nodes × ≤$0.05 = **<$25/month** added.
- Total Rich-scale steady state when Tier 1.4 lands: **≈ $50-125/month**, hard-capped by the budget knob.

**Post-Tier-1.3 (entity resolution lands): same dollars, clearer outcomes.**
- The fuzzy + LLM-fallback resolution layer adds roughly $0.001 per ambiguous entity reference. On Rich-scale data, this is bounded by the alias dictionary cache — first-hit each unique alias is ~$0.001, subsequent hits are free.
- Net: rounding error against the extraction cost above.

For multi-tenant deployments (one Neo4j, many trust ledgers — not yet implemented but plausible by 2027), the math scales linearly per active user. A 100-user deployment at Rich-scale per user is ≈ $5K-12K/month in inference, dominantly Haiku.

**The substrate strategy bet:** $50-125/month is below the line where most knowledge workers think twice. It's an order of magnitude cheaper than running Cursor or hosting Mem0's commercial cloud. Atlas's local-first design is the architectural reason this number stays small.

---

## Real-world performance

On a one-author corpus (Rich Schefren's actual Obsidian vault + 5,000 Limitless transcripts + 300 Screenpipe audio rows + 5,000 Claude Code session logs):

```
== Atlas first real run ==
Streams        : 4
Total events   : 10,604
Total claims   : 14,674
Total errors   : 0
Elapsed        : 21.3s

Quarantine status breakdown:
  requires_approval      6,761  (medium-risk default; awaits adjudication)

Quarantine lane breakdown:
  atlas_observational    5,608  (Limitless + Screenpipe)
  atlas_vault              956  (vault frontmatter + body)
  atlas_chat_history       197  (Claude session prompts)

Ledger intact: ✅  (SHA-256 chain verified)
```

Re-runs are idempotent: 0.9s for the next cycle, with all duplicate claims fingerprint-deduplicated against existing entries.

---

## Quickstart (3 minutes)

> Three good install paths depending on why you want Atlas — researcher / dev, Obsidian power-user, or agent-runtime integration. Each one is self-contained and documented in [`docs/INSTALL_MODES.md`](docs/INSTALL_MODES.md). The block below is the universal version that works for all three.

```bash
# 1. Clone
git clone https://github.com/RichSchefren/atlas && cd atlas

# 2. Run Neo4j locally
docker compose up -d                               # bolt://localhost:7687

# 3. Install — base is deterministic + $0/month; opt in to extras as you need them
python -m venv .venv && source .venv/bin/activate
pip install -e .              # core: AGM + Ripple + ledger + adapters + ingest
# pip install -e ".[llm]"        # add Anthropic SDK for LLM-driven extraction
# pip install -e ".[embeddings]" # add sentence-transformers (~2GB; rarely needed — vault-search is the default retrieval path)
# pip install -e ".[benchmarks]" # add Mem0 / Letta clients for the BMB matrix
# pip install -e ".[full]"       # everything above
# pip install -e ".[dev]"        # contributor tooling (includes anthropic for tests)

# 4. Verify with the test suite (469 tests, ~12s)
PYTHONPATH=. pytest tests/ -v

# 5. Reproduce AGM compliance (49/49 scenarios, ~30s)
PYTHONPATH=. pytest tests/integration/test_agm_compliance.py -v

# 6. First real ingest from your own Obsidian vault
ATLAS_VAULT_ROOT=~/Documents/Obsidian PYTHONPATH=. python scripts/first_real_run.py
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  ATLAS API LAYER                                             │
│  MCP (13 tools) · FastAPI (:9879) · Kumiho-compatible gRPC    │
│  + Hermes / OpenClaw / Claude Code plugins                   │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  RIPPLE ENGINE — Atlas's novel contribution                  │
│  AnalyzeImpact → Reassess → Type-aware Contradictions →      │
│  Adjudication routing (auto / strategic / core-protected)    │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  TRUST LAYER — Quarantine → Corroboration → Hash-chained     │
│  Ledger. SHA-256 chain with verify_chain() tamper detection. │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  AGM REVISION — K*2–K*6 + Hansson, Cypher-backed             │
│  49/49 compliance scenarios pass at 100%                     │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  ATLAS CORE — fork of Graphiti                               │
│  Bitemporal edges. 6 Kumiho typed edges + 8 domain entities  │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  CONTINUOUS INGESTION — 6 streams, idempotent cursors        │
│  Vault · Limitless · Screenpipe · Claude · Fireflies · iMsg  │
└──────────────────────────────────────────────────────────────┘
```

Full design docs are checked into the repo at [`paper/atlas.md`](paper/atlas.md) and [`PHASE-5-AND-BEYOND.md`](PHASE-5-AND-BEYOND.md). The deeper Phase 0 / Phase 1 specs live in the maintainer's private notes — public summaries are in the paper draft.

---

## API surfaces

Atlas ships with three concurrent surfaces:

- **MCP**: 13 Atlas-original tools — `ripple.analyze_impact`, `ripple.reassess`, `ripple.detect_contradictions`, `adjudication.queue`, `adjudication.resolve`, `quarantine.upsert`, `quarantine.list_pending`, `ledger.verify_chain`, `working_memory.assemble`, `lineage.walk`, `sharing.grant`, `sharing.revoke`, `sharing.list_grants`. Stdio JSON-RPC bridge for Claude Code via `python -m atlas_core.adapters.claude_code`. Read-only vs mutation classification at [`docs/PROPOSAL_VS_MUTATION.md`](docs/PROPOSAL_VS_MUTATION.md).
- **HTTP**: FastAPI on `localhost:9879` mirrors the MCP surface for non-MCP clients (the dashboard, curl, integration tests). Endpoints: `/health`, `/tools`, `/tools/{name}`, `/verify-chain`.
- **gRPC** (Phase 2 W7+): scaffold with all 51 Kumiho-compatible RPC method names registered. Existing Kumiho SDK code switches to Atlas by setting `endpoint="localhost:50051"`.

Plus runtime adapters (drop-in plugins):

- `atlas_core.adapters.claude_code` — MCP stdio bridge for Claude Code
- `atlas_core.adapters.hermes.AtlasHermesProvider` — NousResearch Hermes MemoryProvider
- `atlas_core.adapters.openclaw.AtlasOpenClawPlugin` — OpenClaw memory plugin

---

## Benchmarks

Atlas is benchmarked head-to-head with Kumiho, Graphiti, Mem0, Letta, Memori, MemPalace, and vanilla GPT-4o (no memory) on three suites:

### 1. AGM compliance — 49 / 49 at 100%

Operational verification (not symbolic) of AGM postulates K\*2–K\*6 plus Hansson Relevance + Core-Retainment. Same scenario count as Kumiho's published Table 18.

| Postulate                  | Scenarios | Passed | Pass rate |
|----------------------------|-----------|--------|-----------|
| K\*2 Success               | 12        | 12     | 100.0%    |
| K\*3 Inclusion             | 8         | 8      | 100.0%    |
| K\*4 Vacuity               | 1         | 1      | 100.0%    |
| K\*5 Consistency           | 9         | 9      | 100.0%    |
| K\*6 Extensionality        | 3         | 3      | 100.0%    |
| Relevance (Hansson)        | 7         | 7      | 100.0%    |
| Core-Retainment (Hansson)  | 9         | 9      | 100.0%    |
| **Total**                  | **49**    | **49** | **100.0%** |

Five scenario categories — simple (10), multi_item (8), chain (8), temporal (8), adversarial (15). Adversarial bucket includes deliberately constructed cycles, conflicting tags, and concurrent revision races; all pass. Reproducible in one command:

```bash
PYTHONPATH=. pytest tests/integration/test_agm_compliance.py -v
```

Full scenario-level table: [`paper/appendix-a-agm-compliance.md`](paper/appendix-a-agm-compliance.md).

### 2. BusinessMemBench — Atlas 1.000, Graphiti 0.711, Vanilla 0.000 (preliminary, self-authored)

> 📦 **BMB now ships as its own repo:** [github.com/RichSchefren/businessmembench](https://github.com/RichSchefren/businessmembench) (MIT, `pip install businessmembench`). Adopt it, run it on your memory system, publish your numbers. Atlas's in-tree copy stays as a vendored snapshot for zero-dep test runs.

> ⚠ **Honesty disclaimer.** BusinessMemBench is *authored by the Atlas project*. The 149 questions in the current set are *deterministic and synthetic* — generated from corpus templates, not written by independent domain operators. Mem0, Letta, Memori, Kumiho, and MemPalace columns are still **skipped** because their API clients aren't pinned in this environment. We're publishing these numbers because the test loop reproduces on every machine that runs `scripts/run_bmb.py`, but **you should not treat them as a peer-reviewed head-to-head until the 200 human-authored gold subset and the four skipped baselines have actually run**. The full disclosure of what's authored vs measured is in `paper/atlas.md` § 6.2.

Currently 149 deterministic questions across three paraphrase variants per template. The 200 human-authored gold subset and LLM expansion to 1,000 are roadmap.

| System              | status   | overall | prop | contra | line | cross | hist | prov | forget |
|---------------------|----------|---------|------|--------|------|-------|------|------|--------|
| Vanilla (no memory) | measured | 0.000   | 0.00 | 0.00   | 0.00 | 0.00  | 0.00 | 0.00 | 0.00   |
| Graphiti            | measured | 0.711   | 0.33 | 0.00   | 1.00 | 0.00  | 1.00 | 1.00 | 0.00   |
| **Atlas**           | measured | **1.000** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** |
| Mem0                | skipped  | — | — | — | — | — | — | — | — |
| Letta               | skipped  | — | — | — | — | — | — | — | — |
| Memori              | skipped  | — | — | — | — | — | — | — | — |
| Kumiho              | skipped  | — | — | — | — | — | — | — | — |
| MemPalace           | skipped  | — | — | — | — | — | — | — | — |

`measured` = adapter wired in this repo, ran on this machine, score is from `baseline_seed42.json`.
`skipped` = adapter wired but the run requires credentials / pip install we don't ship (e.g. `OPENAI_API_KEY`, `MEMORI_API_KEY`, the `kumiho-sdk` package). Each adapter raises a clear `MissingClientError` with the missing dependency. Atlas does not bundle external API keys.

Atlas's structural lead over Graphiti — the contradiction / cross_stream / forgetfulness / propagation columns — is what the architecture was designed for. The score gap on a self-authored deterministic benchmark proves the architecture works against its own thesis; it does not yet prove general superiority. Reproducible in ≤30 seconds:

```bash
PYTHONPATH=. python scripts/run_bmb.py
```

The canonical run output (`seed=42`, full matrix) is checked in at [`benchmarks/business_mem_bench/runs/baseline_seed42.json`](benchmarks/business_mem_bench/runs/baseline_seed42.json) so visitors can read the scores without installing anything. The structural claims above are also enforced by `tests/integration/test_bmb_endtoend.py` — if Atlas regresses below 1.0 on any category, or Graphiti unexpectedly perfect-scores a Ripple category, CI fails loudly.

### 3. LoCoMo / LongMemEval — claimed parity, NOT YET MEASURED

> ⚠ The runners exist (`benchmarks/locomo/runner.py`, `benchmarks/longmemeval/runner.py`) and pass their own structural tests. The actual datasets — research-license JSONL files from the LongMemEval and LoCoMo papers — have **not** been downloaded and run against Atlas yet. The "parity with Kumiho's published 0.447 F1" claim is therefore an architectural prediction, not a measurement. The paper marks every cell in this category as predicted-not-measured.

---

## Testers

If you want to break Atlas, [TESTING.md](TESTING.md) has five concrete paths from a 5-minute smoke test to a 30-minute wire-level deep dive. Findings get filed via structured GitHub issue templates that auto-route by area (`smoke-test`, `loop-demo`, `bench`, `claude-code`, `ingest`). CI watches every push at <https://github.com/RichSchefren/atlas/actions>.

---

## Status — surgical separation of works today vs planned

**Alpha — v0.1.0a1.** Codex's review (2026-04-27) recommended this section be unambiguous. Every "works today" row below has a one-line proof you can run in under 10 seconds.

### Works today (verified by tests in CI)

| Capability | Proof |
|---|---|
| `RippleEngine.propagate()` runs the full cascade end-to-end | `./demo.sh` |
| AGM compliance — K\*2 / K\*3 / K\*4 / K\*5 / K\*6 / Hansson Relevance / Core-Retainment | `pytest tests/integration/test_agm_compliance.py -v` (49/49) |
| Hash-chained SHA-256 ledger with `verify_chain()` tamper detection | `pytest tests/unit/test_ledger.py -v` |
| Trust quarantine → corroboration → ledger state machine | `pytest tests/unit/test_quarantine.py -v` |
| Six ingestion extractors (Vault, Limitless, Screenpipe, Claude sessions, Fireflies stub, iMessage) | `pytest tests/unit/test_ingestion.py tests/unit/test_ingestion_extra.py -v` |
| Entity resolution cascade (alias → fuzzy → LLM fallback) | `pytest tests/unit/test_resolution.py -v` |
| LLM-driven extraction with hard-capped daily budget | `pytest tests/unit/test_llm_extractors.py -v` |
| Decision-lineage walker + lineage-weakening contradiction detector | `pytest tests/integration/test_lineage.py -v` |
| Working-memory block manager (Letta-style) | `pytest tests/unit/test_working_memory.py -v` |
| Multi-tenant tenant context + sharing policy + federated adjudication | `pytest tests/unit/test_multi_tenant.py -v` |
| Adjudication round-trip — markdown queue → AGM revise → ledger SUPERSEDE → archive | `pytest tests/integration/test_adjudication_resolver.py -v` |
| 13 MCP tools dispatch correctly via stdio JSON-RPC | `pytest tests/integration/test_mcp_server.py tests/integration/test_claude_code_stdio.py -v` |
| FastAPI surface with CORS + Server-Sent Events stream | `pytest tests/integration/test_http_server.py tests/unit/test_events_broadcaster.py -v` |
| Hermes / OpenClaw / Claude Code adapters at the contract level | `pytest tests/integration/test_adapters.py -v` |
| Kumiho-compat gRPC handlers (10 of 51 methods wired, 41 return UNIMPLEMENTED) | `pytest tests/integration/test_grpc_handlers.py -v` |
| Property-based AGM testing (hypothesis-driven) | `pytest tests/unit/test_agm_property_based.py -v` |
| BusinessMemBench at 1.000 vs Graphiti 0.711 on 149 deterministic questions | `python scripts/run_bmb.py` |
| Live ingest from real machine state (vault + Limitless + Screenpipe + Claude) | `python scripts/first_real_run.py` |
| launchd daemon installs (continuous ingestion + API server) | `./scripts/install_launchd.sh` |
| **All of the above run together** | `pytest tests/ -v` (446 passing) |

### Planned — explicitly NOT done (no proof commands, by design)

| Capability | Why it's not done |
|---|---|
| LoCoMo + LongMemEval **measured** numbers (not asserted) | Datasets are research-license; haven't been downloaded + run yet. Runners exist (`benchmarks/locomo/`, `benchmarks/longmemeval/`); just need someone with dataset access to fire them. |
| Mem0 / Letta / Memori columns in BMB matrix | Adapters fail-loud without `OPENAI_API_KEY` / `MEMORI_API_KEY`. Set the keys + re-run `scripts/run_bmb.py` to fill the rows. |
| 1,000-question BusinessMemBench (currently 149 deterministic) | The 200 human-authored gold subset (templates in `benchmarks/business_mem_bench/gold_human/`) needs domain-operator authors. The remaining 800 are LLM-expanded from templates — runner ready, expansion not yet executed. |
| Live Hermes / OpenClaw round-trip in their actual upstream processes | Adapter code complete + tested; round-trip in a real `hermes-agent` / `openclaw` runtime requires cloning those upstreams and configuring Atlas as memory backend. |
| arxiv submission live | Tarball ready at `paper/arxiv/atlas-arxiv.tar.gz`. Submission goes through arxiv.org/submit (24-48h moderation). |
| Confidence-threshold empirical calibration | Script exists at `scripts/calibrate_confidence_thresholds.py`. Needs a week of real ingest data before it produces a meaningful recommendation. |
| Obsidian plugin in the Community Plugins registry | Plugin code complete at `obsidian-plugin/`. Manual install path documented; registry submission deferred. |
| MCP plugin registry submission | Manifest at `mcp-registry/atlas.json`. Submitted when MCP registry opens for plugin uploads. |

If a row in **Works today** doesn't actually work on your machine, that's a bug — file an issue using the `tester-smoke` template.

If a row in **Planned** is something you want sooner, file an issue describing the use case and we'll prioritize.

Atlas as v0.1.0a1 is roughly **70-80% of the full system** described in the Phase 0 design docs. See `PHASE-5-AND-BEYOND.md` for the tiered roadmap of what's left.

Test count this snapshot: **446 passing** in CI against Ubuntu + Neo4j 5.26.

---

## License

Apache 2.0. See [LICENSE](LICENSE).

BusinessMemBench (the benchmark dataset) is MIT — maximally permissive for adoption as the new evaluation reference for propagation-aware memory systems.

---

## Acknowledgments

Atlas implements the AGM correspondence proofs from **Young Bin Park, *Graph-Native Cognitive Memory for AI Agents*** (arxiv:2603.17244, 2026). Atlas is an independent open-source implementation; not affiliated with Kumiho Inc.

Forks the storage substrate from **Graphiti by Zep AI** (Apache 2.0). Trust layer ports the policy architecture from **Bicameral by yhl999** (Apache 2.0); the SHA-256 hash chain is Atlas-original (Bicameral's chain was aspirational).

Built with multi-model AI collaboration: Claude Opus 4.7 (architecture, algorithms, paper), Codex 5.5 (boilerplate + tests), Gemini 2.5 Pro (parallel design review).
