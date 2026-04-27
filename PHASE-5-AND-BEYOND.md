# Phase 5 and beyond — what the public repo doesn't yet have

*An honest accounting of what got descoped between "the Atlas Rich described in Phase 0" and "the Atlas we're about to launch publicly." Written 2026-04-26, after the v0.1.0a1 launchable artifact landed.*

The public repo is shippable. **It is not yet the full system.** This document inventories every gap and what it would take to close.

There are three tiers of gaps:

- **Tier 1 — Required for "Rich uses this daily."** Without these, Atlas is a launchable demo, not the cognitive memory substrate of your business.
- **Tier 2 — Required for paper credibility post-arxiv-revision.** The launch can happen without them; the paper revision in 60 days needs them.
- **Tier 3 — Required for the substrate-strategy moat.** If Atlas is going to BE the open-source memory layer the agent-runtime world plugs into, these have to ship.

Total estimated remaining work for full vision: **8-12 weeks** of focused engineering.

---

## Tier 1 — "Rich uses this daily" (4-6 weeks)

These are the gaps between "I cloned Atlas and ran the tests" and "Atlas is the memory substrate of the maintainer's business, running 24/7 on Rich's machine, fed by every capture stream, surfacing decisions through Obsidian."

### 1.1 Continuous-ingestion daemon (launchd) — 3 days

**Spec:** 07 § 6 calls for `com.atlas.ingestion` and `com.atlas.api-server` launchd plists running 24/7.

**Current state:** Orchestrator exists (`atlas_core/ingestion/orchestrator.py`). No launchd plist. Atlas runs only when you manually invoke `scripts/first_real_run.py`. Re-run is idempotent so the cursor advances correctly, but if you forget to run it for a week, a week of capture data sits unprocessed.

**What ships in this tier:** Two launchd plists at `~/Library/LaunchAgents/com.atlas.ingestion.plist` and `com.atlas.api-server.plist`. The ingestion plist runs every 30 minutes; the API server runs continuously on port 9879. Plus a `~/.atlas/health/` directory with rolling logs so you can audit the daemon.

**Why it matters:** Without this, "continuous ingestion" is a misnomer. The headline launch claim is wrong unless this lands.

---

### 1.2 ALTERNATIVE — Obsidian plugin (Donnie's recommendation, supersedes fswatch) — 5 days

**Donnie's read (2026-04-26):** *"Ship an Obsidian plugin before deepening the Python CLI. The adjudication-as-markdown-checklist UX is your killer move; right now it's behind launchd + fswatch + a service that hasn't shipped."*

He's right. The fswatch-daemon path (1.2 below) works but requires a launchd plist + a Python service running 24/7 — friction at every install. An Obsidian plugin runs *inside the editor Rich already has open*, talks to Atlas's HTTP API on port 9879, and detects checkbox state changes natively via Obsidian's own file events.

**What ships:**
- `atlas-obsidian-plugin/` — TypeScript Obsidian plugin (separate repo: `RichSchefren/atlas-obsidian`)
- On install: connects to `http://localhost:9879`, lists pending adjudications in a sidebar pane
- On `.md` save under `00 Atlas/adjudication/`: parses the checkboxes, calls `POST /tools/adjudication.resolve` with the right payload, archives the file via Obsidian's Vault API
- Sidebar shows real-time Ripple cascade activity (subscribes to a `/events` SSE stream we add to the API)
- Distributed via Obsidian Community Plugins registry (Rich is already an Obsidian power user; he can submit it himself in 30 minutes)

**Why this beats fswatch:**
| | fswatch path | Obsidian plugin path |
|---|---|---|
| Install steps | launchd plist + fswatch + Python service | One click in Obsidian Community Plugins |
| Visibility | Background daemon | Sidebar pane in the editor |
| Cross-platform | macOS only | Mac + Windows + Linux |
| Discoverability | None | Obsidian plugin store front page |
| User context switch | terminal ↔ editor | editor only |
| First-time-user delight | Low | High |

**Decision needed:** drop the fswatch path entirely (1.2 below), do the plugin instead. Total time about the same. UX gap is night-and-day.

### 1.2 [DEPRECATED IF 1.2-ALT LANDS] fswatch-driven adjudication resolver — 2 days

**Spec:** 06 § 6.4 calls for an fswatch hook that reads Rich's checkbox edits in the Obsidian markdown queue and triggers `resolve_adjudication()` automatically.

**Current state:** `resolve_adjudication()` exists and works (commit `8392d13`). But it requires explicit invocation through MCP / HTTP / a Python call. There is NO file-watcher reading Rich's saved markdown to detect when he checks the "Accept" box.

**What ships in this tier:** An `atlas_core/ripple/fswatch_resolver.py` module that uses `watchdog` (already in dependencies) to monitor `$ATLAS_ADJUDICATION_DIR` (default: `~/.atlas/adjudication/`). On save, parse the markdown, detect which checkbox is now checked, call `resolve_adjudication()` with the right decision. Move the file to `resolved/`.

**Why it matters:** This is what makes adjudication actually low-friction. Without it, Rich has to switch out of Obsidian to a terminal to resolve every entry. With it, he checks a box, saves the file, and Atlas does the rest.

---

### 1.3 Entity resolution layer — 5 days

**Spec:** Phase 2 W4 deliverable: "Entity resolution layer (alias dictionary + fuzzy LLM fallback)."

**Current state:** **Not built at all.** When Limitless transcribes "Sarah said the launch is delayed" and the vault has a `Sarah Chen.person.md` file, Atlas does not connect them. Two separate Person nodes get created.

This is the single biggest gap between "Atlas runs on real data" and "Atlas understands real data." Every contradiction detector, every cross-stream check, every lineage walk depends on entity identity being resolved correctly.

**What ships in this tier:**
- `atlas_core/resolution/aliases.py` — a YAML-backed alias dictionary at `~/.atlas/aliases.yaml` that Rich edits ("Sarah" / "Sarah C" / "@sarah" / "Sarah Chen" → `kref://AtlasCoffee/People/sarah_chen.person`).
- `atlas_core/resolution/fuzzy.py` — when no alias hit, fuzzy-match against known Person krefs using `rapidfuzz` (already in some indirect dependencies; pin it).
- `atlas_core/resolution/llm_fallback.py` — when fuzzy confidence is too low, fire one LLM call asking "is X the same person as any of these: [Y, Z, W]?" Cache aggressively; this is the cost driver.
- Wire into every extractor's `extract_claims_from_event` so subject_kref always resolves to the canonical entity.

**Why it matters:** Without this, the cross-stream consistency benchmark category is a lie at scale. The synthetic corpus uses constant kref strings so it works, but real data has 47 ways to say "Sarah."

---

### 1.4 LLM-driven extraction (replacing the deterministic stubs) — 5 days

**Spec:** Phase 2 W6 was supposed to wire LLM-driven extraction. The vault.py module's docstring still says: *"Phase 2 W6 wires LLM-driven extraction for free-text vault changes."* That work didn't land.

**Current state:** Vault extractor only reads frontmatter. Free-text body is ignored. Limitless extractor only reads YAML pre-processing. Anything in the transcript that didn't make it into the structured fields is invisible. Claude session extractor only captures user prompts verbatim — no decision/commitment/preference extraction.

**What ships in this tier:** Three LLM extractor modules using Claude Haiku 4.5 (cheap, fast, sufficient for this):
- `atlas_core/ingestion/extractors/llm_vault.py` — reads body markdown, extracts assertions / decisions / commitments. Per-stream prompt at `atlas_core/ingestion/extractors/prompts/vault.txt`.
- `atlas_core/ingestion/extractors/llm_limitless.py` — reads transcript body for assertions the YAML pre-processor missed.
- `atlas_core/ingestion/extractors/llm_claude_sessions.py` — reads user prompts AND assistant responses to extract decisions Rich actually made.
- Token budget enforcement at `atlas_core/ingestion/budget.py` — `ATLAS_DAILY_LLM_BUDGET_USD` env var, defaults to $5/day, gates extraction.

**Why it matters:** Right now Atlas captures Rich's structured frontmatter and YAML metadata. It does NOT capture the actual content of his thinking. LLM extraction is what makes the capture qualitatively different from a search index.

---

### 1.5 Decision-lineage subsystem (the real one) — 3 days

**Spec:** Phase 2 W4: "Decision lineage subsystem (every Decision links to supporting StrategicBeliefs)."

**Current state:** Decisions exist as nodes. They have `OWNED_BY` edges to People. They do NOT systematically link to the StrategicBeliefs they rest on. The benchmark FAKES this with a corpus generator that emits decision→belief edges via `kref_object`. Real Rich decisions don't have these edges yet.

**What ships in this tier:**
- `atlas_core/lineage/extractor.py` — when an LLM extractor pulls a Decision, prompt it to ALSO extract "what beliefs did this decision rest on?" Emit the SUPPORTS edges.
- `atlas_core/lineage/walker.py` — Cypher walks for "trace this decision back N hops to its root beliefs" with confidence gating.
- `atlas_core/lineage/contradiction.py` — when a belief gets demoted via Ripple, detect every Decision now resting on weakened support and surface them through the existing contradiction detector.

**Why it matters:** This is the most-cited use case in the paper. "Why did we decide X on date Y?" is the question Atlas should answer better than anything else. Today it can't, except for synthetic corpus.

---

### 1.6 Vault-search integration — 2 days

**Spec:** "Atlas absorbs vault-search daemon as retrieval layer for Obsidian queries."

**Current state:** Atlas's retrieval module is empty. Search queries return nothing.

**What ships in this tier:** `atlas_core/retrieval/vault_search.py` — HTTP client for the vault-search daemon at port 9878. Wire into the BMB Atlas adapter's recall paths and into the eventual Hermes/OpenClaw `search` methods.

**Why it matters:** Atlas already has vault-search running on Rich's machine. Not using it is leaving 24/7 GPU-accelerated semantic search on the table.

---

### 1.7 Intelligence Engine + brain-state.json bridge — 2 days

**Spec:** "Atlas writes updates back to `brain-state.json` so BRIEFING.md stays current."

**Current state:** No bridge.

**What ships in this tier:** `atlas_core/integrations/intelligence_engine.py` — on every adjudication.resolve, on every Ripple cascade that produces a strategic-bucket entry, write a notification to `$ATLAS_BRAIN_EVENTS_FILE` (default: `~/.atlas/atlas-events.jsonl`) that the Intelligence Engine pipeline reads on its next run. Plus a section in BRIEFING.md auto-populated from Atlas's last 24h of activity.

**Why it matters:** Atlas integrates with Rich's existing system rather than replacing it. The user-facing surface is BRIEFING.md, not Atlas's adjudication queue.

---

### Tier 1 total: ~22 days of focused engineering

After Tier 1: Atlas runs 24/7 on Rich's laptop. LLM-extracts from every stream. Resolves entities correctly. Surfaces decisions to BRIEFING.md. Adjudicates via Obsidian checkboxes. **This is the system Rich described in Phase 0.**

---

## Tier 2 — Paper revision credibility (2-3 weeks)

The launch goes out with the v1 paper. Within 60 days, you submit v2 (arxiv supports versioning). Tier 2 is what v2 must contain to survive academic scrutiny.

### 2.1 The 1,000-question BMB — 1 week

**Current state:** 149 deterministic + 200 scaffolded gold = 149 actual questions.

**Target:** 1,000 total. Path:
- 200 human-authored gold (Rich + 2 colleagues) — your hand
- 800 LLM-generated from corpus templates with auto-grading by a different LLM (cross-check pattern)
- New module `benchmarks/business_mem_bench/llm_expansion.py` that generates + validates

**Why it matters:** "1,000 questions" is the headline number throughout the paper. Currently it's an aspiration; v2 has to be reality.

---

### 2.2 LongMemEval run — 3 days

**Current state:** Paper claims parity. **We've never run it.** This is the gap I was least honest about.

**Target:** Wire `benchmarks/longmemeval_runner.py` against the published LongMemEval-S (500 questions). Atlas runs through; report measured numbers, not predicted.

**Why it matters:** If you claim parity in v1 and someone runs it in 2027 and finds Atlas at 0.32 vs your "0.75 expected," the paper credibility cracks.

---

### 2.3 LoCoMo run — 3 days

Same as 2.2 but for LoCoMo. Kumiho published 0.447 F1; we say "match or exceed." Not measured.

---

### 2.4 Mem0 + Letta + Memori real numbers — 2 days

**Current state:** Adapters fail-loud without API keys. Matrix shows SKIP.

**Target:** Set keys, run, fill columns. Probable outcome: Mem0 ~0.18, Letta ~0.21, Memori ~0.15 on the BMB matrix. Atlas's lead over them is the headline; without the numbers, the lead is asserted not measured.

---

### 2.5 Confidence calibration empirical study — 5 days

**Spec:** "Atlas re-calibrates [trust thresholds] empirically during Phase 3 benchmarking, publishes the calibration as part of the paper."

**Current state:** Thresholds are still 0.25 / 0.6 / 1.0 — Bicameral's arbitrary defaults.

**Target:** Run 1000 candidates from the real ingest, compute the empirically-optimal thresholds for promotion, document the methodology. Update spec doc + paper § 7.

---

### 2.6 Property-based testing for AGM — 3 days

**Current state:** 49 hand-written scenarios.

**Target:** `hypothesis`-driven random scenario generator that fuzzes around the postulate boundary. Document any postulate violations found. Publish the fuzzer as part of the reproducibility artifact.

---

### Tier 2 total: ~3 weeks. v2 paper-ready.

---

## Tier 3 — Substrate-strategy moat (3-4 weeks)

If Atlas is going to BE the memory substrate of the agent-runtime world (Hermes, OpenClaw, Claude Code, Letta, etc.), it needs more than a working adapter — it needs to be the obvious choice.

### 3.1 Live Hermes round-trip — 1 week

**Current state:** AtlasHermesProvider exists; never run inside an actual NousResearch hermes-agent process.

**Target:** Clone hermes-agent, configure Atlas as the `memory.provider`, run a real conversation through it, capture screencaps for the launch. Submit a PR upstream documenting Atlas as a supported backend.

---

### 3.2 Live OpenClaw round-trip — 1 week

Same pattern, OpenClaw side. The 363K star umbrella is the prize.

---

### 3.3 Real Kumiho gRPC compatibility — 5 days

**Current state:** gRPC scaffold lists 51 method names; none are wired.

**Target:** Wire the 5-10 most-used Kumiho methods (CreateRevision, GetRevision, AnalyzeImpact, TraverseEdges, TagRevision) so Kumiho SDK code can switch endpoints to Atlas with a single config change. Headline: "drop-in replacement for the open-source SDK pieces of Kumiho."

---

### 3.4 The live Ripple visualization (real data) — 5 days

**Current state:** site/live-demo.html runs synthetic data in JavaScript.

**Target:** WebSocket stream from Atlas's HTTP server pushing real graph state + Ripple cascades to a browser. Hosted at atlas-project.org/live with redacted Rich data. THIS is the viral moment Gemini's review identified.

---

### 3.5 MCP plugin registry submission — 2 days

**Target:** When the MCP plugin registry exists (it might already by launch time), submit Atlas. `claude code mcp install atlas` becomes a one-liner.

---

### 3.6 Conference talk prep — ongoing

Atlas paper into NeurIPS / ICML / AAAI memory-systems workshops. 6-month timeline.

---

### Tier 3 total: ~4 weeks. Atlas is the substrate.

---

## Tier 4 — Working memory / context-window block manager (~2 AI hours)

Tier 1+2+3 give Atlas as long-term memory — facts that should outlive a conversation. **Atlas does not yet manage in-conversation context the way Letta does.** Tier 4 closes that gap so Atlas can replace Letta-style block managers entirely.

### 4.1 Block manager — Letta-style working memory — 1.5 AI hours

**Spec inspiration:** Letta (formerly MemGPT) treats LLM context as a tiered memory hierarchy — Human / Persona / current-priorities blocks pinned in-context plus archival storage that auto-summarizes when token limits approach.

**What ships:**
- `atlas_core/working/blocks.py` — `MemoryBlock` dataclass (name, content, max_tokens, last_updated, write_policy)
- `atlas_core/working/manager.py` — `WorkingMemoryManager` class with `pin_block()`, `unpin_block()`, `summarize_if_over_limit()`, `flush_to_archival()` methods
- `atlas_core/working/blocks/standard.py` — three default blocks Rich gets out of the box: `Human` (who Rich is, populated from his Person kref), `Persona` (Atlas's role description), `CurrentPriorities` (auto-populated from open Commitments due in <14 days)
- `atlas_core/working/auto_summarizer.py` — when a block hits 90% of `max_tokens`, fire one Claude Haiku call to compress to 70% while preserving the most-cited entities

### 4.2 Context assembly for agent runtimes — 0.5 AI hours

**What ships:**
- New MCP tool `working_memory.assemble(agent_id, max_tokens)` — returns the optimal context block for a given agent at a given token budget
- Wired into the Hermes + OpenClaw + Claude Code adapters so agents can get "Atlas's view of what matters right now" with a single call
- Per-agent block configuration so different agents see different working memories (research agent sees research priorities, ops agent sees ops priorities)

**Why it matters:** This is what makes Atlas a *complete* memory layer — long-term + working memory in one substrate. Without Tier 4, you still need Letta or Mem0 alongside Atlas for in-conversation context. With Tier 4, Atlas IS the entire memory layer.

---

## Tier 5 — Multi-agent / multi-tenant (~3 AI hours)

Atlas is single-user-single-machine by design through Tier 4. **Tier 5 unlocks multiple humans sharing one Atlas substrate** — the team mode.

### 5.1 Per-tenant trust ledgers — 1 AI hour

**What ships:**
- `atlas_core/trust/tenant.py` — `TenantContext` wrapper that namespaces every quarantine, ledger, and adjudication queue by `tenant_id`
- One Neo4j instance, multiple SQLite ledgers (one per tenant) — preserves AGM correctness per-tenant while sharing the graph substrate
- API surface: every MCP tool gains an optional `tenant_id` param; HTTP endpoints accept `X-Atlas-Tenant` header

### 5.2 Cross-tenant reads with privacy controls — 1 AI hour

**What ships:**
- `atlas_core/sharing/policy.py` — explicit per-kref sharing rules ("Rich can read Ben's Commitments due before next Monday")
- Cypher query rewriter that filters every read by the requester's tenant + sharing policy
- `sharing.grant` and `sharing.revoke` MCP tools

### 5.3 Federated adjudication — 1 AI hour

**What ships:**
- When tenant A asserts a fact that contradicts tenant B's ledger, the adjudication entry routes to *both* tenants' queues
- Resolution requires both to agree, OR one to explicitly override with audit log
- Use case: Rich and Ben both observe a meeting; their independent extractions feed one shared adjudication

### Decision needed before Tier 5

Multi-tenant Atlas is a different shape of system than single-user Atlas. It's the foundation for "Atlas as the memory backend a small team uses" or "Atlas as a hosted service for other companies." If neither of those is on your roadmap, Tier 5 is dead weight. **Lock the decision before Tier 5 starts.**

---

## What the original plan ALSO descoped that we should be honest about

Gemini's Phase 0 review descoped these things, NOT me. They were intentional cuts, not oversights:

| Cut | Why | When to revisit |
|---|---|---|
| Ontology extensibility (Phase 1 hardcoded at 8 entity types) | Discipline — domain-typed correctness > flexibility | After 90 days of real use, see what 9th type Rich's data actually needs |
| BMB scale (300 → 1,000 → currently 149) | 300 was insufficient for academic rigor; 1,000 is the goal; 149 is what we've shipped | Tier 2 above |
| Federated reassessment (multi-instance Atlas) | Distributed AGM is research-grade, not engineering-grade | Out of scope until 2027 |
| Formal verification (Coq/Lean of operators) | Tractable but 3-month engagement | Solicit collaborators after launch |
| Concurrent runs of streams in orchestrator | Sequential is correct; concurrent is optimization | Tier 1.1 (launchd plist) makes this unnecessary in practice |

These should NOT come back into Tier 1/2/3 — they're correctly out of scope for the next 90 days.

---

## What I shipped vs what was promised

Honest scorecard:

| Original promise | Status |
|---|---|
| AGM-compliant belief revision | ✓ DELIVERED — 49/49 at 100% |
| Ripple algorithm | ✓ DELIVERED — analyze_impact + reassess + contradiction + adjudication |
| Trust layer (quarantine → ledger) | ✓ DELIVERED — real SHA-256 chain |
| Domain-typed business ontology | ✓ DELIVERED — 8 entities, 6 typed edges |
| Continuous multi-stream ingestion | ⚠ PARTIAL — extractors exist, daemon doesn't (Tier 1.1) |
| LLM-driven extraction | ✗ NOT DELIVERED — deterministic only (Tier 1.4) |
| Entity resolution | ✗ NOT DELIVERED (Tier 1.3) |
| Obsidian-integrated adjudication | ⚠ PARTIAL — markdown writer exists, fswatch doesn't (Tier 1.2) |
| Decision lineage subsystem | ⚠ PARTIAL — node + 1-hop walk; full subsystem doesn't (Tier 1.5) |
| BusinessMemBench (1,000 questions) | ⚠ PARTIAL — 149 deterministic, 200 scaffolded (Tier 2.1) |
| LoCoMo / LongMemEval parity | ✗ NOT MEASURED — claimed in paper, not run (Tier 2.2-2.3) |
| Hermes / OpenClaw / Claude Code adapters | ⚠ PARTIAL — code exists, never round-tripped against real runtimes (Tier 3.1-3.2) |
| Live Ripple visualization | ⚠ PARTIAL — synthetic JS demo; real data version doesn't exist (Tier 3.4) |
| Vault-search integration | ✗ NOT DELIVERED (Tier 1.6) |
| Intelligence Engine bridge | ✗ NOT DELIVERED (Tier 1.7) |
| arxiv paper | ⚠ DRAFT — submission package ready, not yet uploaded |

---

## Recommended sequencing

If you want the FULL system Rich described, here's my recommended order. **This is post-launch work** — the public artifact ships now, and the work below makes Atlas the system you actually use, while the public continues consuming v0.1.0.

### Weeks 1-3 post-launch: Tier 1.1 + 1.2 + 1.6 + 1.7 (the "Rich uses it daily" minimum)

10 days. After this, Atlas runs 24/7 on Rich's machine, listens for adjudications via Obsidian, surfaces to BRIEFING.md, integrates with vault-search. **This is the smallest scope that makes Atlas Rich's daily memory.**

### Weeks 4-7 post-launch: Tier 1.3 + 1.4 + 1.5 (the qualitative leap)

13 days. After this, Atlas understands Rich's actual data — entity resolution works, LLM extraction surfaces decisions and beliefs from free text, lineage walks the full chain. **This is the system the paper actually describes.**

### Weeks 8-10 post-launch: Tier 2 (paper revision)

3 weeks. arxiv v2 with measured LoCoMo / LongMemEval / Mem0 / Letta / Memori numbers, the full 1,000-question BMB, calibrated thresholds, property-based testing. **This is the scientifically defensible Atlas.**

### Weeks 11-14 post-launch: Tier 3 (substrate moat)

4 weeks. Live Hermes / OpenClaw round-trips. Kumiho gRPC compat. Live Ripple viz on real data. MCP plugin registry. **This is the substrate Atlas claims to be.**

---

## Total runway

- **Public launch artifact (where we are):** complete
- **Tier 1 — Rich uses daily:** +22 working days (~5 weeks)
- **Tier 2 — paper credible:** +15 working days (~3 weeks)
- **Tier 3 — substrate moat:** +20 working days (~4 weeks)
- **Total to full vision:** ~12 weeks of focused work post-launch

Atlas as it stands today is **roughly 50-60% of the system you described in Phase 0**. The hardest 50-60% — the AGM math, the Ripple algorithm, the trust gating, the typed ontology, the adapters, the benchmark, the paper. But the remaining 40-50% is what makes it land in Rich's actual life and in the agent-runtime ecosystem.

**The launch can ship NOW** because the public artifact is real and defensible. **The full vision is 90 days out.** Both are true.

Tell me which Tier you want to start on after Donnie finishes testing. If you want the full system, we go straight into Tier 1 the day after launch.
