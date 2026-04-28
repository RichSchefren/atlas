# Atlas — Personal DMs (drafted, send tomorrow ~7:30am PT)

Each DM is short (4–6 sentences), references their specific work, and asks for honest feedback rather than amplification. Read each, edit any line that doesn't sound like you, then send.

**Send Park first.** He's the most sensitive recipient — we cite his paper prominently and the launch leans on his AGM correspondence theorem.

---

## 1. Young Bin Park (Kumiho) — SEND FIRST

**Channel:** Email if available on his arxiv paper (preferred), Twitter DM as fallback.

> Subject: Atlas — open-source companion to your AGM correspondence work
>
> Young Bin —
>
> I'm Rich Schefren. I've spent the last three months building the open-source local-first companion to your Kumiho contribution (arxiv 2603.17244). It's called Atlas. The repo: github.com/RichSchefren/atlas. Public launch is tomorrow morning Pacific time.
>
> The relationship I'd want with your work, made explicit: Atlas re-implements your AGM operators (K*2–K*6 + Hansson Relevance + Core-Retainment) as open-source local-first infrastructure, runs the same shape of 49-scenario compliance suite (passes 100%), and extends with one thing — Ripple — that re-evaluates downstream beliefs automatically when an upstream fact changes, rather than just flagging them.
>
> I want you to see this before the rest of the world does. The 49-scenario reproducibility artifact is at docs/AGM_COMPLIANCE.md in the repo. The paper draft (which cites you prominently as the formal foundation) is at paper/atlas.md.
>
> If you have feedback, I'd rather hear it now than at launch. If you're cool with the framing, I'd love to tag you in the launch thread tomorrow morning.
>
> — Rich

---

## 2. Daniel Chalef (Zep / Graphiti)

**Channel:** Twitter @danielchalef (DM)

> Daniel — Rich Schefren. I've been head-down on a memory project that forks Graphiti as the storage substrate. It's called Atlas — open-source local-first, AGM-compliant revision (49/49 scenarios), automatic downstream reassessment when facts change. Apache 2.0.
>
> Launching tomorrow at livememory.dev. Wanted you to see it before the launch thread because (a) the comparison table on the site has Graphiti in it, and (b) I'd genuinely love your read on what I got right and what I broke vs. your bitemporal model.
>
> Repo: github.com/RichSchefren/atlas. Honest feedback welcome.

---

## 3. Charles Packer (Letta)

**Channel:** Twitter @charles_packer (DM)

> Charles — Letta's block architecture is in Atlas's working-memory layer. I cite Letta in the install-modes doc as the right answer for "agent stack with memory built in." Different problem class than what I'm shipping (long-lived business beliefs + AGM revision), but Atlas slots underneath your stack rather than competing.
>
> Launching tomorrow morning at livememory.dev. Repo at github.com/RichSchefren/atlas. Curious what you think of the AGM operator wrapping the typed graph.

---

## 4. Karan @ NousResearch (Hermes)

**Channel:** Twitter (find handle in NousResearch member list)

> Karan — Atlas ships a Hermes MemoryProvider (`atlas_core.adapters.hermes.AtlasHermesProvider`). I've been tracking the 8 existing memory backends in your ecosystem — Atlas would be the 9th and the only AGM-compliant one.
>
> The repo's at github.com/RichSchefren/atlas, public launch tomorrow morning at livememory.dev. The adapter passes a stdio + gRPC integration test against a live Neo4j; happy to walk through the integration if you want to formally onboard it as a supported backend post-launch.

---

## 5. Jerry Liu (LlamaIndex)

**Channel:** Twitter @jerryjliu0 (DM)

> Jerry — quick note. I'm shipping Atlas tomorrow morning — open-source local-first cognitive memory with AGM-compliant belief revision. The premise: vector retrieval gives you the right document but doesn't tell you whether the document is still right. Atlas's Ripple algorithm reassesses downstream beliefs the moment a fact changes.
>
> Most natural place in a LlamaIndex stack: as the propagation layer below your retrieval. Repo: github.com/RichSchefren/atlas. Launch link tomorrow ~8:30am PT at livememory.dev.

---

## 6. Harrison Chase (LangChain)

**Channel:** Twitter @hwchase17 (DM)

> Harrison — Rich Schefren. Shipping Atlas tomorrow — open-source AGM-compliant memory layer with automatic downstream reassessment when facts change. Local-first (Neo4j + SQLite ledger), Apache 2.0, MCP / FastAPI / gRPC surfaces.
>
> Atlas's natural integration point in LangChain's tool surface: a memory backend that catches stale-belief failures retrieval can't. Repo at github.com/RichSchefren/atlas. Live tomorrow ~8:30am PT at livememory.dev. Would love your read.

---

## 7. Tomaz Bratanic (Neo4j)

**Channel:** Twitter @tb_tomaz (DM)

> Tomaz — I've built a Neo4j-backed memory layer with bitemporal validity windows + AGM-compliant revision (the Kumiho operators) + a recursive Cypher implementation of forward implication propagation. Open-source, launching tomorrow at livememory.dev.
>
> The Cypher I'm proudest of (and most worried about) is in `atlas_core/ripple/analyze_impact.py` — a max-depth bounded recursive walk with cycle detection across `:DEPENDS_ON` edges. Would deeply value a Neo4j-expert review when you have a sec.
>
> Repo: github.com/RichSchefren/atlas.

---

## 8. Vasilije Markovic (Cognee)

**Channel:** Twitter @vasilije_m (DM)

> Vasilije — adjacent space. I'm shipping Atlas tomorrow — open-source local-first AGM-compliant memory with automatic downstream reassessment. The differentiator from Cognee: domain-typed business ontology + Ripple propagation when facts change.
>
> Repo at github.com/RichSchefren/atlas. Launch link goes live ~8:30am PT tomorrow at livememory.dev. Curious where you see the overlap and where the orthogonal value lies.

---

## Tone notes

- Each DM names *their* specific contribution, not just generic flattery.
- Each asks for *feedback*, not amplification. Maintainers see "would you share this?" 50× a day; "would you tell me what I got wrong?" is rare and gets read.
- The Park DM is the longest by design. He's getting cited; he should hear it from you, and the framing has to be exactly right.
- Don't BCC anyone. Don't send the same message to two people. Each one is hand-customized.
- Park gets first send so he can object before launch. The rest can go in any order.
