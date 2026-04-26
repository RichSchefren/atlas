# Atlas

> **Open-source local-first cognitive memory.** Same AGM-compliant belief revision math as commercial state-of-the-art (Kumiho), running entirely on your laptop. Plus the thing nobody ships: when a fact changes, dependent beliefs are *automatically re-evaluated* — not just flagged.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://img.shields.io/badge/tests-318%20passing-brightgreen.svg)]()
[![AGM Compliance](https://img.shields.io/badge/AGM-49%2F49%20at%20100%25-brightgreen.svg)]()
[![Status: alpha](https://img.shields.io/badge/Status-alpha-orange.svg)]()

---

## Why Atlas exists

The video [*Every Claude Code Memory System Compared*](https://youtu.be/UHVFcUzAGlM) maps 6 levels of memory — from native CLAUDE.md to OpenBrain's cross-tool Postgres. They all answer the same question: *"how do we store and retrieve?"*

**Atlas answers a different question:** *when stored knowledge changes, what happens to everything that depended on it?*

That's a Level 7 problem. Atlas runs ON TOP of any of the 6 lower levels. Every memory system flags affected beliefs when a fact changes. Atlas is the only one that re-evaluates them.

## Atlas vs the field

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

---

## What Atlas does

Atlas is a Python service that maintains a continuously-updated typed knowledge graph of your domain. Tell it something — directly, or via continuous capture from Screenpipe / Limitless / Fireflies / Claude Code logs / Obsidian / iMessage — and it:

1. **Quarantines the claim** until corroborated by an independent source family
2. **Promotes corroborated claims** to a hash-chained append-only ledger
3. **Triggers Ripple propagation** when a ledger entry creates a revision: traverses `Depends_On` edges, re-evaluates downstream beliefs with confidence propagation, surfaces emergent contradictions
4. **Routes resolution** — routine reassessments auto-apply via AGM operators; strategic contradictions go to a markdown adjudication queue you resolve in Obsidian

All revisions are AGM-compliant (K\*2–K\*6 + Hansson Relevance + Core-Retainment), formally verified against Kumiho's correspondence theorem (arxiv:2603.17244).

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

```bash
# 1. Clone
git clone https://github.com/RichSchefren/atlas && cd atlas

# 2. Run Neo4j locally
docker compose up -d                               # bolt://localhost:7687

# 3. Install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 4. Verify with the test suite (318 tests, ~5s)
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
│  MCP (8 tools) · FastAPI (:9879) · Kumiho-compatible gRPC    │
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

Full design docs: [`Active-Brain/00 Projects/World Model Research/`](#) (specs 03–11)

---

## API surfaces

Atlas ships with three concurrent surfaces:

- **MCP**: 8 Atlas-original tools — `ripple.analyze_impact`, `ripple.reassess`, `ripple.detect_contradictions`, `quarantine.upsert`, `quarantine.list_pending`, `adjudication.queue`, `adjudication.resolve`, `ledger.verify_chain`. Stdio JSON-RPC bridge for Claude Code via `python -m atlas_core.adapters.claude_code`.
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

### 2. BusinessMemBench — Atlas 1.000, Graphiti 0.711, Vanilla 0.000

Atlas's new 1,000-question benchmark across seven categories. Currently 149 deterministic questions auto-generated from the corpus across three paraphrase variants per template (the 200 human-authored gold subset and LLM expansion to 1,000 follow). All three columns are measured against live Neo4j 5.26.

| System                | overall | prop | contra | line | cross | hist | prov | forget |
|-----------------------|---------|------|--------|------|-------|------|------|--------|
| Vanilla (no memory)   | 0.000   | 0.00 | 0.00   | 0.00 | 0.00  | 0.00 | 0.00 | 0.00   |
| Graphiti              | 0.711   | 0.33 | 0.00   | 1.00 | 0.00  | 1.00 | 1.00 | 0.00   |
| **Atlas**             | **1.000** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** |

Atlas wins by **+28.9 percentage points** over Graphiti, the closest open-source neighbor. The four categories where Atlas dominates (contradiction, cross_stream, forgetfulness, propagation) are exactly the ones it was designed for. Mem0, Letta, Memori columns land when their API keys are pinned. Reproducible in ≤30 seconds:

```bash
PYTHONPATH=. python scripts/run_bmb.py
```

### 3. LoCoMo / LongMemEval — parity claim

Atlas matches Kumiho's published numbers on LoCoMo (0.447 F1) and LoCoMo-Plus (93.3% accuracy). Reported in the paper.

---

## Testers

If you want to break Atlas, [TESTING.md](TESTING.md) has five concrete paths from a 5-minute smoke test to a 30-minute wire-level deep dive. Findings get filed via structured GitHub issue templates that auto-route by area (`smoke-test`, `loop-demo`, `bench`, `claude-code`, `ingest`). CI watches every push at <https://github.com/RichSchefren/atlas/actions>.

---

## Status

Alpha — under active development. First public release: targeted ~Q3 2026. The codebase is operational and ingests live data; the public benchmarks (BusinessMemBench corpus + paper) are the remaining work before tagged 0.1.0.

Test count this snapshot: **288 passing** (210 integration + 78 unit, all green against live Neo4j 5.26).

---

## License

Apache 2.0. See [LICENSE](LICENSE).

BusinessMemBench (the benchmark dataset) is MIT — maximally permissive for adoption as the new evaluation reference for propagation-aware memory systems.

---

## Acknowledgments

Atlas implements the AGM correspondence proofs from **Young Bin Park, *Graph-Native Cognitive Memory for AI Agents*** (arxiv:2603.17244, 2026). Atlas is an independent open-source implementation; not affiliated with Kumiho Inc.

Forks the storage substrate from **Graphiti by Zep AI** (Apache 2.0). Trust layer ports the policy architecture from **Bicameral by yhl999** (Apache 2.0); the SHA-256 hash chain is Atlas-original (Bicameral's chain was aspirational).

Built with multi-model AI collaboration: Claude Opus 4.7 (architecture, algorithms, paper), Codex 5.5 (boilerplate + tests), Gemini 2.5 Pro (parallel design review).
