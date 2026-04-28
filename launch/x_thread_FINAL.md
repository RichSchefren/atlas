# X / Twitter Thread — Final (with my recommended lead)

**Lead chosen:** worked-example hook (option #1 in `READY_FOR_MORNING.md`). It's the strongest because it lands the failure mode in 2 sentences before reaching for technical credibility.

**Posting time target:** 8:35am PT (5 min after Show HN goes live).

**Tagging strategy:** tags appear ONLY in the final tweet. No tag-mining in the thread itself — that triggers Twitter's spam filters and dampens reach.

---

## Tweet 1 / hook

> Three weeks ago you priced ZenithPro at $2,995. Yesterday you raised it to $3,495. Every margin claim that quoted the old price is now wrong, and your memory system doesn't know.
>
> Atlas does. ↓

*(attach the 88s narrated launch video as native media — autoplays on the timeline)*

---

## Tweet 2 / what it is

> Atlas is open-source local-first cognitive memory with AGM-compliant belief revision. When a fact changes, downstream beliefs are automatically re-evaluated, not just flagged.
>
> Apache 2.0. Local-first (no cloud). 469 tests passing. https://livememory.dev

---

## Tweet 3 / the differentiator (the actual jewel)

> The differentiator is an algorithm called Ripple. It walks the typed DEPENDS_ON graph the moment a fact lands in the ledger, recomputes confidence on every downstream belief, and surfaces emergent contradictions to a markdown adjudication queue you resolve in Obsidian.
>
> No other memory system ships propagation. Vector retrieval can't catch this — by the time you query, the answer is stale.

---

## Tweet 4 / the math

> Atlas implements the AGM postulates K*2–K*6 plus Hansson Relevance and Core-Retainment. Same formal correctness Kumiho's commercial paper proved (arxiv 2603.17244), running as fully open-source local-first code anyone can audit.
>
> 49 of 49 scenarios pass at 100%. Reproducibility artifact: https://github.com/RichSchefren/atlas/blob/master/docs/AGM_COMPLIANCE.md

---

## Tweet 5 / what's in the box

> What ships:
> • 469 tests passing against live Neo4j 5.26
> • 13 MCP tools (Claude Code, Hermes, OpenClaw adapters)
> • 8-entity domain ontology shipped by default
> • Hash-chained SHA-256 ledger with verify_chain()
> • Six ingestion streams (vault, transcripts, screen, sessions)
> • BusinessMemBench harness — 149-question reproducible head-to-head

---

## Tweet 6 / honest about what it isn't

> What Atlas isn't, because honesty wins more than puffery:
>
> Not a chatbot UI. Not a Letta replacement (Letta runs agents; Atlas is the memory layer below). Not a managed cloud. Not yet good at extracting from truly unstructured free-text.
>
> README has the full "what we do worse" table.

---

## Tweet 7 / why I built this

> I built this because my own team kept making decisions on stale beliefs. A price changed in a meeting on Monday; by Wednesday three downstream commitments were quoting the old number. The memory layer should have caught it. None of them do.
>
> Atlas is the one that does.

---

## Tweet 8 / the demo

> The 12-second demo: clone, docker compose up, ./demo.sh. Watch the loop close end-to-end against a real Neo4j — no mocks, no stubs.
>
> The 6-second demo: open https://livememory.dev and click play.
>
> The 30-second demo: `make demo-messy` runs the same loop on a real vault note + meeting transcript.

---

## Tweet 9 / for researchers

> For researchers: the paper draft is at https://github.com/RichSchefren/atlas/blob/master/paper/atlas.md. Cites Kumiho's correspondence theorem prominently. Reproducibility artifacts (AGM compliance + BMB seed=42 baseline) are committed to the repo with their generating scripts.

---

## Tweet 10 / for builders

> For builders integrating into agent stacks:
> • MCP server: `python -m atlas_core.adapters.claude_code` (drop into ~/.claude/.mcp.json)
> • Hermes: `AtlasHermesProvider` from atlas_core.adapters.hermes
> • OpenClaw: plugin factory at atlas_core.adapters.openclaw
>
> Read-only vs. mutation classification: docs/PROPOSAL_VS_MUTATION.md

---

## Tweet 11 / where this goes next

> What's next: BMB split into its own MIT repo so any memory system can adopt it. Continuous-capture daemons for Limitless / Fireflies / Screenpipe / Claude logs. arxiv submission. The 30-day roadmap is in docs/LAUNCH_BACKLOG.md — every item is a tracked GitHub issue you can comment on.

---

## Tweet 12 / the ask + tags

> If you build with memory in agent stacks, I'd love to hear what breaks. If you've shipped a memory system, I'd love your honest read of where Atlas overlaps vs. complements.
>
> Repo: https://github.com/RichSchefren/atlas
> Show HN: https://news.ycombinator.com/item?id=<INSERT-HN-ID-AFTER-POSTING>
>
> @danielchalef @charles_packer @tomasonjo @hwchase17 @jerryjliu0 @vasilije_m @garymarcus
