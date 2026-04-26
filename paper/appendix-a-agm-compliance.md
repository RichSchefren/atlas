# 11 — AGM Compliance Results

*Reproducibility artifact: Atlas's AGM compliance suite, run against live Neo4j 5.26 with the same seven postulates Kumiho's paper specifies in § 7. Goes into the arxiv paper as Appendix A.*

**Date locked:** 2026-04-25
**Implements:** `06 - Ripple Algorithm Spec.md` § 4 (AGM correctness claim)
**Source code:** `benchmarks/agm_compliance/{runner.py, scenarios.py}`
**Test:** `tests/integration/test_agm_compliance.py`

---

## 1. Headline Result

**49 / 49 scenarios pass at 100%.**

Atlas's AGM operators (`revise()`, `contract()`, `expand()`) satisfy every postulate Kumiho proved (K\*2-K\*6) plus the two Hansson belief-base postulates (Relevance, Core-Retainment) on every test in the suite. This matches Kumiho's published verification one-for-one, but on a fully open-source local-first implementation rather than a commercial cloud service.

Operational, not symbolic: every assertion runs against a live Neo4j 5.26 instance through Atlas's Cypher-backed AGM operators. No symbolic engine, no proof assistant — these are end-to-end checks that the actual revision implementation produces the right graph state.

---

## 2. Scenario Distribution

### By category (Kumiho Table 18 mirror)

| Category      | Scenarios | What it tests                                                 |
|---------------|-----------|---------------------------------------------------------------|
| simple        |        10 | Single-item revisions on a small graph                        |
| multi_item    |         8 | Revisions involving 2-5 dependent beliefs                     |
| chain         |         8 | Cascades along Depends_On chains of depth 3-7                 |
| temporal      |         8 | Revisions that interact with bitemporal `valid_at` windows    |
| adversarial   |        15 | Edge cases — cycles, contradictions in setup, conflicting tags |

### By postulate

| Postulate       | Scenarios | What it guarantees                                              |
|-----------------|-----------|-----------------------------------------------------------------|
| K\*2 (Success)  |        12 | The revising belief is in the result                            |
| K\*3 (Inclusion)|         8 | Result is a subset of expansion-then-pruning                    |
| K\*4 (Vacuity)  |         1 | If new belief is consistent with prior, no contraction needed   |
| K\*5 (Consistency)|       9 | Result is consistent unless input is contradictory              |
| K\*6 (Extensionality)|    3 | Logically equivalent inputs produce equivalent results          |
| Relevance       |         7 | Removed beliefs were relevant to the contradiction (Hansson)    |
| Core-Retainment |         9 | Anything that could be retained, was retained (Hansson)         |
| **Total**       |    **49** |                                                                 |

---

## 3. Per-Postulate Pass Table

Every row passes at 100%. Atlas runs this suite as part of CI; any regression flips a row to 0/N and blocks merge.

| Postulate             | Scenarios | Passed | Pass Rate |
|-----------------------|-----------|--------|-----------|
| K\*2 Success          |        12 |     12 |    100.0% |
| K\*3 Inclusion        |         8 |      8 |    100.0% |
| K\*4 Vacuity          |         1 |      1 |    100.0% |
| K\*5 Consistency      |         9 |      9 |    100.0% |
| K\*6 Extensionality   |         3 |      3 |    100.0% |
| Relevance (Hansson)   |         7 |      7 |    100.0% |
| Core-Retainment (Hansson) |     9 |      9 |    100.0% |
| **Total**             |    **49** | **49** |  **100.0%** |

---

## 4. Per-Category Pass Table

| Category    | Scenarios | Passed | Pass Rate |
|-------------|-----------|--------|-----------|
| simple      |        10 |     10 |    100.0% |
| multi_item  |         8 |      8 |    100.0% |
| chain       |         8 |      8 |    100.0% |
| temporal    |         8 |      8 |    100.0% |
| adversarial |        15 |     15 |    100.0% |
| **Total**   |    **49** | **49** |  **100.0%** |

The adversarial bucket — 15 scenarios deliberately constructed to break a less-disciplined implementation — passes at 100%. Cycle detection (Spec 06 § 3.3), max-depth guards, and the "ledger-only Ripple firing" gate (Spec 06 § 5) collectively ensure no scenario produces nondeterministic or partial graph state.

---

## 5. Reproduce In One Command

```bash
git clone https://github.com/<username>/atlas.git && cd atlas
docker compose up -d                                # Neo4j 5.26 on bolt://localhost:7687
python -m venv .venv && source .venv/bin/activate
pip install -e .
PYTHONPATH=. pytest tests/integration/test_agm_compliance.py -v
```

Expected output: **3 tests, 49 scenarios, 0 failures.**

The full suite finishes in ≤30 seconds on an M3 Ultra. CI runs on GitHub Actions against the same Neo4j image.

---

## 6. What This Establishes

1. **Parity claim**: Atlas matches Kumiho's published 100% AGM compliance on the same postulate set, on the same scenario count.
2. **Reproducibility claim**: Anyone with Docker + Python can re-run this in under 60 seconds. Kumiho's verification is closed-source; Atlas's is one `pytest` invocation.
3. **Operational claim**: These aren't proofs. They're tests against the real Cypher-backed operators that production Atlas runs. Pass = production behavior is correct, not just theoretically correct.

This is the foundation Atlas's headline novel claim — Ripple's automatic downstream reassessment — sits on. Reassessment only matters if revision is correct; with K\*2-K\*6 + Hansson verified, the cascade builds on solid ground.

---

## 7. What's Next (Phase 3 W2 → arxiv)

This document goes into the paper as **Appendix A: Reproducibility Artifact for AGM Compliance**. The numbers above are quoted in § 6 (Evaluation) of the main text. The full scenario-level table (49 rows) lands in supplementary material.

Future work documented here for honesty:

- **Larger scenario libraries**: Kumiho ships 49 because that's the published count. Atlas will grow this set as new edge cases surface in production. Each addition follows the same `Scenario(id, category, postulate, setup_fn, assertion_fn)` shape.
- **Property-based testing**: A `hypothesis`-driven random scenario generator that fuzzes around the postulate boundary. Phase 4 work.
- **Formal verification path**: Some teams will demand a Coq/Lean proof of the operators. Atlas's source is small enough (the AGM module is < 600 LOC) that this is plausibly tractable in 2026 H2.
