# AGM Compliance Suite — Reproducibility Artifact

This is the checked-in result of running Atlas's 49-scenario AGM compliance suite, the same shape as Kumiho Table 18 (5 categories × all-applicable postulates). Atlas's headline correctness claim is 100% pass rate across all 49 scenarios. This file is the auditable artifact behind that claim.

## How this file was generated

```bash
docker compose up -d neo4j
PYTHONPATH=. python scripts/run_agm_compliance.py
```

Run timestamp (UTC): `2026-04-27T19:28:08.917828+00:00` → `2026-04-27T19:28:09.624573+00:00`
Neo4j endpoint: `bolt://localhost:7687`

## Headline result

**49 / 49 scenarios passed (100.0%).**

All seven AGM postulates are upheld across all five operational categories. This matches Kumiho's Table 18 result and is the formal correctness baseline Atlas's Ripple engine extends from.

## By category

| Category | Passed | Total |
|---|---|---|
| `adversarial` | 15 | 15 |
| `chain` | 8 | 8 |
| `multi_item` | 8 | 8 |
| `simple` | 10 | 10 |
| `temporal` | 8 | 8 |

## By postulate

| Postulate | Passed | Total |
|---|---|---|
| `Core-Retainment` | 9 | 9 |
| `K*2` | 12 | 12 |
| `K*3` | 8 | 8 |
| `K*4` | 1 | 1 |
| `K*5` | 9 | 9 |
| `K*6` | 3 | 3 |
| `Relevance` | 7 | 7 |

## Failures

_None._

## Machine-readable output

Per-scenario rows (including detail strings and error messages) are in `benchmarks/agm_compliance/runs/baseline.json`. Tools that want to diff runs across commits should read that file, not this one — Markdown is for humans, JSON is for machines.

## Why this matters

Kumiho's central contribution (arxiv 2603.17244) was proving AGM K*2–K*6 + Hansson Relevance/Core-Retainment can be discharged on a property graph. They reported 100% across 49 scenarios in their published table. Atlas re-implements those operators as open-source local-first infrastructure and runs the same shape suite, so a reader can verify Atlas hasn't quietly weakened the formal guarantees that make AGM compliance load-bearing for the rest of the system. Ripple's downstream re-evaluation (Atlas's headline extension) sits on top of these operators — if any postulate weakened, every Ripple-derived confidence would be unsound.
