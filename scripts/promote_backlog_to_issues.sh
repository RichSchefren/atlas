#!/usr/bin/env bash
# Promote unchecked items from docs/LAUNCH_BACKLOG.md to labeled GitHub issues.
#
# Idempotent: re-running won't create duplicates as long as the issue
# titles haven't drifted (it greps existing issue titles before
# creating). Safe to run after each backlog edit.
#
# Spec: docs/LAUNCH_BACKLOG.md → P2 'Promote backlog entries to GitHub issues'.

set -euo pipefail

REPO="RichSchefren/atlas"

# ─── Labels ──────────────────────────────────────────────────────────────────
# Six tier-and-theme labels — created once; ignored if they already exist.
declare -a LABEL_SPECS=(
  "credibility|#b60205|Public-facing claims, badges, README accuracy — keeps Atlas honest"
  "onboarding|#0e8a16|First 10 minutes — quickstart, doctor, errors, expected output"
  "benchmark|#1d76db|BusinessMemBench / AGM compliance / LoCoMo / LongMemEval"
  "docs|#0075ca|Documentation pages, READMEs, install guides"
  "architecture|#5319e7|Engine, AGM, Ripple, trust, ingestion, sharing"
  "polish|#fbca04|Lint, CI infra, dev ergonomics, small visible improvements"
)

_LABELS_CACHED=""

_ensure_labels_cached() {
  if [ -n "$_LABELS_CACHED" ]; then return; fi
  # gh label list with --search filters server-side but is fuzzy; fetch
  # the full list and grep locally for exact-match guarantees.
  _LABELS_CACHED=$(gh label list --repo "$REPO" --limit 200 --json name -q '.[].name')
}

ensure_label() {
  local name=$1 color=$2 desc=$3
  _ensure_labels_cached
  if echo "$_LABELS_CACHED" | grep -qx "$name"; then
    echo "  = label  $name"
    return
  fi
  gh label create "$name" --color "${color#\#}" --description "$desc" \
      --repo "$REPO" >/dev/null
  echo "  + label  $name"
  _LABELS_CACHED="$_LABELS_CACHED"$'\n'"$name"
}

# ─── Issues ──────────────────────────────────────────────────────────────────
# Each entry: title|labels (csv)|body file (heredoc literal, single-line escaped)
#
# Bodies are kept intentionally short — the issue is a pointer back to
# docs/LAUNCH_BACKLOG.md, not a duplicate of it.

_OPEN_TITLES_FILE=""

_ensure_open_titles_cached() {
  # Cache all open issue titles once, then exact-match against that list.
  # gh's --search "in:title ..." was missing exact phrases so we list +
  # filter ourselves.
  if [ -n "$_OPEN_TITLES_FILE" ] && [ -f "$_OPEN_TITLES_FILE" ]; then
    return
  fi
  _OPEN_TITLES_FILE=$(mktemp)
  # 200 issues is plenty for our backlog scale; bump if it grows.
  gh issue list --repo "$REPO" --state open --limit 200 \
      --json title -q '.[].title' > "$_OPEN_TITLES_FILE"
}

create_issue_if_missing() {
  local title=$1
  local labels=$2
  local body=$3
  _ensure_open_titles_cached
  if grep -Fxq "$title" "$_OPEN_TITLES_FILE"; then
    echo "  = exists  $title"
    return
  fi
  local url
  url=$(gh issue create --repo "$REPO" --title "$title" \
      --label "$labels" --body "$body")
  echo "  + issue  $url"
  # Append the new title so later calls in the same run dedup correctly.
  echo "$title" >> "$_OPEN_TITLES_FILE"
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
  echo "Ensuring labels exist on $REPO ..."
  for spec in "${LABEL_SPECS[@]}"; do
    IFS="|" read -r name color desc <<<"$spec"
    ensure_label "$name" "$color" "$desc"
  done

  echo
  echo "Creating issues for unchecked LAUNCH_BACKLOG items ..."

  create_issue_if_missing \
    "Record 90-second demo GIF / video for the README hero" \
    "polish,onboarding" \
    "Tracks the unchecked P1 item in [docs/LAUNCH_BACKLOG.md](../blob/master/docs/LAUNCH_BACKLOG.md).

Three takes (~30s each):

1. \`./demo.sh\` running, loop closes — no narration needed; the terminal output speaks.
2. Neo4j Browser at \`http://localhost:7474\` after the demo, Cypher queries from the README's Browser-query block, watch the graph repaint when a fact changes.
3. Atlas pinned as an MCP server in Claude Code, agent surfaces a contradiction live.

Embed at the top of the README. Hosted on YouTube or Vimeo.

Needs Rich on camera (or a screen recording with voiceover). Cannot be auto-generated."

  create_issue_if_missing \
    "Split BusinessMemBench out into its own MIT-licensed repository" \
    "benchmark,docs" \
    "Tracks the unchecked P2 item in [docs/LAUNCH_BACKLOG.md](../blob/master/docs/LAUNCH_BACKLOG.md).

Currently \`benchmarks/business_mem_bench/\` lives inside Atlas. To make BMB adoptable as a memory-system benchmark by anyone (Mem0, Letta, Memori, Kumiho, MemPalace teams), split into:

- \`RichSchefren/businessmembench\` (new repo, MIT) — corpus generator, scoring rubric, harness, CLI runner, gold subset
- \`RichSchefren/atlas\` — \`benchmarks/business_mem_bench/\` becomes a thin adapter that pip-installs the public package and provides Atlas-specific glue

Acceptance:
- BMB repo public + pip-installable
- Atlas's BMB adapter still runs identically against the package
- The 149-question seed=42 baseline output still checks in (or moves to the new repo's \`runs/\`)
- README-level cross-link from each repo to the other"

  create_issue_if_missing \
    "Wire continuous-capture daemons (Limitless / Fireflies / Screenpipe / Claude logs / iMessage)" \
    "architecture,onboarding" \
    "Discovered during launch-backlog work. Tracks the gap called out in \`docs/INSTALL_MODES.md\` Mode 2 ('what you skip').

Per-source extractors exist in \`atlas_core/ingestion/\` but enabling them on a fresh machine needs platform-specific setup not yet documented. Ship:

- \`docs/CAPTURE_SETUP.md\` — one section per source with the exact env-var + path config
- A \`make capture\` Makefile target that runs the ingestion daemon under \`launchd\`-equivalent on macOS / \`systemd\` on Linux
- Smoke tests for each extractor against fixture data so onboarding can verify before turning on real capture

Out of scope for the alpha release; tracked here so it doesn't drift."

  create_issue_if_missing \
    "Write the arxiv paper draft (paper/atlas.md)" \
    "docs,benchmark" \
    "8-12 page paper, working title: 'Atlas: Forward Implication Propagation for Continuously-Updated Cognitive World Models'.

Sections (per Phase 3 plan):

1. Introduction
2. Related Work — Kumiho, Graphiti, Memori, Letta, Hindsight, OMEGA cited
3. Architecture — typed graph + AGM operators + Ripple
4. The Ripple Algorithm — analyze_impact / reassess / contradiction / routing
5. Domain Ontology — 8 entity types
6. Evaluation — BusinessMemBench (149q seed=42 baseline checked in), AGM compliance (49/49), LongMemEval + LoCoMo (predicted, not measured)
7. Limitations
8. Open Problems

The AGM compliance + BMB reproducibility artifacts are already checked in; the paper cites them with file paths so reviewers can audit. Reproducibility = release \`benchmarks/\` directory + eval harness + datasets at submission."

  create_issue_if_missing \
    "Register a launch domain and point Cloudflare Pages at site/" \
    "onboarding,polish" \
    "The repo currently has zero domain references (sanitization commit \`1c3aadc\`). Once Rich picks a name + registers, every reference flips on at once via a single auditable commit:

1. Update \`README.md\` hero with the live demo URL
2. Update \`launch/x_thread.md\` and \`launch/show_hn.md\` placeholders
3. Update \`paper/atlas.md\` reproducibility section
4. Update \`LAUNCH-PLAYBOOK.md\` [ ] Domain registered + pointed checkbox

Candidate names verified available as of 2026-04-27 (see assistant transcript): \`atlasripple.dev\`, \`atlas-memory.dev\`, \`ripplememory.dev\`. Recommendation: \`atlasripple.dev\` — names both product and differentiator, .dev is at-cost on Cloudflare Registrar, forces HTTPS.

Cannot be done autonomously — needs Rich's Cloudflare account + payment method. Tracked here to keep visible."

  echo
  echo "Done."
}

main "$@"
