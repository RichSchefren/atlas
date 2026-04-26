---
name: Tester report — BusinessMemBench (`scripts/run_bmb.py`)
about: The benchmark didn't print the expected scores or a system errored mid-run
labels: tester-finding, bench
---

## Tester

<!-- Your name + setup -->

## Which system misbehaved

- [ ] Atlas (expected 1.000 on 149 questions)
- [ ] Graphiti (expected 0.711)
- [ ] Vanilla (expected 0.000 — if non-zero, your harness is broken)
- [ ] Mem0 (skip without OPENAI_API_KEY; otherwise expected ≥0.10)
- [ ] Letta (skip without OPENAI_API_KEY)
- [ ] Memori (skip without MEMORI_API_KEY)
- [ ] Other / harness itself crashed

## Score gap

- Expected:
- Got:
- Per-category breakdown (paste the matrix output here):

```
Paste the `━━ <system> ━━` block(s) from your run.
```

## Reproduction

```bash
PYTHONPATH=. python scripts/run_bmb.py [--seed 42]
```

If using keys, list which ones were set:

- [ ] OPENAI_API_KEY
- [ ] MEMORI_API_KEY

## Environment

- Atlas commit: `git rev-parse HEAD`
- Neo4j version:
- Are there leftover nodes from a prior run? `MATCH (n) WHERE n.kref STARTS WITH 'kref://AtlasCoffee/' RETURN count(n)` should be 0 before run, ~150 during, 0 after `reset()`.
