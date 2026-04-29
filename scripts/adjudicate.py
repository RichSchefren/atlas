"""Adjudication CLI — promote, queue, or deny stuck candidates.

Atlas extracts claims into a quarantine pool tagged `requires_approval`.
Until they're moved out of quarantine — either promoted to the canonical
ledger or denied — Ripple has nothing to walk on and Atlas can't produce
contradictions, lineage, or any of its propagation-aware behavior.

This CLI is the human-in-the-loop unblocker. It does three things:

  • Auto-promote: candidates above the verification floor (0.80 by
    default) and on a trusted lane go straight into the ledger.
  • Queue: candidates below the floor are written as Markdown files to
    the adjudication queue (an Obsidian-readable folder) so the user can
    resolve them by editing `decision: accept|reject|adjust` in the
    frontmatter.
  • Auto-deny: candidates below a hard noise floor (0.50 by default) are
    marked terminal-denied with a logged reason.

Usage:
    python scripts/adjudicate.py --report                     # show buckets, no changes
    python scripts/adjudicate.py --auto-promote --dry-run     # preview ledger writes
    python scripts/adjudicate.py --auto-promote               # apply promotions
    python scripts/adjudicate.py --queue                      # write queue entries
    python scripts/adjudicate.py --auto-deny                  # deny noise candidates
    python scripts/adjudicate.py --all                        # promote + queue + deny

Defaults match the launch posture: auto-promote vault claims at >=0.80,
queue everything between 0.50 and 0.80, deny below 0.50.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure repo root is on sys.path when invoked as a script
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from atlas_core.trust.ledger import HashChainedLedger  # noqa: E402
from atlas_core.trust.promotion_policy import (  # noqa: E402
    VERIFICATION_FLOOR_CONFIDENCE,
    PromotionPolicy,
)
from atlas_core.trust.quarantine import QuarantineStore  # noqa: E402

log = logging.getLogger("adjudicate")


DEFAULT_DATA_DIR = Path(os.path.expanduser(os.environ.get("ATLAS_DATA_DIR", "~/.atlas")))
DEFAULT_QUEUE_DIR = Path(
    os.path.expanduser(
        os.environ.get(
            "ATLAS_QUEUE_DIR",
            "~/Obsidian/Active-Brain/00 Atlas/queue",
        )
    )
)
DEFAULT_NOISE_FLOOR = 0.50
DEFAULT_PROMOTE_LANES = ("atlas_vault", "atlas_meeting")


@dataclass
class Counts:
    promoted: int = 0
    promoted_failed: int = 0
    queued: int = 0
    denied: int = 0
    skipped: int = 0


def _safe_filename(text: str, max_len: int = 80) -> str:
    """Slugify a string for use as a filename component."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    return slug[:max_len] or "claim"


def _candidate_to_markdown(c: dict) -> str:
    """Render a candidate as a queue-ready Markdown file (frontmatter + body)."""
    evidence = json.loads(c.get("evidence_refs_json") or "[]")
    sources = sorted({e.get("source_family") or e.get("source") or "?" for e in evidence})
    n_sources = len(evidence)
    frontmatter = {
        "atlas_candidate_id": c["candidate_id"],
        "subject_kref": c["subject_kref"],
        "predicate": c["predicate"],
        "object_value": c["object_value"],
        "lane": c["lane"],
        "assertion_type": c["assertion_type"],
        "confidence": float(c["confidence"]),
        "trust_score": float(c["trust_score"]),
        "n_sources": n_sources,
        "source_families": sources,
        "decision": "pending",  # user edits to: accept | reject | adjust
        "decision_note": "",
    }
    fm_lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            fm_lines.append(f"{k}: {json.dumps(v)}")
        elif isinstance(v, str):
            fm_lines.append(f"{k}: {json.dumps(v)}")
        else:
            fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")

    body = [
        "",
        f"# {c['subject_kref']} — {c['predicate']}",
        "",
        f"**Atlas extracted this claim:** `{c['object_value']}`",
        "",
        f"From the **{c['lane']}** lane (confidence "
        f"{float(c['confidence']):.2f}, trust {float(c['trust_score']):.2f}).",
        "",
        f"## Evidence ({n_sources} source{'s' if n_sources != 1 else ''})",
        "",
    ]
    for e in evidence[:10]:
        ts = e.get("timestamp") or ""
        kref = e.get("kref") or ""
        body.append(f"- `{e.get('source_family', '?')}` @ `{ts}` — {kref}")
    if n_sources > 10:
        body.append(f"- … and {n_sources - 10} more")

    body.extend([
        "",
        "## Decision",
        "",
        "Edit the frontmatter above:",
        "- `decision: accept` — promote this claim into the ledger.",
        "- `decision: reject` — terminal-deny this claim.",
        "- `decision: adjust` — promote with `object_value` rewritten in `decision_note`.",
        "",
        "Atlas re-reads this file on the next adjudication pass and applies "
        "your decision.",
        "",
    ])
    return "\n".join(fm_lines + body)


def _bucket_report(quarantine: QuarantineStore) -> dict:
    """Count requires_approval candidates by lane × confidence bucket."""
    buckets: dict[str, dict[str, int]] = {}
    for c in quarantine.list_requires_approval():
        lane = c["lane"]
        conf = float(c["confidence"])
        if conf >= VERIFICATION_FLOOR_CONFIDENCE:
            bucket = ">=0.80"
        elif conf >= DEFAULT_NOISE_FLOOR:
            bucket = "0.50-0.79"
        else:
            bucket = "<0.50"
        buckets.setdefault(lane, {}).setdefault(bucket, 0)
        buckets[lane][bucket] += 1
    return buckets


def auto_promote(
    *,
    quarantine: QuarantineStore,
    policy: PromotionPolicy,
    lanes: tuple[str, ...],
    floor: float,
    dry_run: bool,
) -> Counts:
    counts = Counts()
    for c in quarantine.list_requires_approval():
        if c["lane"] not in lanes:
            continue
        if float(c["confidence"]) < floor:
            continue
        if dry_run:
            counts.promoted += 1
            log.info(
                "DRY-RUN promote: %s %s.%s = %r (conf=%.2f)",
                c["candidate_id"], c["subject_kref"], c["predicate"],
                c["object_value"], float(c["confidence"]),
            )
            continue
        result = policy.promote(c["candidate_id"], actor_id="adjudicate.auto_promote")
        if result.promoted:
            counts.promoted += 1
        else:
            counts.promoted_failed += 1
            log.warning(
                "promote failed: %s — gate=%s reason=%s",
                c["candidate_id"], result.blocked_at_gate, result.blocked_reason,
            )
    return counts


def queue_for_review(
    *,
    quarantine: QuarantineStore,
    queue_dir: Path,
    floor: float,
    noise_floor: float,
    dry_run: bool,
) -> Counts:
    counts = Counts()
    queue_dir.mkdir(parents=True, exist_ok=True)
    for c in quarantine.list_requires_approval():
        conf = float(c["confidence"])
        if conf >= floor or conf < noise_floor:
            continue
        lane_dir = queue_dir / c["lane"]
        lane_dir.mkdir(parents=True, exist_ok=True)
        fname = (
            _safe_filename(c["subject_kref"])
            + "__"
            + _safe_filename(c["predicate"])
            + "__"
            + c["candidate_id"][-8:]
            + ".md"
        )
        path = lane_dir / fname
        if dry_run:
            counts.queued += 1
            log.info("DRY-RUN queue: %s", path)
            continue
        if path.exists():
            counts.skipped += 1
            continue
        path.write_text(_candidate_to_markdown(c), encoding="utf-8")
        counts.queued += 1
    return counts


def auto_deny(
    *,
    quarantine: QuarantineStore,
    noise_floor: float,
    dry_run: bool,
) -> Counts:
    counts = Counts()
    for c in quarantine.list_requires_approval():
        if float(c["confidence"]) >= noise_floor:
            continue
        if dry_run:
            counts.denied += 1
            log.info(
                "DRY-RUN deny: %s (conf=%.2f)",
                c["candidate_id"], float(c["confidence"]),
            )
            continue
        quarantine.deny_candidate(
            c["candidate_id"],
            reason=f"below adjudication noise floor ({noise_floor:.2f})",
            decision_id="adjudicate.auto_deny",
        )
        counts.denied += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--data-dir", type=Path, default=DEFAULT_DATA_DIR,
        help="Atlas data dir (candidates.db + ledger.db live here)",
    )
    parser.add_argument(
        "--queue-dir", type=Path, default=DEFAULT_QUEUE_DIR,
        help="Where queue Markdown files are written",
    )
    parser.add_argument(
        "--floor", type=float, default=VERIFICATION_FLOOR_CONFIDENCE,
        help=f"Promote-eligible confidence floor (default {VERIFICATION_FLOOR_CONFIDENCE})",
    )
    parser.add_argument(
        "--noise-floor", type=float, default=DEFAULT_NOISE_FLOOR,
        help=f"Below this confidence, candidates are denied (default {DEFAULT_NOISE_FLOOR})",
    )
    parser.add_argument(
        "--lanes", nargs="+", default=list(DEFAULT_PROMOTE_LANES),
        help=f"Lanes eligible for auto-promote (default {DEFAULT_PROMOTE_LANES})",
    )
    parser.add_argument("--report", action="store_true", help="Show counts only")
    parser.add_argument("--auto-promote", action="store_true")
    parser.add_argument("--queue", action="store_true")
    parser.add_argument("--auto-deny", action="store_true")
    parser.add_argument("--all", action="store_true",
                        help="Equivalent to --auto-promote --queue --auto-deny")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without mutating any state")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    candidates_db = args.data_dir / "candidates.db"
    ledger_db = args.data_dir / "ledger.db"
    if not candidates_db.exists():
        print(f"error: {candidates_db} does not exist. Run ingestion first.", file=sys.stderr)
        return 2

    quarantine = QuarantineStore(db_path=candidates_db)
    ledger = HashChainedLedger(db_path=ledger_db)
    policy = PromotionPolicy(quarantine=quarantine, ledger=ledger)

    # Default action when no flags: report
    if not any([args.report, args.auto_promote, args.queue, args.auto_deny, args.all]):
        args.report = True

    if args.report:
        buckets = _bucket_report(quarantine)
        if not buckets:
            print("No candidates in requires_approval state.")
            return 0
        print("\nrequires_approval candidates by lane × confidence:\n")
        print(f"  {'lane':<25} {'>=0.80':>8} {'0.50-0.79':>10} {'<0.50':>7}")
        print(f"  {'-'*25} {'-'*8} {'-'*10} {'-'*7}")
        totals = {">=0.80": 0, "0.50-0.79": 0, "<0.50": 0}
        for lane in sorted(buckets):
            row = buckets[lane]
            for k in totals:
                totals[k] += row.get(k, 0)
            print(f"  {lane:<25} {row.get('>=0.80',0):>8} "
                  f"{row.get('0.50-0.79',0):>10} {row.get('<0.50',0):>7}")
        print(f"  {'-'*25} {'-'*8} {'-'*10} {'-'*7}")
        print(f"  {'total':<25} {totals['>=0.80']:>8} "
              f"{totals['0.50-0.79']:>10} {totals['<0.50']:>7}")
        print()
        return 0

    do_promote = args.auto_promote or args.all
    do_queue = args.queue or args.all
    do_deny = args.auto_deny or args.all

    grand = Counts()
    if do_promote:
        c = auto_promote(
            quarantine=quarantine, policy=policy,
            lanes=tuple(args.lanes), floor=args.floor, dry_run=args.dry_run,
        )
        grand.promoted += c.promoted
        grand.promoted_failed += c.promoted_failed
    if do_queue:
        c = queue_for_review(
            quarantine=quarantine, queue_dir=args.queue_dir,
            floor=args.floor, noise_floor=args.noise_floor, dry_run=args.dry_run,
        )
        grand.queued += c.queued
        grand.skipped += c.skipped
    if do_deny:
        c = auto_deny(
            quarantine=quarantine, noise_floor=args.noise_floor, dry_run=args.dry_run,
        )
        grand.denied += c.denied

    prefix = "DRY-RUN " if args.dry_run else ""
    print(
        f"\n{prefix}adjudication summary: "
        f"promoted={grand.promoted} (failed={grand.promoted_failed}) "
        f"queued={grand.queued} (skipped={grand.skipped}) "
        f"denied={grand.denied}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
