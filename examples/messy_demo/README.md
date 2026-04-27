# Messy demo — real-shape inputs, real loop

`scripts/demo_messy.py` reads the files in this directory and runs them through
Atlas's full pipeline: deterministic extraction → quarantine →
cross-lane corroboration → ledger promotion → Ripple propagation →
contradiction detection → adjudication → SHA-256 chain verify.

The two input files are deliberately *shaped* like real captures, not like
synthetic test data:

- **`note_zenith_pricing.md`** — an Obsidian markdown note with YAML
  frontmatter and free-text body. It records that ZenithPro's price is
  `$2,995` and that the Origins margin claim depends on that price holding.
- **`transcript_pricing_meeting.md`** — a Limitless / Fireflies-style
  meeting transcript snippet where the team agrees to raise the price to
  `$3,495` starting next month.

The two claims are about the same `subject_kref` with the same `predicate`,
so:

1. The vault note lands first → quarantine candidate, lane = `vault_edit`.
2. The transcript lands second → identical fingerprint (subject, predicate,
   object differ — fingerprint is per claim shape), so it's a *new* claim
   contradicting the first. The cross-lane corroboration path *would* fire
   if both said the same thing. Here they disagree, which is the
   interesting case Ripple is designed for.
3. Both promote to ledger; the second supersedes the first via AGM revise.
4. Ripple walks the `DEPENDS_ON` edge and re-evaluates the margin belief
   downstream — its confidence drops because its supporting price changed.
5. The change shows up in the Obsidian adjudication queue (markdown).
6. The SHA-256 ledger chain stays intact across both writes.

No API keys required. The extractor is pure regex — no LLM calls. The point
of this demo is to show the loop running on input that *looks* like what
arrives from real capture, not extraction quality. Extraction quality is a
separate story documented in `atlas_core/ingestion/extractors/`.

Run it:

```bash
make demo-messy
# or
PYTHONPATH=. python scripts/demo_messy.py
```
