# Atlas

> **Open-source local-first cognitive memory.** Same AGM-compliant belief revision math as commercial state-of-the-art (Kumiho), running entirely on your laptop. Plus the thing nobody ships: when a fact changes, dependent beliefs are *automatically re-evaluated* — not just flagged.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Status: alpha](https://img.shields.io/badge/Status-alpha-orange.svg)]()

---

## What Atlas does

Atlas is a Python service that maintains a continuously-updated typed knowledge graph of a specific domain. When you tell Atlas something — directly, or via continuous capture from Screenpipe / Limitless / Fireflies / Claude Code logs / Obsidian / iMessage — it:

1. **Quarantines the claim** until corroborated by an independent source family
2. **Promotes corroborated claims** to a hash-chained append-only ledger
3. **Triggers Ripple propagation** when a ledger entry creates a revision: traverses `Depends_On` edges, re-evaluates downstream beliefs with confidence propagation, surfaces emergent contradictions
4. **Routes resolution** — routine reassessments auto-apply via AGM revision operators; strategic contradictions go to a markdown adjudication queue you resolve in Obsidian

All revisions are AGM-compliant (K*2-K*6 + Hansson Relevance + Core-Retainment), formally proved against Kumiho's correspondence theorem (arxiv:2603.17244).

## Where Atlas fits

The video [*Every Claude Code Memory System Compared*](https://youtu.be/UHVFcUzAGlM) maps 6 levels of memory — from native CLAUDE.md to OpenBrain's cross-tool Postgres. They all answer the same question: *"how do we store and retrieve?"*

Atlas answers a different question: ***"when stored knowledge changes, what happens to everything that depended on it?"*** That's a Level 7 problem. Atlas runs ON TOP of any of the 6 lower levels. Adapters ship for Hermes, OpenClaw, Claude Code via MCP, and a Kumiho-SDK-compatible gRPC surface.

## Quickstart (3 minutes)

```bash
# 1. Run Neo4j locally (any version 5.26+)
docker run -d --name neo4j-atlas -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/atlas \
  neo4j:5.26

# 2. Install Atlas
pip install atlas-core

# 3. Run a first ingest
python -m atlas_core.examples.business_ontology_demo
```

Detailed quickstart: [docs/QUICKSTART.md](docs/QUICKSTART.md)

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  ATLAS API LAYER                                             │
│  MCP Server · HTTP Server · Kumiho-compatible gRPC           │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  RIPPLE ENGINE — automatic downstream reassessment           │
│  AnalyzeImpact + Reassess + Confidence Propagation           │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  TRUST LAYER — Quarantine (0.25) → Corroboration (0.6)       │
│                              → Ledger (1.0)                   │
│  SHA-256 hash-chained SQLite ledger                          │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  ATLAS CORE — fork of Graphiti                               │
│  Bitemporal edges. AGM K*2-K*6. 6 typed edges + 10 domain    │
└──────────────────────────────────────────────────────────────┘
                            │
┌──────────────────────────────────────────────────────────────┐
│  CONTINUOUS INGESTION — 6 streams                             │
│  Screenpipe · Limitless · Fireflies · Claude · Vault · iMsg  │
└──────────────────────────────────────────────────────────────┘
```

Full architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Status

Alpha — under active development. First public release: targeted ~Q3 2026. See [SPECS/](specs/) for the full design lock.

## License

Apache 2.0. See [LICENSE](LICENSE).

## Acknowledgments

Atlas implements the AGM correspondence proofs from **Young Bin Park, "Graph-Native Cognitive Memory for AI Agents" (arxiv:2603.17244, 2026)**. Atlas is an independent open-source implementation; not affiliated with Kumiho Inc.

Forks the storage substrate from **Graphiti by Zep AI** (Apache 2.0). Trust layer ports the policy architecture from **Bicameral by yhl999** (Apache 2.0), with a real SHA-256 hash chain Atlas adds (Bicameral's chain was aspirational).

Built with multi-model AI collaboration: Claude Opus 4.7 (architecture, algorithms), Codex 5.5 (implementation), Gemini 2.5 Pro (parallel review).
