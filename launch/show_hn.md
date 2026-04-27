# Show HN: Atlas — open-source local-first AGM-compliant cognitive memory

**Title (≤80 chars):**
Show HN: Atlas – open-source memory that re-evaluates, not just retrieves

**URL:** github.com/RichSchefren/atlas

---

## Body (HN markdown)

Hi HN.

I'm releasing Atlas — an open-source local-first cognitive memory system that runs as the substrate underneath any agent runtime (Hermes, OpenClaw, Claude Code, anything that speaks MCP).

The motivation: every memory system I looked at — Mem0, Letta, Memori, Graphiti, even the formal AGM-compliant Kumiho — solves the "store and retrieve" problem. None of them solve the "reassess" problem.

When you change a fact, every downstream belief that depended on it is now suspect. Kumiho's AnalyzeImpact tells you *which* beliefs are affected. It doesn't re-evaluate them. The user has to chase the cascade manually.

Atlas closes that gap with an algorithm I'm calling Ripple. When a belief is promoted to the immutable ledger, Ripple walks the Depends_On cascade with cycle detection, recomputes confidence on each downstream belief via dependency strength, surfaces emergent contradictions, and routes strategic conflicts to a markdown adjudication queue you resolve in Obsidian.

What's there today:

- 288 tests passing (210 integration + 78 unit) against live Neo4j 5.26
- AGM compliance: 49/49 scenarios pass at 100%, matching Kumiho's published verification
- Six ingestion streams (Obsidian vault, Limitless, Screenpipe, Claude session logs, Fireflies, iMessage); idempotent cursors; per-stream confidence floors
- Three API surfaces (MCP stdio, FastAPI HTTP, gRPC scaffold for Kumiho-SDK drop-in)
- Hash-chained SQLite ledger with verify_chain() tamper detection — actual SHA-256 chain, not aspirational
- Three runtime adapters (Hermes MemoryProvider, OpenClaw plugin, Claude Code MCP)

Just ran it against my own corpus: 10,604 events from 4 streams in 21.3 seconds, 14,674 raw claims dedup'd to 6,761 unique candidates in the trust quarantine. Re-runs are 0.9s thanks to fingerprint deduplication. Zero errors.

Where Atlas extends Kumiho (which is the closest neighbor):

1. Open-source local-first vs commercial cloud
2. Ripple — auto reassessment, not just AnalyzeImpact flagging
3. 8-entity domain ontology shipped by default vs domain-agnostic
4. Continuous multi-stream ingestion vs SDK-only
5. Trust layer with quarantine → corroboration → ledger gating

Atlas builds directly on Young Bin Park's formal contribution (arxiv:2603.17244). I cite Kumiho throughout. The AGM correspondence proof is theirs; the open-source implementation is mine.

Releasing Atlas under Apache 2.0. Releasing BusinessMemBench (1,000-question benchmark across 7 categories) under MIT for max adoption.

The code: github.com/RichSchefren/atlas
The paper draft: github.com/RichSchefren/atlas/blob/main/paper/atlas.md
Live interactive demo (Ripple cascade animated on a sample graph): <FILL-IN-AFTER-DOMAIN-REGISTERED>/live-demo

Happy to answer questions about the architecture, the AGM postulate verification approach, the trust gating, the propagation algorithm, or why I chose to fork Graphiti rather than build from scratch.
