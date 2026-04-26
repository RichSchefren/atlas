---
name: Tester report — smoke test (`pytest tests/`)
about: The 318-test suite went red on a clean checkout
labels: tester-finding, smoke-test
---

## Tester

<!-- Your name + how you're running Atlas (Mac/Linux, Python version, Neo4j source) -->

## What broke

<!-- Which test(s)? Paste the failing pytest -v line -->

## Expected vs actual

- Expected: 318 passed
- Actual: <N> passed, <M> failed

## Reproduction (exactly the commands you ran)

```bash
git clone https://github.com/RichSchefren/atlas && cd atlas
docker compose up -d
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
PYTHONPATH=. pytest tests/ -v
```

## Failure output

```
Paste the full traceback for at least one failing test here.
```

## Environment

- Atlas commit: `git rev-parse HEAD`
- `python --version`:
- `docker compose version`:
- OS / arch:

## What I tried before filing

<!-- E.g., "ran `docker compose down -v && docker compose up -d` and it still failed", or "happens on first checkout, no prior state" -->
