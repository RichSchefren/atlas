# Awesome-list PRs — drafted, you submit (~10 min total in the morning)

Each PR below is fully drafted: README diff, PR title, PR body. Submit at ~9:30am PT after the HN/X attention has peaked but is still active.

**Why I didn't auto-submit:** the permission guard correctly blocked unsolicited fork+PR under your identity. Submitting these is a 30-second action per list once you're logged in.

**Pacing:** stagger them across the day — one at 9:30, one at 11:00, one at 1:30pm. Maintainers see "5 PRs from same user in 5 minutes" as spam; spaced out, they read as "this person actually shipped something today."

---

## PR #1: punkpeye/awesome-mcp-servers

**Repo:** https://github.com/punkpeye/awesome-mcp-servers
**Why this list first:** Most active MCP-focused awesome list (~3.5k stars), maintainers are responsive, audience is exactly your target (MCP server builders).

**5-step submission:**
1. Open the repo in browser → Fork (top-right button)
2. In your fork, edit `README.md` directly via the GitHub web UI (pencil icon)
3. Find the section that fits — likely "Knowledge & Memory" or "Other" (search the README for similar entries)
4. Insert this line in alphabetical order:

```markdown
- [Atlas](https://github.com/RichSchefren/atlas) – Open-source local-first cognitive memory with AGM-compliant belief revision. Automatic downstream reassessment when facts change. 13 MCP tools (Ripple, AGM, ledger, adjudication). Apache 2.0.
```

5. Commit message: `Add Atlas — AGM-compliant local-first memory MCP server`
6. Open PR with title `Add Atlas — AGM-compliant local-first memory MCP server` and this body:

```
Hi! Adding Atlas, an open-source local-first cognitive memory MCP server I just released.

What it is:
- AGM-compliant belief revision (49/49 postulate scenarios at 100%)
- Automatic forward implication propagation when facts change (algorithm: Ripple)
- 13 MCP tools covering analyze_impact, reassess, contradiction detection, adjudication, ledger verification
- Local-first (Neo4j + SQLite), Apache 2.0
- 469 tests passing, demo in 12 seconds

Live: https://livememory.dev
Repo: https://github.com/RichSchefren/atlas

Happy to adjust placement / wording per the list's conventions.
```

---

## PR #2: e2b-dev/awesome-ai-agents

**Repo:** https://github.com/e2b-dev/awesome-ai-agents

**5-step submission:**
1. Fork on GitHub
2. Edit `README.md` (or `agents.md` — check what the list uses)
3. Find the section for memory / knowledge / context engines
4. Insert (alphabetical order):

```markdown
- [Atlas](https://github.com/RichSchefren/atlas) – Open-source local-first AGM-compliant memory layer for AI agents. Automatic downstream reassessment when facts change. Hermes / OpenClaw / Claude Code adapters. Apache 2.0.
```

5. PR title: `Add Atlas — AGM-compliant memory layer for AI agents`
6. PR body:

```
Adding Atlas — a memory layer that ships with three agent-runtime adapters (Hermes MemoryProvider, OpenClaw plugin, Claude Code MCP).

Differentiator vs. other entries: when a fact changes, downstream beliefs are automatically re-evaluated, not just flagged. AGM-compliant (49/49 scenarios), local-first, Apache 2.0.

Repo: https://github.com/RichSchefren/atlas
Live: https://livememory.dev
```

---

## PR #3: Hannibal046/Awesome-LLM

**Repo:** https://github.com/Hannibal046/Awesome-LLM

**5-step submission:**
1. Fork on GitHub
2. Edit `README.md`
3. Search for "Memory" — there should be a Memory or Knowledge section
4. Insert:

```markdown
- [Atlas](https://github.com/RichSchefren/atlas) - Open-source local-first cognitive memory with AGM-compliant belief revision and automatic downstream reassessment. ![](https://img.shields.io/github/stars/RichSchefren/atlas.svg?style=social)
```

(Many large awesome-LLM lists include the GitHub stars badge; matches existing entry style — verify the convention before submitting.)

5. PR title: `Add Atlas — AGM-compliant local-first memory layer`
6. PR body:

```
Adding Atlas — open-source local-first cognitive memory with AGM-compliant belief revision (the K*2–K*6 postulates from Alchourrón-Gärdenfors-Makinson, Kumiho's paper extended to open-source).

The novel contribution is automatic downstream reassessment: when a fact changes, every belief that depended on it is re-evaluated, not just flagged. 49/49 compliance scenarios pass at 100%. 469 tests passing. Apache 2.0.

Repo: https://github.com/RichSchefren/atlas
Paper draft: https://github.com/RichSchefren/atlas/blob/master/paper/atlas.md
```

---

## Optional 4th: modelcontextprotocol/servers

**Repo:** https://github.com/modelcontextprotocol/servers

**Why optional:** This is the *official* MCP servers list. Stricter merge bar, slower review cycle. Worth submitting because of the credibility halo, but don't lead with it (they may want a more thorough adapter implementation first). Submit *after* PR #1 lands.

**Defer until 24-48h after launch.** Better signal: "this project has community traction (HN front page, 200+ stars), now it's worth being on the official list" than "submit on day 1."

---

## How to know if the PRs land

- Track each in your GitHub notifications.
- If a maintainer asks for changes (placement, wording, badge style), respond within 12 hours — fast response signals seriousness.
- Don't escalate or re-PR if rejected. One PR per list per launch. If rejected, the next move is to ship more, then try again in 6 months.

## What this gets you

Per merged PR: 50–500 ongoing eyeballs over the next 6 months as the awesome-list propagates through GitHub Trending, blog roundups, and "starting with X" search queries. Compounds slowly but persistently.
