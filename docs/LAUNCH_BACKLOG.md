# Atlas — Launch Backlog

This file tracks the expanded improvement list from Codex's second
review (2026-04-27) and any other items required between alpha and
public launch. **Every entry is concrete enough that a working session
can pick it up without re-discovery.** When an item is shipped, mark
the box, paste the commit hash, and link the artifact.

The North Star — what every entry below should serve:

> *Atlas is a local-first graph memory system that tracks dependencies
> between beliefs, and when a fact changes, reassesses downstream
> beliefs instead of merely retrieving old context.*

Don't let the framing drift into "universal memory substrate" yet.
The propagation-aware belief-revision loop is the jewel.

---

## P0 — Credibility Blockers (ship before launch)

- [x] **Stale public numbers fixed.** Test count badge now reads 450
      and is wired to live GitHub Actions. (`336e5ad`, `<this commit>`)
- [x] **`RippleEngine` stub resolved.** `atlas_core/ripple/engine.py`
      is the real orchestrator. (`05290ca`)
- [x] **BMB defensibility — disclaimer + checked-in run + status
      column.** Each adapter row is now labeled `measured` /
      `skipped`. Run JSON at
      `benchmarks/business_mem_bench/runs/baseline_seed42.json`.
      (`14cb32c`, `<this commit>`)
- [x] **Messy real-world demo.** `scripts/demo_messy.py` runs the full
      pipeline on `examples/messy_demo/note_zenith_pricing.md` (vault
      note) + `examples/messy_demo/transcript_pricing_meeting.md`
      (Limitless-style transcript). Deterministic regex extraction (no
      API keys), six-stage output shape parallel to `./demo.sh`,
      ~6s on warm Neo4j. Regression test at
      `tests/integration/test_demo_messy.py`. (`606f67a`)
- [x] **Alpha framing visible & proud.** Sub-badge line on README.
      (`<this commit>`)

## P1 — First 10 Minutes

- [x] **`make` commands.** `setup`, `neo4j`, `neo4j-down`, `demo`,
      `test`, `lint`, `bench`, `bench-agm`, `bench-bmb`, `doctor`,
      `clean`. (`<this commit>`)
- [x] **`scripts/doctor.py`.** Checks Python, Docker, compose, Neo4j
      Bolt port, APOC version, `~/.atlas` writability, `.env`
      (optional), `atlas_core` import, pytest collect count.
      (`<this commit>`)
- [x] **Friendly demo failure messages.** Preflight in
      `scripts/demo_loop.py`. (`7b83b23`)
- [x] **Quickstart points to `./demo.sh`.** (`6be4e91`)
- [x] **"What you should see" expected output.** README block plus
      ledger semantics line in the demo itself. (`<this commit>`)

## P1 — Product Clarity

- [x] **What Atlas is *not*.** Explicit four-bullet section.
      (`<this commit>`)
- [x] **Define the user.** "Who Atlas is for, today" section with
      four user shapes. (`<this commit>`)
- [x] **Three concrete use cases.** Pricing change, partner exit,
      deadline slip — with a one-line description of what Atlas does
      in each. (`<this commit>`)
- [ ] **90-second GIF / video.** Needs Rich on camera (or a screen
      recording). Three takes:
        - 0–15s: open laptop, type `./demo.sh`, watch the loop close.
        - 15–60s: open Neo4j Browser, run the dependency-edge query,
          show a fact change live, watch the graph repaint.
        - 60–90s: pin Atlas as the MCP server in Claude Code, ask
          a question, show it surface a contradiction.
      Embed at the top of the README and link from
      `docs/LAUNCH_BACKLOG.md` so future contributors can see the
      target.
- [x] **Neo4j Browser query block in README.** Four canned Cypher
      queries a curious visitor can paste into the browser at
      `localhost:7474` after `./demo.sh`. (`<this commit>`)

## P1 — Engineering Hygiene

- [x] **Ruff clean (0 violations).** (`7b83b23`)
- [x] **Ruff in CI as a gate.** `lint` step in
      `.github/workflows/test.yml`. (`<this commit>`)
- [x] **`.gitignore` covers `neo4j-data/`, caches.** (`7b83b23`)
- [x] **`pyproject` URLs point at `RichSchefren/atlas`.** (`131ec36`)
- [x] **Heavy LLM/embedding deps moved to optional extras.**
      (`b9bf770`)
- [x] **Python 3.13 / 3.14 in classifiers.** (`<this commit>`)
- [x] **GitHub Actions matrix on Python 3.10–3.14.** `test.yml` now
      runs the full pytest + AGM compliance + BMB matrix on every
      supported interpreter (3.10, 3.11, 3.12, 3.13, 3.14) with
      `fail-fast: false` so one bad version doesn't mask others.
      Each Python's BMB artifact is uploaded under a version-suffixed
      name. `allow-prereleases: true` so 3.14 builds don't block on
      release-candidate naming. (`71c0bd9`)

## P1 — Architecture Questions

- [x] **Candidate fingerprint excludes lane** so cross-lane corroboration
      works. (`7b83b23`)
- [x] **Cross-lane corroboration test.**
      `tests/unit/test_quarantine.py::test_cross_lane_same_claim_dedups_and_corroborates`.
      (`7b83b23`)
- [x] **Real orchestrated `RippleEngine`.** (`05290ca`)
- [x] **Ledger semantics in demo.** Demo now prints what
      `last_verified_sequence` means and why a small number is
      expected on the first run. (`<this commit>`)
- [x] **Proposal-vs-mutation explicit in API surface.**
      `docs/PROPOSAL_VS_MUTATION.md` classifies every public method in
      `atlas_core/ripple/`, `atlas_core/revision/`, `atlas_core/trust/`,
      and the 13 MCP tools in `atlas_core/api/mcp_server.py` into
      READ-ONLY / PROPOSAL / MUTATION buckets. The invariant — *no
      typed-graph mutation happens automatically as part of Ripple
      propagation* — is enforced by an AST-based regression test
      (`tests/unit/test_proposal_vs_mutation.py`) that parses every
      `session.run(...)` call in the cascade modules and fails CI if a
      Cypher write keyword leaks into one. (`16e8fcd`)

## P2 — Viral / Adoption (post-launch nice-to-haves)

- [x] **"Why vector memory is not enough" page.**
      `docs/WHY_VECTOR_IS_NOT_ENOUGH.md` — concrete worked example
      (ZenithPro pricing change three weeks before the question), one
      mermaid diagram contrasting vector-only vs. Atlas, generalization
      paragraph, "what this is not" section so the doc isn't an attack
      on RAG / Mem0 / Letta. Linked from README's "What Atlas is not"
      section. Backed by 4 doc-smoke tests in
      `tests/unit/test_docs_why_vector.py` that guard the worked
      example's concrete numbers, the mermaid diagram balance, and the
      README link. (`1885208`)
- [ ] **Publish BusinessMemBench as its own repo.** Currently lives
      inside Atlas. Split into `RichSchefren/businessmembench` (MIT)
      so other memory systems can adopt it without forking Atlas.
      Atlas's `benchmarks/business_mem_bench/` becomes a thin
      adapter that pip-installs the public package.
- [x] **Comparison humility.** README now has a "What Atlas does
      *worse* (today)" subsection directly under the head-to-head
      comparison table. Six concrete rows, each naming the alternative
      to reach for and the reason: pure-retrieval throughput, chat
      memory, managed cloud / support, zero-config setup, multi-user
      concurrency, NL extraction quality. Closes with explicit
      "if your criteria match these rows, use the alternative" —
      better to lose the wrong-fit user than to over-claim and lose
      their trust later. (`625165e`)
- [ ] **Install modes** (researcher / Obsidian power-user / agent-
      runtime integration). Document each in
      `docs/INSTALL_MODES.md` so the right user lands on the right
      install path on first read.
- [ ] **Promote backlog entries to GitHub issues** with labels
      `credibility`, `onboarding`, `benchmark`, `docs`,
      `architecture`, `polish`. Lets external contributors see
      where help is welcome.

---

## Convention

- When you ship an item, change `[ ]` to `[x]` and append the commit
  hash in parentheses. Keep the entry — it's the audit trail.
- When you discover a new item that fits this list, add it in the
  appropriate P-tier and tag it `(new YYYY-MM-DD)` so the
  archaeology stays clean.
- The North Star at the top of this file is load-bearing. If a
  proposed item doesn't sharpen the propagation-aware belief-revision
  pitch, push it to P3 (or kill it).
