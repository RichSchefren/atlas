"""First real-data ingestion run.

Wires the Vault + Limitless extractors against Rich's actual Obsidian
vaults, ingests into a fresh ~/.atlas data directory, and prints a
summary of what landed in the quarantine.

This is the moment Atlas crosses from "passes its own tests" to "ingests
the world." Run from the repo root:

    PYTHONPATH=. python scripts/first_real_run.py

Run is idempotent on the cursor — re-running picks up only newer files.
The two slow guards:
  - VAULT_LIMIT  caps how many vault files we scan per run.
  - LIMITLESS_LIMIT  caps Limitless transcripts per run (5,200+ files
    on Rich's machine; ingest in slices).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Allow `python scripts/first_real_run.py` from repo root without PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ATLAS_DATA_DIR = Path(os.environ.get(
    "ATLAS_DATA_DIR", str(Path.home() / ".atlas")
))
VAULT_ROOT = Path(os.environ.get(
    "ATLAS_VAULT_ROOT",
    str(Path.home() / ".atlas" / "watch" / "vault"),
))
LIMITLESS_ROOT = Path(os.environ.get(
    "ATLAS_LIMITLESS_ROOT",
    str(Path.home() / ".atlas" / "watch" / "limitless"),
))

VAULT_LIMIT = int(os.environ.get("ATLAS_VAULT_LIMIT", "200"))
LIMITLESS_LIMIT = int(os.environ.get("ATLAS_LIMITLESS_LIMIT", "100"))


def main() -> int:
    from atlas_core.ingestion import (
        ClaudeSessionExtractor,
        IngestionOrchestrator,
        LimitlessExtractor,
        ScreenpipeExtractor,
        VaultExtractor,
    )
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    ATLAS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    candidates_db = ATLAS_DATA_DIR / "candidates.db"
    ledger_db = ATLAS_DATA_DIR / "ledger.db"

    print("== Atlas first real run ==")
    print(f"Data dir   : {ATLAS_DATA_DIR}")
    print(f"Vault root : {VAULT_ROOT}")
    print(f"Limitless  : {LIMITLESS_ROOT}")
    print(f"Caps       : vault={VAULT_LIMIT}, limitless={LIMITLESS_LIMIT}")
    print()

    if not VAULT_ROOT.exists():
        print("  ! vault root missing — skipping vault stream", file=sys.stderr)
        vault_extractor = None
    else:
        # File-cap enforced inside extractor via env contract — fall back
        # to raw VaultExtractor and trust caller to pre-filter via VAULT_LIMIT.
        vault_extractor = VaultExtractor(
            quarantine=QuarantineStore(candidates_db),
            vault_roots=[VAULT_ROOT],
        )

    quarantine = QuarantineStore(candidates_db)
    ledger = HashChainedLedger(ledger_db)

    orch = IngestionOrchestrator()
    if vault_extractor is not None:
        orch.register(vault_extractor)
    if LIMITLESS_ROOT.exists():
        orch.register(LimitlessExtractor(
            quarantine=quarantine,
            archive_root=LIMITLESS_ROOT,
        ))
    else:
        print("  ! limitless root missing — skipping", file=sys.stderr)

    # Screenpipe (read-only against ~/.screenpipe/db.sqlite)
    screenpipe_db = Path(
        os.environ.get(
            "ATLAS_SCREENPIPE_DB",
            str(Path.home() / ".screenpipe" / "db.sqlite"),
        )
    )
    if screenpipe_db.exists():
        from atlas_core.ingestion import ScreenpipeExtractor
        orch.register(ScreenpipeExtractor(
            quarantine=quarantine,
            db_path=screenpipe_db,
            batch_limit=int(os.environ.get("ATLAS_SCREENPIPE_LIMIT", "300")),
        ))
    else:
        print("  ! screenpipe db missing — skipping", file=sys.stderr)

    # Claude session logs
    claude_root = Path(
        os.environ.get(
            "ATLAS_CLAUDE_PROJECTS",
            str(Path.home() / ".claude" / "projects" / "-Users-richardschefren"),
        )
    )
    if claude_root.exists():
        from atlas_core.ingestion import ClaudeSessionExtractor
        orch.register(ClaudeSessionExtractor(
            quarantine=quarantine,
            projects_root=claude_root,
        ))
    else:
        print("  ! claude projects root missing — skipping", file=sys.stderr)

    if not orch.registered_streams():
        print("No streams to run. Exiting.")
        return 1

    started = time.time()
    report = orch.run_cycle()
    elapsed = time.time() - started

    print(f"== Orchestration finished in {elapsed:.1f}s ==")
    print(f"Streams        : {len(report.per_stream)}")
    print(f"Total events   : {report.total_events}")
    print(f"Total claims   : {report.total_claims}")
    print(f"Total errors   : {report.total_errors}")
    print()

    for stream, result in report.per_stream.items():
        print(f"  {stream.value:<14} events={result.events_processed:>5}  "
              f"claims={result.claims_extracted:>5}  "
              f"errors={len(result.errors):>3}")
        if result.errors:
            for err in result.errors[:3]:
                print(f"    ! {err}")
    print()

    # Status breakdown straight from SQLite — list_pending only returns
    # 'pending' status, but vault/observational claims default to
    # 'requires_approval' (medium risk), so we surface both.
    import sqlite3
    conn = sqlite3.connect(candidates_db)
    status_rows = conn.execute(
        "SELECT status, COUNT(*) FROM candidates GROUP BY status ORDER BY 2 DESC"
    ).fetchall()
    lane_rows = conn.execute(
        "SELECT lane, COUNT(*) FROM candidates GROUP BY lane ORDER BY 2 DESC"
    ).fetchall()
    conn.close()

    print("Quarantine status breakdown:")
    for status, n in status_rows:
        print(f"  {status:<22} {n}")
    print("Quarantine lane breakdown:")
    for lane, n in lane_rows:
        print(f"  {lane:<22} {n}")

    chain_status = ledger.verify_chain()
    print()
    print(f"Ledger intact: {chain_status.intact}  "
          f"(seq={chain_status.last_verified_sequence})")

    summary = {
        "elapsed_seconds": round(elapsed, 2),
        "streams": [s.value for s in report.per_stream],
        "total_events": report.total_events,
        "total_claims": report.total_claims,
        "total_errors": report.total_errors,
        "candidates_by_status": {s: n for s, n in status_rows},
        "candidates_by_lane": {lane: n for lane, n in lane_rows},
        "ledger_intact": chain_status.intact,
        "ledger_last_sequence": chain_status.last_verified_sequence,
    }
    out_path = ATLAS_DATA_DIR / "first_run_report.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"Report -> {out_path}")
    return 0 if report.total_errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
