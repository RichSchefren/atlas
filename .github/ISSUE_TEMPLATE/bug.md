---
name: Bug report
about: Reproducible failure on master
labels: bug
---

## What happened

<!-- One paragraph. What did you do, what did Atlas do, what did you expect? -->

## Reproduction

```bash
# Exact commands that trigger the failure on a clean checkout.
git clone https://github.com/<placeholder>/atlas && cd atlas
docker compose up -d
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
PYTHONPATH=. pytest tests/path/to/failing_test.py -v
```

## Output

```
Paste the failing pytest -v output here. Include the full traceback.
```

## Environment

- Atlas commit / version:
- Python version: `python --version`
- Neo4j version: `docker exec atlas-neo4j-1 neo4j --version` (or your equivalent)
- OS: macOS 14, Ubuntu 24.04, etc.

## Spec section (if relevant)

<!-- e.g., the failure suggests Ripple Spec § 4.1 is wrong, or "n/a" -->
