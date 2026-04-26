---
name: Tester report — loop demo (`scripts/demo_loop.py`)
about: The end-to-end loop demo crashed, hung, or printed wrong output
labels: tester-finding, loop-demo
---

## Tester

<!-- Your name + setup -->

## Which stage broke

The demo runs through 7 stages. Which one failed?

- [ ] 1. Plant the upstream belief
- [ ] 2. Plant the downstream belief
- [ ] 3. Fact change announcement
- [ ] 4. Ripple cascade (analyze_impact + reassess)
- [ ] 5. Adjudication queue (markdown write)
- [ ] 6. Resolve (AGM revise + ledger SUPERSEDE)
- [ ] 7. verify_chain (tamper detection)
- [ ] Other (between stages or at startup)

## What you saw vs what was expected

<!--
Expected at end: "✓ intact ✓  last_verified_sequence = 1" + "LOOP CLOSED" banner.
Paste the actual output and indicate where it diverged.
-->

## Output (full terminal capture)

```
Paste from the line ATLAS — open-source local-first cognitive memory
through the failure or end of output.
```

## Reproduction

```bash
PYTHONPATH=. python scripts/demo_loop.py
```

## Environment

- Atlas commit: `git rev-parse HEAD`
- Neo4j version: `docker exec atlas-neo4j-1 neo4j --version` (or your equivalent)
- `python --version`:
