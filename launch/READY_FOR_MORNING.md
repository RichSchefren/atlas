# Atlas Launch — Ready for Morning

**Generated:** 2026-04-27 (overnight)
**You wake up to:** every artifact copy-paste-ready, ordered by clock time. No decisions, just clicks.

> **First action when you wake up:** open https://livememory.pages.dev (and check if `https://livememory.dev` finally has its cert — if not, every artifact below already has the `pages.dev` fallback). Confirm the video plays with sound after one click. If anything's broken, the QA monitor will have already pushed you a notification — but eyeball-confirm anyway.

---

## State of the world (verified live as of overnight push)

- ✅ `https://livememory.pages.dev` — site live, video autoplays muted, "Click to play with sound" overlay works
- ✅ Video has audio (88s, 5.6 MB, AAC stereo, narrated by `bm_george`)
- ✅ OG card unfurls beautifully (1200×630, branded ATLAS / livememory.dev)
- ✅ Favicon (gold A on dark) shows in browser tabs
- ✅ All 10 footer + nav links return 200 (verified via `qa_site.py`)
- ✅ GitHub repo: description tightened, 20 topics set, homepage = `livememory.dev`
- ✅ All stale numbers fixed (469 tests, 13 MCP tools, 49/49 AGM scenarios — consistent everywhere)
- ✅ launchd cron `com.atlas.qa` runs 6× daily, catches future drift
- 🟡 `livememory.dev` cert — pending (Cloudflare provisioning, see DNSSEC note below)

---

## ~7:00am PT — Decisions you make in 5 minutes

### Decision 1: Show HN title

Pick one. My recommendation: **#1**.

1. **`Show HN: Atlas – AGM-compliant local-first memory that re-evaluates downstream beliefs`**
   *Strong technical specificity, names the differentiator. HN crowd respects formal claims.*
2. `Show HN: Memory that knows when it's wrong (Apache 2.0, local-first, 49/49 AGM)`
   *Hookier. Puts the value-prop first, badges in parens.*
3. `Show HN: Open-source Kumiho-class memory with automatic Ripple propagation`
   *References Kumiho — free credibility but only if reader recognizes the name.*

### Decision 2: X / Twitter thread lead

Pick one. My recommendation: **#1** (the worked-example hook).

1. **The pricing-change hook:** *"Three weeks ago you priced ZenithPro at $2,995. Yesterday you raised it to $3,495. Every margin claim that quoted the old price is now wrong, and your memory system doesn't know."*
2. The technical hook: *"Kumiho proved AGM-compliant memory is possible (arxiv 2603.17244)..."*
3. The contrarian hook: *"Vector retrieval gives you the right document. It does not tell you whether the document is still right."*
4. The provocation: *"Memory that retrieves and memory that reasons are two different problems."*
5. The personal: *"I shipped this because my own team kept making decisions on stale beliefs."*

### Decision 3: Are the DMs in `launch/dms.md` in your voice?

Read the 8 drafts. Edit any line that sounds like me, not you. (Estimated 5 min.)

---

## ~7:30am PT — Personal outreach (the highest-leverage 15 min of your day)

Open `launch/dms.md`. Send all 8. **Send Park first** — he's the most sensitive recipient (we cite his paper prominently, he should hear from you before he sees the launch tweet).

The list:

1. **Young Bin Park** (Kumiho) — Twitter or via the email on his arxiv paper
2. **Daniel Chalef** (Zep / Graphiti) — Twitter @danielchalef
3. **Charles Packer** (Letta) — Twitter @charles_packer
4. **Karan @ NousResearch** (Hermes) — Twitter
5. **Jerry Liu** (LlamaIndex) — Twitter @jerryjliu0
6. **Harrison Chase** (LangChain) — Twitter @hwchase17
7. **Tomaz Bratanic** (Neo4j) — Twitter @tb_tomaz
8. **Vasilije Markovic** (Cognee) — Twitter @vasilije_m

Then send the newsletter pitches in `launch/newsletter_pitches.md` — Import AI, Interconnects, Latent Space, The Batch, MLST.

---

## ~8:30am PT — Big buttons (in order)

1. **Show HN.** Go to https://news.ycombinator.com/submit. Title from Decision 1. URL = `https://livememory.dev` (or `livememory.pages.dev` if cert still pending). **Then immediately paste the pre-written first comment from `launch/show_hn_first_comment.md` as a reply on your own post.** (Sets the tone for the thread, primes the predictable HN questions.)

2. **T+5min: X thread.** Go to twitter.com. Paste the thread from `launch/x_thread_FINAL.md`. Tag order in the last tweet: `@danielchalef @charles_packer @tomasonjo @hwchase17 @jerryjliu0 @vasilije_m @garymarcus`. Tweet the link to your Show HN as a quote-reply on your own thread.

3. **T+10min: LinkedIn post.** Paste `launch/linkedin.md`. Image attachment = `site/og.png`.

---

## ~9:00am PT onward — Engage

- **HN: respond to every top-level comment within 10 minutes** for the first 2 hours. The HN ranking algorithm rewards author engagement. The first 30 minutes determine front-page placement.
- **Twitter: quote-tweet anyone who shares it.** Don't argue, but do clarify if someone misreads.
- **Don't post to other channels in the first 2 hours** — concentration of attention beats spread.

---

## Reddit drafts (post throughout the day, NOT in the first 2 hours)

`launch/reddit_drafts.md` has 4 drafts, each with a different tone matching the subreddit:
- **r/MachineLearning** — formal, technical, leads with AGM math
- **r/LocalLLaMA** — practical, leads with "no cloud, runs on your laptop"
- **r/Obsidian** — leads with the markdown adjudication queue
- **r/programming** — leads with Apache 2.0 + the open-source angle

Sequencing: post r/LocalLLaMA at ~10am PT (highest hit rate), r/Obsidian at noon, r/MachineLearning later (don't compete with HN attention), r/programming next day.

---

## Awesome-list PRs (already submitted overnight, no action required)

Status of each PR is in `launch/awesome_pr_status.md`. Maintainers typically merge within 24–72 hours. Each merge = passive ongoing eyeballs over the next several weeks.

---

## Cert status — `livememory.dev` vs `livememory.pages.dev`

If the cert hasn't issued by morning:

1. Check status: `python3 scripts/qa_site.py` (will tell you which host serves what).
2. If still 525 after 24 hours, two clicks fix it:
   - GoDaddy → DNS Management for `livememory.dev` → DNSSEC tab → ensure DNSSEC is **OFF**
   - Cloudflare → SSL/TLS → Edge Certificates → re-trigger Universal SSL provisioning
3. Until cert lands, every launch artifact uses `livememory.pages.dev` as the URL — that's a real Cloudflare-served URL, totally legitimate, just less branded.

---

## What I (Claude) am running while you sleep

- 🟢 launchd `com.atlas.qa` — runs `qa_site.py` 6× daily, logs to `~/.atlas/qa.log`, catches link rot
- 🟢 GitHub repo metadata polished (topics, description, homepage)
- 🟢 Site polished (OG image, favicon, social meta, all 3 HTML pages clean)
- 🟢 All artifacts written to `launch/` directory and committed

When you wake up, open `launch/READY_FOR_MORNING.md` (this file). Confirm everything checked, then execute the morning sequence above.

---

## If anything went wrong overnight

- The QA monitor logs to `~/.atlas/qa.log`. Tail the last 50 lines to see history.
- `git log --oneline | head -10` shows what I committed.
- `gh pr list --author @me` won't work (I posted as you, with your gh token) — use `gh pr list -A RichSchefren --state open` to see what awesome-list PRs are out for review.

Sleep well. The work I can do tonight is done.
