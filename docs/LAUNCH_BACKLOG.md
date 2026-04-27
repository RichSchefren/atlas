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
- [ ] **Messy real-world demo.** The current `./demo.sh` runs a
      synthetic loop on planted nodes. Build a second demo
      `scripts/demo_messy.py` that:
        - Ingests a real markdown note + a Limitless-style transcript
          snippet checked into `examples/messy_demo/`
        - Runs the full extraction → quarantine → ledger → Ripple →
          adjudication path on that input
        - Prints the same six-stage output shape so a viewer sees
          parity with the synthetic demo
      Targets: ≤ 30 seconds end-to-end, no external API keys
      required (use the offline extractor stubs).
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
- [ ] **GitHub Actions matrix on Python 3.10–3.14.** Currently CI
      runs only on 3.12. Add `strategy.matrix.python-version` so
      every supported interpreter is exercised on every PR.

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
- [ ] **Proposal-vs-mutation explicit in API surface.** Audit the
      `atlas_core/ripple/` and `atlas_core/api/` surface to ensure
      every method that *proposes* a change is named with the verb
      `propose_*` and every method that *mutates* the graph goes
      through `adjudication.resolve()` or the AGM revise/contract
      operators. Add a docs page `docs/PROPOSAL_VS_MUTATION.md`
      that lists every method in each category.

## P2 — Viral / Adoption (post-launch nice-to-haves)

- [ ] **"Why vector memory is not enough" page.** One concrete
      worked example: vector retrieval surfaces the right document,
      but the document's claim is now superseded; Atlas would have
      caught the contradiction. Target: 600 words, one diagram, link
      from README hero.
- [ ] **Publish BusinessMemBench as its own repo.** Currently lives
      inside Atlas. Split into `RichSchefren/businessmembench` (MIT)
      so other memory systems can adopt it without forking Atlas.
      Atlas's `benchmarks/business_mem_bench/` becomes a thin
      adapter that pip-installs the public package.
- [ ] **Comparison humility.** Add a "what Atlas does *worse*" sub-
      section under the comparison table — concrete deficits we
      know about today (no real-time chat memory, no managed cloud,
      slower for pure-retrieval queries than a vector DB, etc.).
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
