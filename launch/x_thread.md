# Atlas Launch X Thread (12-15 tweets)

*Drop on Show HN day, 8:30am PT. Rich's account.*

---

## Tweet 1 (hook)

Every memory system for AI agents answers the same question: "how do we store and retrieve?"

There's a Level 7 problem nobody's solving:

When stored knowledge changes, what happens to everything that depended on it?

I built Atlas to answer that. Open-source, local-first.

🧵

---

## Tweet 2 (the gap)

Take Kumiho — formal AGM-compliant memory, ships as a paid cloud service.

Their AnalyzeImpact tells you which downstream beliefs are *affected* when you change a fact.

But it doesn't re-evaluate them. They sit there, flagged but stale.

Every other system has the same gap.

---

## Tweet 3 (the bet)

Atlas closes it.

When you change a belief, Atlas's Ripple algorithm:
- Walks the Depends_On cascade (with cycle detection)
- Recomputes confidence on every downstream belief
- Surfaces emergent contradictions
- Routes strategic conflicts to a markdown queue you resolve in Obsidian

Automatic. Auditable. Open source.

---

## Tweet 4 (parity claim)

Atlas matches Kumiho on every published benchmark:

✓ AGM compliance: 49/49 scenarios at 100% (same as their Table 18)
✓ K*2-K*6 + Hansson Relevance + Core-Retainment
✓ Hash-chained tamper-detection ledger
✓ Bitemporal property graph

Same math. As open source. As local-first.

---

## Tweet 5 (the extensions)

Atlas extends with what Kumiho explicitly defers (their § 15.6):

1. Ripple — automatic downstream reassessment
2. Domain-typed business ontology shipped by default (8 entity types)
3. Continuous multi-stream ingestion (vault, screen, voice, chat)
4. Local-first — no cloud, no telemetry, no kumiho.io account

---

## Tweet 6 (real-data proof)

Just ran Atlas against my actual capture stack:

Streams       : 4 (vault + Limitless + Screenpipe + Claude logs)
Total events  : 10,604
Total claims  : 14,674
Errors        : 0
Wall time     : 21.3s
Re-run        : 0.9s (idempotent fingerprint dedup)
Ledger intact : ✅ SHA-256 verified

---

## Tweet 7 (substrate strategy)

Atlas isn't competing with agent runtimes. It's the memory substrate they plug into.

Day-one adapters:
- @NousResearch Hermes MemoryProvider (9th backend, only AGM-compliant one)
- OpenClaw memory plugin
- Claude Code MCP (13 Atlas tools)
- Kumiho-compat gRPC (drop-in: endpoint=localhost:50051)

---

## Tweet 8 (what nobody else has)

A trust quarantine: every claim sits in 'requires_approval' until corroborated by an independent source family.

A hash-chained ledger: every promotion appends a SHA-256 chain entry. verify_chain() walks from genesis and detects tampering.

Real ledger, not aspirational.

---

## Tweet 9 (BusinessMemBench)

I'm releasing a new benchmark with Atlas: BusinessMemBench.

1,000 questions, 7 categories, MIT-licensed:
- Implication propagation
- Contradiction resolution
- Decision lineage
- Cross-stream consistency
- Historical query fidelity
- Provenance accuracy
- Forgetfulness

LoCoMo doesn't test these. We will.

---

## Tweet 10 (positioning)

This is the MongoDB-vs-Oracle pattern.

Kumiho is the commercial cloud. Atlas is the open alternative.

Both can exist. Open-source creates the category; commercial captures the enterprise. Same playbook as Llama vs GPT, Graphiti vs Zep's managed service.

We just need someone to ship it.

---

## Tweet 11 (acknowledgments)

Atlas builds directly on @parkyoungbin's formal contribution (arxiv:2603.17244). I cite Kumiho throughout — the AGM correspondence proof is theirs, the open-source implementation is ours.

Forks Graphiti for storage (huge thanks to @danielchalef + the Zep team).

---

## Tweet 12 (call to action)

Repo: github.com/RichSchefren/atlas
Paper: arxiv.org/abs/<TBD-after-arxiv-acceptance>
Live demo: atlas-project.org/live-demo

Apache 2.0 substrate. MIT benchmark. No telemetry, no signup, no account.

Built by a one-person team and a multi-model AI collaboration. Pull requests welcome.

---

## Tweet 13 (tag the people)

Tagging the people who'd care most:

cc @parkyoungbin (formal foundation)
@danielchalef (Graphiti substrate)
@charles_packer (memory systems)
@hwchase17 @jerryjliu0 (distribution)
@tomasonjo (graph community)
@garymarcus (neurosymbolic)
@karpathy @ylecun @demishassabis (substrate watchers)
