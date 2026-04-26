# Human-authored gold subset

The 200-question gold-standard subset of BusinessMemBench. Authored by Rich + 2 colleagues against the Atlas Coffee Roasting Co. corpus. Counterweight to the 149 deterministic synthetic questions: stress-tests Atlas on the messy, ambiguous queries operators actually ask.

## Status

- Target: 200 questions (40 + 30 + 30 + 30 + 30 + 20 + 20 = per-category counts mirroring §3 of `notes/08 - BusinessMemBench Design.md`)
- Authored: 0 (you're holding the empty bag — fill it)
- Validated by harness: 0

## How to author

Each question goes in `<category>.jsonl`, one JSON object per line. Schema matches the synthetic gold files (which are the implementation reference):

```json
{
  "id": "prop_human_001",
  "question": "If we drop the Origins price by 25% AND simultaneously raise the Reserve price by 30%, does Atlas reassess the 'broad accessibility' belief differently than if we only changed Origins?",
  "scoring": "binary_in_band",
  "correct_answer_band": {"min": 0.4, "max": 0.7},
  "upstream_kref": "kref://AtlasCoffee/Programs/p01.program",
  "old_confidence": 0.9,
  "new_confidence": 0.6,
  "is_human_authored": true,
  "_authored_by": "rich",
  "_rationale": "Tests cascade interaction between two simultaneous upstream changes — the synthetic generator only changes one thing at a time."
}
```

## Per-category templates

Open the corresponding `.jsonl` file. Each contains a header comment with example questions in the right shape, plus the count we need:

| File | Target | What we test |
|---|---|---|
| `propagation.jsonl` | 40 | Multi-upstream cascades, threshold edges, no-op invariance |
| `contradiction.jsonl` | 30 | Triples (3-way contradictions), latent vs. surfaced, type-mismatch |
| `lineage.jsonl` | 30 | 3+ hop chains, branch points, decisions with multiple supports |
| `cross_stream.jsonl` | 30 | Disagreement between streams, stale-stream detection |
| `historical.jsonl` | 30 | Date-range queries, "as of last week", calendar arithmetic |
| `provenance.jsonl` | 20 | Long evidence chains, missing-evidence flagging |
| `forgetfulness.jsonl` | 20 | Bitemporal expirations, partial deprecations |

## Validation

Once you've authored a category, validate by:

```bash
PYTHONPATH=. python -c "
from pathlib import Path
from benchmarks.business_mem_bench import load_questions
qs = list(load_questions(Path('benchmarks/business_mem_bench/gold_human')))
print(f'{len(qs)} questions loaded; categories:',
      {q.category.value for q in qs})
"
```

Then run Atlas against just the human subset:

```bash
PYTHONPATH=. python scripts/run_bmb.py --gold benchmarks/business_mem_bench/gold_human
```

## Authorship attribution

Add `_authored_by` to every question. It's stripped from the public release but preserved in git history so reviewers can see who wrote what.
