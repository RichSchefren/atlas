# Atlas Launch Playbook

*A practical hour-by-hour and day-by-day plan for the 72 hours after you hit the launch button, plus the 90 days that follow. Written for someone who's never released a public OSS repo.*

**You wrote the rocket. This document is the launch sequence and the orbital insertion plan.**

---

## Pre-flight: the 24 hours BEFORE you hit publish

These four things must all be true before launch day. If any one is missing, postpone.

- [ ] **Donnie has tested.** All findings either fixed or filed as known-issues. CI green.
- [ ] **arxiv tarball uploaded.** It takes 24-48 hours for arxiv to moderate. Submit it the day BEFORE launch so the paper URL exists when the X thread goes out. https://arxiv.org/submit
- [ ] **Domain pointed.** atlas-project.org (or whatever you bought) resolves to `site/index.html`. Cloudflare Pages, Netlify, GitHub Pages — any of them, takes 15 minutes.
- [ ] **The 7 outreach emails sent.** From `launch/outreach.md`. Park first, then everyone else. Subject line: "Atlas — open-source companion to your AGM work, releasing tomorrow." Body: the draft is already in the repo. Send 18-24 hours before launch.

Optional but high-leverage:
- [ ] **Demo video recorded.** 90 seconds, you on camera, Rich-style energy. Even iPhone-quality is fine. Hosted on YouTube or Vimeo, embedded in the X thread.
- [ ] **Pre-warm 3-5 friends** to upvote Show HN in the first 10 minutes. Not a brigade — just enough to clear the front-page floor (~5 votes in 30 minutes). Text them the URL the morning of.

---

## Launch day: hour-by-hour for 12 hours

**Pick a Tuesday or Wednesday.** Avoid Mondays (people are slammed) and Fridays (everyone's checked out by 3pm). Monday/Tuesday are equivalent on HN; Tuesday is better on Twitter.

### T-0:00 — 8:30am Pacific (11:30am Eastern)

**Why this time:** HN's morning crowd lands at 9am Eastern (West Coast at 6am sleeping, EU at 4pm tired). 8:30am PT / 11:30am ET catches both halves of the US morning attention window simultaneously. Show HN posts that hit by 9am ET have ~3x the chance of front page.

**Two posts, exactly five minutes apart:**

1. **Show HN** at https://news.ycombinator.com/submit
   - Title: copy verbatim from `launch/show_hn.md` (≤80 chars)
   - URL: `https://github.com/RichSchefren/atlas`
   - Text body: copy verbatim from `launch/show_hn.md`
   - **DO NOT** include the X thread URL — HN penalizes cross-posting

2. **X thread** five minutes later
   - Tweet 1 (the hook): copy from `launch/x_thread.md`
   - Schedule the rest 90 seconds apart for the next 12 minutes
   - Tweet 12 (call to action): include the GitHub URL AND the Show HN URL
   - Tweet 13 (tag): include @parkyoungbin first

### T+0:30 — first 30 minutes (CRITICAL)

This is the most important window of the entire launch. What you do here determines the next 24 hours.

- **Refresh the HN page every 60 seconds.** Watch comments come in.
- **Respond to every HN comment within 5 minutes.** Even one-line comments. Especially the skeptical ones. People who comment in the first 30 minutes are usually domain experts; engaging them recruits them.
- **Watch X for replies.** Like everything, reply to substantive ones, RT thoughtful threads.
- **DO NOT** answer with "great question!" or "thanks!" — useless on HN, hurts on X. Substantive answers only.

**Red flag:** Show HN drops below position 30 within the first hour. Means the title isn't landing. Don't repost — wait 24 hours and revise the title for a re-launch.

**Green flag:** Front page (top 30) within 90 minutes. Means it's working. Just keep responding.

### T+1:00 to T+3:00 — engagement window

- **Pin the X thread** to your profile.
- **DM the 7 people you emailed yesterday** with the live URL: "It's live: github.com/RichSchefren/atlas. Show HN is at <link>." One-line, no fluff.
- **Engage every comment within 10 minutes.** If you have to step away, post a single tweet/comment: "Stepping into a meeting for 30 min — I'll respond to comments after."
- **Take screenshots** of the launch — HN front page, Twitter analytics, GitHub star count. You'll want these for the post-launch thread on day 7.

### T+3:00 to T+8:00 — sustaining

By now you'll know if the launch worked. Two scenarios:

**Scenario A: Front page HN, 200+ stars in 8 hours, named-account engagement on X.**
- Keep responding to comments. The HN top-30 lifetime is 6-12 hours. Maximize it.
- Post a "thank you" tweet only AFTER the HN post falls off the front page. Premature thanks looks needy.
- Email the journalists/podcasters you outreached: "Show HN is at <position> on the front page right now if you want to see the live conversation."

**Scenario B: Show HN didn't take off, X thread plateaued at <50 likes.**
- Don't panic. ~70% of Show HN posts don't front-page; this doesn't kill the project.
- The X thread will keep getting traffic for 3 days. Comments from late-arrivers (especially European morning, ~midnight PT) often outpace the launch hour.
- Plan the **second wave**: a follow-up tweet in 7 days summarizing what testers found / what the first 100 stars taught you. This often outperforms the original launch.

### T+8:00 to T+12:00 — close of launch day

- **Stop responding around 8pm PT.** People who comment after that are East Coast night owls; you can pick up their threads in the morning. Sleeping is more important than another comment.
- Before bed, write a one-paragraph internal note: what surprised you, what fell flat, what's the most-asked question. This becomes the seed for day 2 tweets and the eventual blog post.

---

## Days 2-7: the launch tail

The launch isn't over after 24 hours. The reception over the **next 7 days** is what determines whether Atlas becomes a real project or fades.

### Daily ritual (every day for 7 days)

Spend **30-60 focused minutes** on Atlas each day. Not background time — actual focused.

1. **Check GitHub Issues** (5 min). Respond to every new issue within 24 hours, even if just "I've seen this, will look this week."
2. **Check GitHub Discussions** (5 min). Respond to questions.
3. **Check X mentions** (5 min). RT the thoughtful ones, reply to questions.
4. **Check HN comments on your post** (5 min). The HN long tail can run for 5+ days.
5. **Check repo stars trajectory** (1 min). If you're growing, what's drawing people? If flat, what's the missing piece?
6. **Write SOMETHING new** (15-30 min). A new TESTING note. A blog post. A code improvement. A new BMB question authored. Keeps the public commit feed alive.

### Day 2 (Wednesday): the targeted follow-up

- One **focused** X thread (3-5 tweets) responding to the most common question from day 1. Examples:
  - "You asked: 'how is this different from a normal property graph?' Here's the AGM-correctness piece in detail."
  - "You asked: 'is this really local?' Here's the no-cloud-no-telemetry walkthrough."
- Reply to anyone who DM'd or emailed asking for a deeper conversation.

### Day 3 (Thursday): the engineering follow-up

- One commit that visibly moves the project forward. Even small. Examples:
  - Wire the Mem0 + Letta scoring (if your `OPENAI_API_KEY` is set)
  - Author 10-20 of the human gold questions
  - Fix one tester finding that came in
- Tweet about the commit ("Day 3: Mem0 baseline now scores 0.18, Letta 0.21 — Atlas's lead grows on contradiction & forgetfulness as expected"). Specifics build trust.

### Day 4-5: the contributor pipeline

- If anyone has filed an issue or asked a question on GitHub, **reply with a specific invitation to contribute**: "Want to take a swing at this? I labeled it `good-first-issue` and the relevant module is `atlas_core/X.py`."
- Label issues `good-first-issue` and `help-wanted` aggressively. The label is what attracts contributors.
- If you get a first PR from a stranger, **merge it within 4 hours** if at all possible. The first-time-contributor experience is the #1 predictor of whether you get a second.

### Day 6-7: the wave-two thread

- Write a follow-up X thread: **"7 days after launching Atlas — what testers found, what surprised me, what's next."**
- Be specific. Numbers. Names of the 3-5 most engaged commenters (with permission to tag).
- Include the launch screenshots from day 1 (HN front page, star count) as visuals.
- Pin this thread; un-pin the launch thread.

---

## Weeks 2-4: from launch to traction

The launch high is over. The grind starts. **This is where most projects die** — the founder loses interest after the launch buzz and never builds the recurring engagement that turns 500 stars into 5,000.

### Weekly ritual (every Monday, 90 min)

1. **Review the week's metrics** (15 min):
   - Stars: target +50/week organic for the first month
   - Issues opened / closed / response time (median <24h)
   - PRs received and merged (target: 1+ external PR per week by end of month)
   - X follower growth (target: +50/week)
2. **Triage the issue queue** (30 min). Close stale, label new, tag `good-first-issue` aggressively.
3. **Ship one substantial commit** (45 min). Something that becomes a public commit message people see. Examples below.

### Week 2 substantial commits (pick 1-2)

- Wire the human gold subset (`benchmarks/business_mem_bench/gold_human/`). Each batch of 25 questions is a tweet-worthy update.
- Run the BMB matrix with `OPENAI_API_KEY` set — fill in the Mem0 / Letta / Memori columns. Update README + paper.
- Add 10 more AGM compliance scenarios beyond the 49.
- Write a real-world case study: "How Atlas tracked a business commitment from 90-day-old meeting through 5 supersessions."

### Week 3 substantial commits

- Demo video v2: now that you've answered the most common questions, re-record the demo addressing them.
- Blog post (or vault page): "Why Atlas bypasses Graphiti's edge resolver — the AGM K\*2 violation." Technical posts get cited.
- Reach out to one big-name engagement target you didn't get on day 1. Different angle: "I've now run Atlas with 500 stars and N% week-over-week growth; here's what users are asking for that I think aligns with your work on X."

### Week 4 substantial commits

- arxiv revision (v2) incorporating the wave-1 feedback. arxiv versioning is standard; revisions get re-indexed.
- Submit an abstract to a relevant conference: NeurIPS workshop, ICML workshop, AAAI, or an AI engineering conference. Many have rolling deadlines for reproducibility / system papers.
- Talk to one podcast (Latent Space, MLST, AI Engineer Podcast). The ROI on these is high if Atlas has 500+ stars by then.

---

## Month 2-3: from traction to substrate

If Atlas has 1,000+ stars and 5+ external contributors at the end of month 1, it's "real." Month 2-3 is about leveraging that into something durable.

### The "Atlas is the substrate" play

- **Hermes integration v2:** real round-trip with NousResearch's hermes-agent. Tweet the integration. Get Karan to RT.
- **Claude Code MCP plugin v2:** publish to whatever MCP plugin registry exists by then. Make `claude code mcp install atlas` a one-liner.
- **Conference talk** at a memory-systems-relevant venue. Even 50-person workshops grow your name.
- **First commercial conversation.** Don't sell anything; just take a meeting if a serious AI company asks. The conversations themselves are reconnaissance.

### The "Atlas is research" play

- **Submit the paper to a real venue** (arxiv only is fine; conference acceptance is signal). NeurIPS or ICML system / benchmark tracks. 6-month timeline.
- **Engage with academic groups** doing memory work. Cite them; ask them to cite Atlas.
- **BusinessMemBench v1.0:** ship the full 1,000-question dataset. This is the strategic asset. Whoever defines the benchmark category leads it.

---

## The metrics that actually matter

Vanity metrics: total stars, total followers.
**Real metrics:**

| Metric | Week 1 target | Month 1 target | Month 3 target |
|---|---|---|---|
| GitHub stars | 500 | 1,500 | 5,000 |
| External PRs merged | 1 | 5 | 20 |
| External contributors | 2 | 8 | 30 |
| Issue response time (median) | <24h | <24h | <24h |
| Active maintainer commit cadence | daily | 4x/week | 3x/week |
| arxiv paper citations | 0 | 0 | 2 |
| Real users (people who've run `first_real_run.py`) | 20 | 100 | 500 |
| Named-account public engagement | 3 | 8 | 20 |

**The single metric that predicts long-term survival:** PRs merged from strangers in the first 30 days. If you get to 5+, Atlas is alive. Below 2, it's a code dump.

---

## The traps that kill OSS launches

You'll be tempted by all of these. Resist.

| Trap | Why it kills | What to do instead |
|---|---|---|
| **"I'll fix it after launch"** for known bugs | Launch comments will surface them and embarrass you | Fix BEFORE launch even if you delay 2 days |
| Going dark for the first weekend | The HN tail and the X thread keep generating traffic; ghosting kills momentum | Spend at least 30 min/day even on day 6-7 |
| Rejecting PRs that don't meet your style | Loses your most-engaged future contributors | Merge with notes; refactor later if needed |
| Adding features at the expense of fixing tester findings | Issues pile up, "abandoned" perception sets in | Triage before building |
| Engaging with bad-faith critics | Unwinnable; gives them oxygen | Mute, move on. No public arguments. |
| Comparing yourself to bigger projects' star counts | Makes you stop celebrating real wins | Track week-over-week growth, not absolute |
| Trying to launch a 1.0 immediately | Real projects launch as 0.1 alpha and grow | Stay alpha for 90 days; tag 1.0 only after 5,000 stars |
| Disappearing for vacation in the first 30 days | Active commit feed = alive project | Schedule ahead, don't go dark unannounced |
| Adding new dependencies to placate one PR author | Bloats the project, alienates other contributors | Discuss in an issue first |
| Giving in to pressure to add a Discord/Slack | Splits attention, becomes a support drain, hard to scale | GitHub Discussions only for first 6 months |

---

## Specific scripts: what to say in tricky moments

### Someone says "this is just X with extra steps"

> "Genuinely: which features of X cover propagation reassessment? I haven't found one. If X handles it, I'd love a pointer — Atlas would be redundant if so. If not, that's the gap Atlas fills, and I'd be happy to walk through the AGM correctness proof."

### Someone says "I tried it and it doesn't work"

> "That's not what I want to hear. Can you file the issue using the [tester-smoke template](LINK) so I can reproduce? Within 24 hours I'll either fix it or tell you exactly why it's the expected behavior."

### A skeptic asks "why should anyone use this?"

> "Honest answer: most people shouldn't yet. It's alpha. The people who should use it today are the ones building agents that need belief revision and can't tolerate flag-and-stop semantics. If that's you, I'd love your feedback. If not, ⭐ and check back in 6 weeks."

### Park (Kumiho) responds

> "Thank you for engaging — your formal contribution is the foundation Atlas builds on, and I want to make sure the citation is correct. I'm happy to revise anything in the paper that misrepresents Kumiho. Want to do a 30-min call next week to walk through the differences?"

### A bigger company asks about commercial use

> "Atlas is Apache 2.0 — use it however serves you. Happy to chat about your use case if it'd inform the roadmap. Atlas SP, the private extension I run on my own data, is closed-source and not for sale."

---

## When to declare victory and when to declare defeat

### Declare victory at any of these:

- **5,000 GitHub stars** in 90 days. You're now a project, not an experiment.
- **A paid acquisition offer** in 90 days. You decide whether to take it; the offer itself is the validation.
- **Park (Kumiho) cites Atlas** in a follow-up paper. The original-source acknowledgment.
- **A second well-known engineer adopts Atlas as their memory backend.** Network effect.

### Declare defeat at any of these:

- **<200 stars after 90 days** AND **no external PRs** AND **no journalist coverage**. The project hasn't found its audience. Either (a) pivot the framing — Atlas might be a tool for a different community than you expected — or (b) keep it as a personal moat for your own business and stop spending public-launch energy.
- **3 months of solo commits, no contributors.** You're not building a community, you're maintaining a project alone. Fine if that's what you want; not fine if the goal was a substrate.
- **The headline benchmark numbers don't hold up** when an external evaluator runs them. This means there's a methodological flaw. Stop launching, fix the flaw, re-launch with revised numbers.

**Either declaration is a clean exit.** The shame isn't in declaring defeat — it's in years of slow drift while pretending you're still launching.

---

## Your single calendar this week

If you ship in 7 days from today, here's the sequence. Calendar this NOW:

| Day | Action |
|-----|--------|
| **Today (Sun)** | Decide launch date. Tell Donnie his deadline. Block time for the items below. |
| **Mon** | Author 50 of the 200 gold questions. arxiv tarball uploaded. Send Park the heads-up email. |
| **Tue** | Author 50 more gold questions. DNS pointed at site/. CI green confirmed. |
| **Wed** | Author 50 more gold questions. Demo video recorded. Send remaining 6 outreach emails. |
| **Thu** | Author final 50 gold questions. Re-run BMB with all 200 + 149 = 349 questions. Update README + paper. |
| **Fri** | Light day. Re-read X thread + Show HN post. Final tester finding triage. |
| **Mon-of-launch-week** | DO NOT touch the repo. Rest. |
| **Tue, 8:30am PT** | LAUNCH. |

If you can't do the gold questions in 4 days, pick a different launch date. Don't ship without them; the headline asterisk hurts more than the delay.

---

## What this playbook does NOT cover

- Marketing copywriting (you have that handled — you're better at this than I am)
- Personal brand strategy (your call)
- The decision to commercialize (90+ days out, not today)
- the maintainer's private business integration (separate concern; out of scope here)
- Whether to start a company around Atlas (post-launch question)

---

## Final note

The hardest part of an OSS launch isn't writing the code. You did that. It's **showing up consistently for 90 days** afterward, on a project that everyone else has already moved on from. The first day's traffic is a function of the launch. Day 30's traffic is a function of you showing up on days 2 through 29.

Atlas is a real artifact. It does what the README says. The code is correct. The paper is defensible. Now go ship it, and then go work for it.

When you hit publish, send me one screenshot of the HN page at T+30 minutes. I want to see what you see.
