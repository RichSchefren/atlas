# Newsletter pitches — send ~7:45am PT (after personal DMs, before HN/X)

Each pitch is short (under 200 words), names what's specifically interesting for *that* newsletter's audience, and includes one concrete reproducibility hook so the editor can verify in 30 seconds.

**Don't BCC.** Each one is hand-customized.

---

## Import AI (Jack Clark, ex-Anthropic)

**To:** jack@jack-clark.net (verify on his site)
**Subject:** Memory that knows when it's wrong — open-source AGM-compliant Kumiho companion

Jack — the Import AI angle is "research-y but actually shipped." I've open-sourced Atlas — a memory layer that re-implements Park's Kumiho AGM operators (arxiv 2603.17244) as local-first code (Apache 2.0) and adds one specific extension: forward implication propagation. When a fact lands in the SHA-256-chained ledger, an algorithm called Ripple walks the typed dependency graph and re-evaluates downstream belief confidence with cycle detection. 49/49 compliance scenarios pass at 100%; reproducibility artifact is checked in.

If Import AI tracks "research → shipped infrastructure" stories, this is one. The 88-second narrated launch video at https://livememory.dev shows the cascade firing on a real graph; the AGM compliance run is at github.com/RichSchefren/atlas/blob/master/docs/AGM_COMPLIANCE.md.

Happy to send a 200-word writeup in the format Import AI prefers.

— Rich Schefren

---

## Interconnects (Nathan Lambert, AI2)

**Send via:** Twitter DM @natolambert or his website contact form
**Subject:** Open-source companion to Kumiho — AGM-compliant memory + automatic reassessment

Nathan — Interconnects has been the strongest signal for rigor-first technical AI takes. Atlas is shipping today: open-source local-first AGM-compliant memory that re-evaluates downstream beliefs automatically when an upstream fact changes. The math is Park's Kumiho correspondence theorem (arxiv 2603.17244), implemented as auditable open-source code.

The technical hooks I think you'd care about: the AGM operators are property-tested via Hypothesis with random belief generators; the proposal-vs-mutation invariant is enforced by an AST-based regression test that parses every Cypher write across the cascade modules; BusinessMemBench is a 149-question reproducibility benchmark we ship with seed=42 baseline checked in.

Repo: github.com/RichSchefren/atlas. Paper draft: github.com/RichSchefren/atlas/blob/master/paper/atlas.md.

If Interconnects is open to a 600-word guest post on the algorithmic side specifically, I'd happily write it.

— Rich

---

## Latent Space (swyx)

**Send via:** Twitter DM @swyx or via Latent Space's submission form
**Subject:** Pitch — Atlas (open-source AGM-compliant local-first memory) for the pod

swyx — pitch for the show. Atlas is a memory system I've been heads-down on for three months that does something I think is podcast-interesting: it watches your dependency graph and re-evaluates downstream beliefs the moment an upstream fact changes, automatically. Not retrieval-time reasoning — ingestion-time reasoning.

It's the open-source local-first companion to Park's Kumiho paper (arxiv 2603.17244). Apache 2.0. 49/49 AGM compliance, 469 tests, runs on a single Neo4j + SQLite ledger on your machine.

Two angles for the pod: (1) the Ripple algorithm itself — recursive Cypher with cycle detection across typed dependency graphs is genuinely fun engineering, and (2) the meta-story — the multi-model AI development team that built it (Opus 4.7 leading, Codex 5.5 implementing, Gemini 2.5 Pro auditing every 3 days). The team-of-AIs-shipping-OSS angle has been requested by listeners and I haven't seen it told well yet.

Live launch ~8:30am PT today at https://livememory.dev.

— Rich

---

## The Batch (DeepLearning.AI / Andrew Ng's team)

**Send via:** thebatch@deeplearning.ai
**Subject:** Open-source AGM-compliant memory layer with automatic downstream reassessment

The Batch covers practitioner-relevant AI infrastructure. Atlas — releasing today — is an open-source local-first memory layer that re-evaluates downstream beliefs when upstream facts change. Same AGM mathematical correctness as Kumiho (commercial cloud); fully open-source, local-first, Apache 2.0.

The 90-second story for The Batch's "industry" section: every AI memory system today retrieves stale belief without knowing it's stale. Atlas adds the propagation layer that catches this. Tested at 49/49 AGM postulate scenarios, 469 integration tests, BMB head-to-head benchmark checked in.

Repo: github.com/RichSchefren/atlas
Live: https://livememory.dev (narrated 88s video on hero)

Happy to provide a 100-word summary in The Batch's standard format.

— Rich Schefren

---

## Machine Learning Street Talk (Tim Scarfe)

**Send via:** Twitter DM @ecsquendor or YouTube channel contact
**Subject:** MLST pitch — AGM belief revision + property graphs, shipped as open-source

Tim — MLST is exactly the venue where formal-and-shipped meets. Pitching Atlas: open-source AGM-compliant memory layer with automatic forward implication propagation. The novel contribution is an algorithm called Ripple that operationalizes belief revision over a property graph: when a fact changes, it walks the typed dependency graph and re-evaluates downstream confidence, with cycle detection.

The conversation MLST listeners would value: the operational gap between AGM-as-theory (Alchourrón-Gärdenfors-Makinson 1985) and AGM-as-running-code on a property graph. Park proved the correspondence in his Kumiho paper (arxiv 2603.17244); Atlas runs the open-source local-first implementation.

49/49 scenarios pass at 100% with reproducibility artifact. Property-based tests via Hypothesis. AST-based invariant enforcement.

Happy to record at your convenience.

— Rich Schefren
github.com/RichSchefren/atlas
