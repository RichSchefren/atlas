# Contributing to Atlas

Thanks for considering a contribution. Atlas is intentionally a small, opinionated codebase — fewer than 6,000 lines of Python plus tests. The bar to add something is "would this be defensible in the paper?" If yes, ship it. If no, please file an issue first.

---

## Quick start (5 minutes)

```bash
git clone https://github.com/<placeholder>/atlas && cd atlas
docker compose up -d                         # Neo4j 5.26 with APOC
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
PYTHONPATH=. pytest tests/ -v                # 318 tests, ~8s
```

If the suite goes red on a clean checkout, that's a bug. Open an issue with the `pytest -v` output and your `python --version`.

---

## What we accept

| Category | Bar | Examples |
|---|---|---|
| **Bug fixes** | Reproducible failure on `master` | Cypher query rejected by Neo4j 5.26 |
| **AGM compliance** | New scenario in `benchmarks/agm_compliance/scenarios.py` covering an unrepresented edge | Concurrent revision race |
| **Ripple algorithm** | Spec update in `notes/06 - Ripple Algorithm Spec.md` first, then code | Confidence calibration on a new entity type |
| **Domain ontology** | Phase 1 locked at 8 entity types — additions need a vault whiteboard session, not a PR | New `Asset` subtype |
| **Adapters** | Real round-trip test against the target runtime | Hermes MemoryProvider |
| **Documentation** | Always welcome | Better docstring on `_temporal_decay_factor` |

## What we don't accept

- New top-level ontology entities without spec discussion (Phase 1 is locked at 8).
- Mocked Neo4j when a live container is available — the `docker compose up -d` is one line.
- Backward-compat shims for "what if the user already has X". Atlas is alpha; we change interfaces freely.
- Heuristic fallbacks for AGM operators. They're either correct or they're not.

---

## Pull request checklist

- [ ] `pytest tests/ -v` all green
- [ ] `pytest tests/integration/test_agm_compliance.py` still 49/49 at 100%
- [ ] `python scripts/run_bmb.py` still scores ≥0.90 on Atlas
- [ ] New code has a docstring with a spec reference
- [ ] Magic numbers are named constants
- [ ] Cypher queries are tested against live Neo4j (no fake drivers)
- [ ] If you changed AGM semantics, the compliance suite still passes AND the spec doc is updated

The CI workflow at `.github/workflows/test.yml` enforces the first three automatically. PRs that fail the BMB ≥0.90 gate cannot merge — Atlas's headline numbers are the product.

---

## Architecture you should read before changing things

- `notes/05 - Atlas Architecture & Schema.md` — the layered architecture
- `notes/06 - Ripple Algorithm Spec.md` — the propagation engine
- `notes/07 - Atlas Ingestion Pipeline.md` — the 6 streams
- `notes/08 - BusinessMemBench Design.md` — the benchmark
- `paper/atlas.md` — the paper draft

If you're touching any module under `atlas_core/revision/` or `atlas_core/ripple/`, read the spec for that module first. The AGM operators in particular satisfy seven postulates simultaneously; "obvious" simplifications usually break one of them.

---

## Communication

- **Bugs:** GitHub issues with the `bug` label
- **Feature ideas:** GitHub Discussions
- **Security:** Email rich@strategicprofits.com (see `SECURITY.md`)
- **Roadmap questions:** Discussions; the maintainer answers within a week

---

## Code style

- Python 3.10+ syntax (`list[X]`, `X | None`, `match`)
- Async-first; sync helpers only for cursor persistence
- 4-space indent, no tabs, trailing newline
- `from __future__ import annotations` on every module
- No emojis in code or comments
- Docstrings on every public function with a spec reference
- Comments explain *why*, not *what*

---

## License

By submitting a PR you agree your contribution is licensed under Apache 2.0 (the project license). Atlas does not require a CLA.
