# Reddit Drafts — 4 subreddits, different tones

**Sequencing:** post r/LocalLLaMA at ~10am PT (highest hit rate for technical OSS launches), r/Obsidian at noon PT, r/MachineLearning later in the afternoon, r/programming next day. Don't compete with your own HN attention.

**Common rules:** Reddit hates self-promotion. Lead with technical content; the link goes at the end. Engage in comments fast.

---

## r/LocalLLaMA — *post at ~10am PT*

**Title:** I built an open-source local-first memory layer that AUTO-RE-EVALUATES downstream beliefs when facts change (AGM-compliant, Apache 2.0)

**Body:**

For the last three months I've been heads-down on a memory project that's a bit different from the usual vector-store-with-extra-steps. Sharing here because I think this community in particular cares about local-first + open-source + actually-runnable.

The premise: every memory system ingests text, embeds, retrieves. Mem0, Letta, Memori, Graphiti, Kumiho — they all do this well. None of them re-evaluate downstream beliefs when a fact changes. If you priced something at $2,995 three weeks ago and updated it to $3,495 yesterday, every margin claim that quoted the old price is now wrong, and the memory system doesn't know.

Atlas's contribution is an algorithm called **Ripple**. When a fact lands in the immutable ledger, Ripple walks the typed DEPENDS_ON graph, recomputes confidence on each downstream belief via dependency strength, and surfaces emergent contradictions to a markdown adjudication queue you resolve in Obsidian. AGM-compliant (the K\*2–K\*6 + Hansson Relevance/Core-Retainment postulates from 1985 — same formal correctness Kumiho's commercial paper claims, but as fully open-source code).

What's in the box:
- 469 tests passing against live Neo4j 5.26
- AGM compliance: 49/49 scenarios pass at 100% (reproducibility artifact in the repo)
- 13 MCP tools (Claude Code adapter ships out of the box)
- Hermes + OpenClaw adapters for agent-runtime integration
- Hash-chained SHA-256 ledger with tamper detection
- Six ingestion streams (Obsidian vault, Limitless, Fireflies, Screenpipe, Claude session logs, iMessage)
- BusinessMemBench: 149-question reproducible head-to-head harness, seed=42 baseline checked in

Local-first means a single Neo4j instance + SQLite ledger on your machine. No cloud, no telemetry, no API keys for the core path.

Apache 2.0. Repo: https://github.com/RichSchefren/atlas. Live demo + 90s narrated video at https://livememory.dev (or `livememory.pages.dev` if the cert hasn't propagated yet).

If you build with memory in agent stacks, would love to hear what breaks.

---

## r/Obsidian — *post at noon PT*

**Title:** I built an open-source memory layer that uses Obsidian for human adjudication when AI memory contradicts itself

**Body:**

Different angle for this sub. Atlas is a memory system I've been building (AGM-compliant belief revision, automatic downstream reassessment, Apache 2.0). The thing that might be relevant to Obsidian users: when Atlas's algorithm finds a strategic contradiction it can't auto-resolve, it writes the conflict as a markdown file to an adjudication queue you resolve **inside Obsidian**.

That means:
- The "queue" is just a folder of markdown files. Open it in Obsidian alongside your main vault.
- Each entry has a frontmatter block (target_kref, old_confidence, new_confidence, contradictions_count, route) and a body that explains the conflict in human-readable form.
- You decide the resolution by editing the markdown — `decision: accept` / `decision: reject` / `decision: adjust`. Atlas re-reads the file, applies the AGM revision, archives the entry.

Atlas also reads from your vault as one of six ingestion streams — `atlas_core/ingestion/vault.py` watches file changes and extracts structured claims via frontmatter parsing (no LLM required for the core path).

If you have a vault you actually use for thinking — meetings, decisions, projects, distinctions — Atlas can sit underneath, watch for contradictions when facts change in your captures, and route the strategic ones back to Obsidian for you to resolve.

Repo: https://github.com/RichSchefren/atlas. 12-second demo at https://livememory.dev.

Happy to answer questions about the vault adapter or the markdown queue format specifically.

---

## r/MachineLearning — *post late afternoon PT*

**Title:** [P] Atlas — open-source local-first AGM-compliant memory with automatic downstream reassessment (extends Kumiho's correspondence theorem)

**Body:**

I'm releasing Atlas, an open-source local-first cognitive memory system. It re-implements the AGM operators (K\*2–K\*6 + Hansson Relevance/Core-Retainment) on a property graph as Kumiho proved possible (arxiv 2603.17244), and extends with one specific algorithmic contribution: **forward implication propagation via the Ripple algorithm**.

The gap Atlas fills: every memory system flags affected beliefs when a fact changes. Atlas re-evaluates them, by walking the typed DEPENDS_ON graph with cycle detection and recomputing confidence on each downstream belief via dependency strength.

Empirical claims, all reproducible:

- AGM compliance: 49 of 49 scenarios pass at 100%, matching Kumiho's published Table 18. Reproducibility artifact at `docs/AGM_COMPLIANCE.md`.
- BusinessMemBench (a benchmark we author and ship in the repo, MIT-licensed): Atlas 1.000 vs Graphiti 0.711 vs Vanilla 0.000 across 149 deterministic questions. The claim is *structural*: Atlas wins by definition on the four propagation-aware categories, ties on the three typed-graph-suffices categories. Honest disclaimer in the README: this is a self-authored benchmark and several adapter columns (Mem0/Letta/Memori/Kumiho/MemPalace) are still skipped.
- 469 unit + integration tests against live Neo4j 5.26, AST-enforced invariant test for the proposal-vs-mutation safety guarantee, property-based tests for the AGM operators.

Paper draft (cites Kumiho prominently): https://github.com/RichSchefren/atlas/blob/master/paper/atlas.md

Repo: https://github.com/RichSchefren/atlas

Apache 2.0. Local-first (Neo4j + SQLite ledger, no cloud).

Critique welcome — especially on the property-based AGM tests and the Cypher implementation of analyze_impact. Happy to walk through specific design choices in the comments.

---

## r/programming — *post next day at ~9am PT*

**Title:** Open-source AGM-compliant memory system in Python — the Cypher behind automatic downstream reassessment

**Body:**

I shipped a memory system yesterday and the comment thread on HN got into the implementation, so I figured this sub might enjoy the engineering side specifically.

Atlas is an open-source local-first cognitive memory layer (Apache 2.0, github.com/RichSchefren/atlas). The interesting engineering is the Ripple algorithm: when a fact lands in the SHA-256-chained ledger, Ripple walks the typed DEPENDS_ON graph in Neo4j, recomputes confidence on each downstream belief, surfaces emergent contradictions to a markdown adjudication queue, and routes resolution through the AGM operators.

Three things I'm proud of, code-wise:

1. **Recursive Cypher with cycle detection.** AnalyzeImpact is a max-depth bounded recursive walk with a visited-set guard and a cycle-report to the adjudication queue. Code at `atlas_core/ripple/analyze_impact.py`.

2. **AST-enforced invariant test.** Atlas has one safety guarantee that's load-bearing: no graph-typed mutation happens automatically as part of Ripple propagation. The test that enforces it parses every `session.run("...")` call in the cascade modules and fails CI if a Cypher write keyword (MERGE, CREATE, DELETE, SET-property) leaks in. `tests/unit/test_proposal_vs_mutation.py`.

3. **Property-based AGM tests.** The K\*2–K\*6 postulates aren't just hand-tested with example revisions — they're property-tested via Hypothesis with random belief generators. If a property fails, you get a minimum reproducing example out of the box. `tests/unit/test_agm_property_based.py`.

12-second demo: clone, `docker compose up -d`, `./demo.sh`. Or watch the 88s narrated video at https://livememory.dev.

Repo: https://github.com/RichSchefren/atlas
