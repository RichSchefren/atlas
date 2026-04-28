# Atlas Launch — Overnight Plan (2026-04-27 → 2026-04-28)

**Goal:** Wake up to every channel pre-seeded, every launch artifact polished, every personal DM drafted. Morning is "review → click → click → click," not "where do I start."

**Honest timing reality:**
- Show HN posts overnight in PT die — the morning crowd lands ~8am PT and the algorithm ranks by *velocity in first 30 minutes*. Posting at 1am gives you 0 votes by 8am, then HN's "old post" dampening kicks in and you're invisible.
- Twitter is similar — the people you want to tag (Chalef, Packer, Karan, etc.) are asleep. A 1am tweet won't get the timeline placement you need.
- **The right move tonight: prep, draft, low-stakes seeds. The big buttons get pressed at 8:30am PT tomorrow.**

---

## Tier 1 — What I'll do autonomously overnight (no clicks from you)

### Polish & artifact finalization
- [ ] Replace every `<FILL-IN-AFTER-DOMAIN-REGISTERED>` placeholder in `launch/x_thread.md` and `launch/show_hn.md` with `https://livememory.dev` (and the `livememory.pages.dev` fallback in case the cert hasn't issued).
- [ ] Bump every "446 tests passing / 449 tests passing / etc." stale count to the actual current number (469 as of last commit — verify before final).
- [ ] Update `LAUNCH-PLAYBOOK.md` checkboxes: domain registered ✓, Pages live ✓, video recorded ✓.
- [ ] Add an `og:image` and `twitter:card` meta to `site/index.html` so the URL unfurls cleanly in Slack / X / Discord.
- [ ] Generate a 1200×630 OpenGraph image (HyperFrames composition → render to PNG) — Atlas wordmark + tagline + "livememory.dev" — drop at `site/og.png`.
- [ ] Generate a 1200×600 social-share frame from the video (the moment scene 3 turns red — best single-frame story).

### GitHub repo metadata
- [ ] Set GitHub topics on the repo: `memory`, `knowledge-graph`, `agm`, `belief-revision`, `neo4j`, `llm`, `ai-agents`, `mcp-server`, `local-first`, `open-source`, `ripple`, `cognitive-memory`. (Topics drive GitHub Trending and category discovery.)
- [ ] Tighten the repo `description` field — currently long, should be one tight line.
- [ ] Add `CITATION.cff` so academics get a clean citation block (this is one of the things that gets papers cited later).
- [ ] Pin `LAUNCH-PLAYBOOK.md`, `docs/PROPOSAL_VS_MUTATION.md`, `docs/AGM_COMPLIANCE.md`, `docs/WHY_VECTOR_IS_NOT_ENOUGH.md` on the repo's "Pinned" section so they're the first things visitors see.

### Show HN — fully drafted
- [ ] 3 alternate titles (different angles), with my pick + reasoning:
    - "Show HN: Atlas – AGM-compliant local-first memory that re-evaluates downstream beliefs"
    - "Show HN: Memory that knows when it's wrong (Apache 2.0, local-first, 49/49 AGM)"
    - "Show HN: Open-source Kumiho-class memory with automatic Ripple propagation"
- [ ] Final body for the post — ready to paste, every link tested.
- [ ] **Pre-written Show HN comment** from your account answering the 5 questions HN will predictably ask in the first 30 minutes:
    1. "How is this different from Graphiti?" — answer with the BMB columns we lose vs. win on.
    2. "Why Neo4j and not <X>?" — answer with the bitemporal + APOC story.
    3. "Is this just RAG with extra steps?" — answer with the WHY_VECTOR_IS_NOT_ENOUGH worked example.
    4. "How do I run this without an LLM?" — point at the `[llm]` extra being optional.
    5. "Compliance with what postulates exactly?" — point at AGM_COMPLIANCE.md.
  Drafted, queued. You paste it as the *first comment* on your own Show HN at submission time — sets the tone for the thread.

### X thread — fully drafted
- [ ] 5 alternate lead tweets (different hooks), with my pick + reasoning:
    - **The pricing-change hook (recommended):** "Three weeks ago you priced ZenithPro at $2,995. Yesterday you raised it to $3,495. Every margin claim that quoted the old price is now wrong, and your memory system doesn't know."
    - **The technical hook:** "Kumiho proved AGM-compliant memory is possible (arxiv 2603.17244). They built a commercial cloud. I built the open-source local-first version with one extension: when a fact changes, downstream beliefs are *re-evaluated*, not just flagged."
    - **The contrarian hook:** "Vector retrieval gives you the right document. It does not tell you whether the document is still right."
    - **The provocation:** "Memory that retrieves and memory that reasons are two different problems. The current AI stack is great at the first and silent on the second."
    - **The personal:** "I shipped this because my own team kept making decisions on stale beliefs. Here's the open-source memory layer that catches the propagation when a fact changes."
- [ ] Full 12-tweet thread for the chosen lead, every URL real, video embedded in tweet 2.
- [ ] Dedicated "tag this list, in this order" — Chalef → Packer → Karan @ NousResearch → Jerry Liu → Harrison Chase → Tomaz Bratanic → Vasilije Markovic → Gary Marcus → Park (Kumiho).
- [ ] **Critical:** `https://livememory.dev` opens with the autoplay-muted hero video, so when someone clicks the link from your tweet, they see the loop running before they read a word.

### Personal outreach — drafted, not sent
- [ ] **8 personalized DMs** (each 4–6 sentences, references their specific work, asks for honest feedback not amplification):
    - **Daniel Chalef (Zep / Graphiti)** — "I forked Graphiti as Atlas's substrate. Adding AGM revision + Ripple. Want your honest read on what I got right and what I broke."
    - **Charles Packer (Letta)** — "Letta's block architecture is in Atlas's working-memory layer. Curious what you think of the AGM operator wrapping the typed graph."
    - **Karan @ NousResearch (Hermes)** — "Atlas ships a Hermes MemoryProvider. Read your post on memory backends; here's what AGM compliance looks like as a 9th option."
    - **Jerry Liu (LlamaIndex)** — "If you're shopping for a propagation layer below LlamaIndex's retrieval, here's one. Open-source, local-first, AGM-compliant."
    - **Harrison Chase (LangChain)** — same shape, LangChain's tool surface.
    - **Tomaz Bratanic (Neo4j)** — "Neo4j-based memory layer with bitemporal + AGM revision. Would love a Cypher review of the recursive Ripple cascade."
    - **Vasilije Markovic (Cognee)** — adjacent space, mutual interest.
    - **Young Bin Park (Kumiho)** — *most important one*. Position respectfully: "Your AGM correspondence theorem is the formal foundation. I built the open-source local-first companion. Would love your eyes on the 49-scenario compliance run before launch tomorrow." Tag him in the launch thread *only after* he's seen this DM — otherwise it reads like ambush marketing.

  All 8 saved at `launch/dms.md`, ready to copy-paste into Twitter/LinkedIn DMs.

### Newsletter pitches — drafted
- [ ] **Import AI** (Jack Clark, was Anthropic) — 200-word summary, link to paper draft + repo.
- [ ] **Interconnects** (Nathan Lambert, AI2) — 200-word summary, technical angle.
- [ ] **Latent Space** (swyx) — pitch for podcast appearance.
- [ ] **The Batch** (DeepLearning.AI / Andrew Ng) — submit form.
- [ ] **MLST** (Tim Scarfe) — pitch for podcast.
- All saved at `launch/newsletter_pitches.md`. You send them at 8am.

### Awesome-list PRs — auto-submittable overnight (low-stakes, time-insensitive)
- [ ] PR to `awesome-mcp` adding Atlas as an MCP server entry.
- [ ] PR to `awesome-ai-agents` if applicable.
- [ ] PR to `awesome-knowledge-graph` if applicable.
- [ ] PR to `awesome-local-first` if applicable.
- These don't need traction velocity — they sit until the maintainer reviews. Submit them now, get the review queue ticking.

### CI / hygiene
- [ ] Confirm CI is green on the latest commit (red badge on launch day = death).
- [ ] Verify `./demo.sh` runs cleanly from a fresh clone *with the current `master` SHA* — record the run, drop a transcript at `docs/DEMO_TRANSCRIPT.md` so anyone who wants to verify before installing can read it.
- [ ] Run `make doctor` and confirm 9/9 OK.

### Full click-through QA — every page, every link
- [ ] Click every link on `livememory.dev` (`/`, `/live-demo.html`, `/live-real.html`). Record HTTP status of each + visual sanity check.
- [ ] Click every link on the GitHub README — every internal repo path, every external citation.
- [ ] Click every link in `docs/AGM_COMPLIANCE.md`, `docs/PROPOSAL_VS_MUTATION.md`, `docs/INSTALL_MODES.md`, `docs/WHY_VECTOR_IS_NOT_ENOUGH.md`, `docs/LAUNCH_BACKLOG.md`.
- [ ] Click every link in the X thread draft, Show HN draft, paper draft.
- [ ] Open `livememory.dev` in Chrome + Safari + iPhone (mobile responsive sanity).
- [ ] Verify the OG image actually unfurls — paste `livememory.dev` into Slack, Twitter card validator, LinkedIn post inspector.
- [ ] **This is the bug class Rich hit tonight (footer Docs link → 404 localhost).** Pre-launch, no broken link survives.

### Automated post-launch QA cron (scheduled, recurring)
Rich's request: *"set it all up in a schedule so that nobody has to remember and nobody has to hit anything. We're going to do things more than once."*

- [ ] Create `scripts/qa_site.py` — runs every link on `livememory.dev` + the public GitHub repo + the deployed `livememory.pages.dev` and reports any non-200, any localhost reference, any FILL-IN placeholder. Exits non-zero on any failure.
- [ ] Cron-schedule it via `CronCreate`: every 4 hours during launch week, daily after. Output goes to a log file + a PushNotification on any failure.
- [ ] Same script also checks: GitHub repo description doesn't contain placeholders, GitHub homepage URL is live, repo topics are set, CI is green, video MP4 still serves video/mp4 + has audio stream, custom domains (livememory.dev, www.livememory.dev) status (active vs pending).
- [ ] One-line invocation: `python scripts/qa_site.py` — runs full battery in <30s.

### Promotion calendar — scheduled, not one-shot
Rich's other point: launches happen more than once. The plan tomorrow morning is the *initial* push; this builds the recurring infrastructure.

- [ ] Create `launch/promotion_calendar.md` — a 30-day schedule of *what* to post *where* on *which day*:
    - Day 1: HN Show + X thread + LinkedIn post + 8 personal DMs (the morning launch).
    - Day 2: r/MachineLearning post (different angle than Day 1).
    - Day 3: r/LocalLLaMA + r/Obsidian.
    - Day 5: HuggingFace papers thread.
    - Day 7: Newsletter pitches (Import AI, Interconnects).
    - Day 10: "What we shipped" follow-up post + benchmark deep-dive.
    - Day 14: Submit BMB as its own repo (issue #2).
    - Day 21: Comparison post (Atlas vs Mem0 vs Letta vs Memori).
    - Day 30: Retrospective + month-1 metrics.
  Each entry has the title + a draft body + the right account/channel.
- [ ] Use `CronCreate` to schedule cloud reminders at the right time on each day, with the draft pre-loaded so launch becomes 2 clicks (review + post).

---

## Tier 2 — Things only you can do, queued in exact order for tomorrow morning

### 7:00am PT — Wake & review
1. Open `launch/OVERNIGHT_PLAN.md` (this file). Confirm everything in Tier 1 is checked.
2. Read the 3 Show HN title options + my pick. Reply "1", "2", "3", or rewrite. (~2 min)
3. Read the 5 X-thread lead options + my pick. Reply "1"…"5", or rewrite. (~3 min)
4. Skim the 8 personal DMs. Edit any that don't sound like you. (~10 min)

### 7:30am PT — Personal outreach (warm-launch)
5. Send all 8 DMs. **This is the single highest-leverage 15 minutes of the day.** Park first, others in any order.
6. Send the newsletter pitches.

### 8:30am PT — Big buttons
7. Post Show HN. **Then immediately paste the pre-drafted comment as the first reply on your own post** — primes the thread.
8. T+5min: Post the X thread.
9. T+10min: Post a copy of the launch tweet to LinkedIn (longer-form acceptable there).

### 9:00am PT onward — Engage
10. Respond to every comment on HN within 10 minutes for the first 2 hours. The HN algorithm rewards author engagement.
11. Quote-tweet anyone who shares the launch.

---

## Tier 3 — Channels I will NOT autonomously post to, ever

These need your account, your judgement, and live timing. I'll draft, you click:
- **Hacker News.** Your account, your karma, your timing.
- **X / Twitter.** Same.
- **LinkedIn.** Your professional surface.
- **Reddit (r/MachineLearning, r/LocalLLaMA, r/Obsidian, r/programming).** Each has rules; bad timing or self-promotion ratio kills you. Drafts ready, you decide when to fire.
- **Discord / Slack communities.** Which ones to seed are your call.

---

## Decision needed before you go to sleep

I need a single answer to know what to actually execute autonomously vs. just stage:

> **"Run Tier 1"** — I do all of Tier 1 overnight, no further confirmation needed. You wake up to an inbox of "this is done, this is queued."
>
> **"Run Tier 1 except <X>"** — same but skip specific items.
>
> **"Stage everything, no execution"** — I write all the artifacts but commit nothing, push nothing, submit no PRs. You review every action in the morning before any of it goes out.

If you don't reply, I default to **Stage everything, no execution** — the most conservative path. You wake up to drafts in `launch/`, nothing has gone public, no surprises.

---

## What I'm NOT promising

- I cannot make HN traction happen overnight. Nobody can. We can only stage so morning execution is clean.
- I cannot guarantee the cert lands by morning. If `livememory.dev` is still 525 by 8am, the launch artifacts auto-fall-back to `livememory.pages.dev` (the URL is template-substituted in every artifact, one variable change flips them all).
- I cannot replace your judgment on the 5 lead-hook variants. Pick the one that sounds like *you* talking — copy that goes against your voice tanks instantly.

Sleep well. Reply with a tier directive and I'll execute.
