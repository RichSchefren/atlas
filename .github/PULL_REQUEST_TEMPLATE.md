# Pull Request

## What does this PR do?

<!-- One paragraph. What changed, why it matters, what spec section if any. -->

## Spec reference

<!-- e.g., notes/06 - Ripple Algorithm Spec § 4.2, or "n/a — bug fix only" -->

## Testing

- [ ] `pytest tests/ -v` all green
- [ ] `pytest tests/integration/test_agm_compliance.py` still 49/49 at 100%
- [ ] `python scripts/run_bmb.py` Atlas score ≥0.90
- [ ] New code has docstrings with spec references
- [ ] No magic numbers without named constants

## Type

- [ ] Bug fix
- [ ] New AGM compliance scenario
- [ ] Ripple algorithm change (requires spec update)
- [ ] Adapter (with real round-trip test)
- [ ] Documentation
- [ ] Other (explain)

## Notes for reviewer

<!-- Anything non-obvious, especially Cypher queries or AGM-adjacent changes. -->
