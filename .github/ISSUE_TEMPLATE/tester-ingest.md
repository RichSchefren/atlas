---
name: Tester report — live ingest (`scripts/first_real_run.py`)
about: Pointed Atlas at a real Obsidian vault / Limitless / Screenpipe / Claude logs and something went wrong
labels: tester-finding, ingest
---

## Tester

<!-- Your name + which streams you pointed Atlas at -->

## Which stream(s) misbehaved

- [ ] Vault (Obsidian markdown)
- [ ] Limitless (pendant transcripts)
- [ ] Screenpipe (~/.screenpipe/db.sqlite)
- [ ] Claude Code session logs (~/.claude/projects/<slug>/*.jsonl)
- [ ] Fireflies (needs FIREFLIES_API_KEY)
- [ ] iMessage (needs Full Disk Access)

## Failure shape

- [ ] Crashed with traceback (paste below)
- [ ] Ran clean but produced 0 candidates
- [ ] Produced wrong-shaped krefs (paste an example)
- [ ] Landed in wrong lane (e.g., vault content showing up in atlas_observational)
- [ ] Cursor didn't advance (re-run reprocessed everything)
- [ ] Ledger reported `intact: false`

## Numbers

- Files in source dir: <N>
- Events ingested: <N>
- Claims extracted: <N>
- Candidates that landed: <N>
- Errors reported in the run: <N>
- Wall time: <Ns>

## Sample output

```
Paste the ‘== Atlas first real run ==’ output block.
```

## Spot-checked candidates

```sql
sqlite3 ~/.atlas/candidates.db "
  SELECT lane, status, COUNT(*) FROM candidates GROUP BY lane, status
"
```

```
Paste output.
```

## Environment

- Atlas commit: `git rev-parse HEAD`
- Source-of-truth size (vault file count, screenpipe DB MB, etc.):
