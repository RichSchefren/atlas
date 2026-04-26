# Pre-Launch Outreach Drafts

*Send 24-48 hours before public launch. Each gets a personalized first paragraph; the body is reusable. Rich edits voice + tags.*

---

## 1. Young Bin Park — Kumiho author (HIGHEST PRIORITY)

**Subject:** Open-source companion to your AGM correspondence work

Hi Young Bin,

I've spent the last few weeks reading your Kumiho paper end-to-end and building an open-source local-first implementation of the AGM correspondence you proved. I'm releasing it as Atlas next week and wanted you to see it before it goes public — both because it builds directly on your formal contribution and because I'd rather you hear about it from me than from Twitter.

Atlas reproduces your 49-scenario AGM compliance verification at 100% (same K\*2-K\*6 + Hansson postulates, same scenario shape) and extends with the automatic downstream reassessment you explicitly defer in § 15.6. The Ripple algorithm walks the Depends_On cascade after a ledger promotion and recomputes confidence on each downstream belief.

I want Atlas to be positioned as the open-source companion to your commercial work — the MongoDB-vs-Oracle pattern. You ship the formal foundation and the enterprise cloud. I ship the open-source local-first version and the propagation extension. Different markets; you have the citation; nobody's hostile.

Can I send you the repo + paper draft for review before it's public?

Rich

---

## 2. Karan Malhotra — NousResearch / Hermes (HIGH-LEVERAGE)

**Subject:** Atlas as Hermes's 9th MemoryProvider

Hi Karan,

Quick one. I'm releasing an open-source memory system called Atlas next week — AGM-compliant belief revision with automatic downstream reassessment. Built it specifically to plug into Hermes as a MemoryProvider.

Atlas is the only memory backend Hermes could ship that does:
- AGM-compliant revision (49/49 compliance scenarios pass at 100%)
- Automatic downstream reassessment when a belief changes
- Hash-chained tamper-detection ledger
- Continuous multi-stream ingestion

The plugin already implements the full 4-method MemoryProvider contract (put / search / get / delete) — you can find it at `atlas_core/adapters/hermes.py` in the repo.

Mutual interest: your plugin ecosystem grows by one strongly-differentiated backend; my distribution gets the Hermes 115K-star umbrella. Want to chat about featuring Atlas as the recommended memory provider for AGM-correctness use cases?

Rich

---

## 3. Daniel Chalef — Zep / Graphiti

**Subject:** Atlas — extending Graphiti with AGM + Ripple

Hi Daniel,

Wanted to give you advance notice that I'm releasing an open-source memory system next week called Atlas that forks Graphiti for the storage layer. Apache 2.0; I credit Graphiti prominently in the README + paper.

Atlas extends Graphiti with three things you don't ship:

1. AGM-compliant revision (K\*2-K\*6 + Hansson) on top of the bitemporal edge model. We bypass `resolve_extracted_edges` because its "most recent wins" semantics violate K\*2 (Success).
2. The Ripple algorithm — automatic downstream reassessment when a belief changes.
3. A trust quarantine + hash-chained ledger that gates promotions to the canonical graph.

Two questions:

(a) Want to review the design before public release? Specifically the AGM operator implementation and the choice to bypass the edge resolver — both touch areas you know better than anyone.

(b) Is there interest in a Graphiti-side integration or feature flag, or do you want Atlas to stay a clean fork? I'm fine with either; want to do what's right for the community.

Rich

---

## 4. Charles Packer — Letta

**Subject:** Atlas — AGM-compliant memory substrate, releasing next week

Hi Charles,

Quick heads-up. I'm releasing an open-source memory system called Atlas next week. AGM-compliant belief revision (matching the formal Kumiho contribution at 49/49) with automatic downstream reassessment.

Atlas is positioned for a different problem class than Letta — Letta solves working-memory + agent state, Atlas solves long-horizon factual-belief consistency with formal correctness. They're complementary; I'd love your read on whether Letta could use Atlas as its persistent memory backend for the cases where formal correctness matters (legal, finance, scientific).

Repo + paper drop next week. Want to see the architecture before then?

Rich

---

## 5. Tomaž Bratanic — Neo4j

**Subject:** Atlas — open-source AGM-compliant memory on Neo4j 5.26

Hi Tomaž,

Releasing Atlas next week — open-source local-first cognitive memory built on Neo4j 5.26. Apache 2.0. The full AGM revision logic is implemented as Cypher transactions; 49/49 compliance scenarios pass at 100%.

Three Neo4j-community-relevant pieces:
- Recursive Cypher for the Depends_On cascade with cycle detection
- Bitemporal edge handling for `valid_at` queries
- A novel approach to belief supersession that uses `Supersedes` edges rather than mutating prior nodes

If you'd be open to a guest post or tutorial on the Neo4j blog, I'd love to write one once the repo's public. The graph community is exactly the audience that'd care about this.

Rich

---

## 6. Newsletter pitches (single email, BCC the editors)

**Subject:** Atlas (open-source AGM-compliant cognitive memory) — release next week

Hi,

Brief pitch. I'm releasing an open-source memory system for AI agents next Tuesday called Atlas. Apache 2.0. Builds on Young Bin Park's Kumiho paper (arxiv:2603.17244) but ships open-source, local-first, and extends with automatic downstream reassessment that Park explicitly defers as future work.

The headline numbers:
- 288 tests pass against live Neo4j 5.26
- 49/49 AGM compliance scenarios at 100% (matching Park's published verification)
- Real ingest of 10,604 events from 4 streams in 21.3s (Obsidian + Limitless + Screenpipe + Claude logs)
- Three runtime adapters (Hermes, OpenClaw, Claude Code MCP)
- New benchmark released alongside (BusinessMemBench, MIT, 1,000 questions across 7 categories LoCoMo doesn't test)

Happy to send the repo + paper draft + a 90-second demo video for any coverage you'd consider.

Rich Schefren
strategicprofits.com

(Recipients: editor@importai.net, batch-editor@deeplearning.ai, nathan@interconnects.ai, latentspace@swyx.io, mlst@machine-learning-street-talk.com)

---

## 7. Podcast outreach (Latent Space + MLST)

**Subject:** Atlas launch — would the show want a guest spot?

Hi Swyx (or [host]),

I'm releasing an open-source AGM-compliant cognitive memory system called Atlas next week. The novelty is automatic downstream reassessment — when a belief changes, every dependent belief is recomputed via dependency strength rather than just flagged. Nobody else does this.

Could be a fit for a 45-min episode covering:
- Why "store and retrieve" is the wrong frame for memory
- The AGM postulate substrate (and why no commercial system implements it correctly)
- The MongoDB-vs-Oracle pattern playing out in agent memory
- The Ripple algorithm + how it handles cycles, confidence propagation, and contradiction routing

I'd be the guest. Strategic Profits founder; have shipped systems before; not new to the mic.

Want to do it?

Rich
