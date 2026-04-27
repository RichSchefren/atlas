"""One ingestion cycle — invoked every 30 minutes by launchd.

Wires every available extractor against the configured paths,
runs the orchestrator once, writes a health row, exits. launchd
re-fires per the StartCalendarInterval / StartInterval in the
plist.

Spec: PHASE-5-AND-BEYOND.md § 1.1
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from atlas_core.daemon.health import HealthLogger, HealthRow


log = logging.getLogger(__name__)


def run_ingestion_cycle() -> int:
    """Run one orchestration pass. Returns exit code (0 = ok, ≠0 = error)."""
    from atlas_core.ingestion import (
        ClaudeSessionExtractor,
        IngestionOrchestrator,
        LimitlessExtractor,
        ScreenpipeExtractor,
        VaultExtractor,
    )
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    health = HealthLogger("com.atlas.ingestion")
    started = time.time()
    started_iso = health.now_iso()

    try:
        data_dir = Path(os.environ.get(
            "ATLAS_DATA_DIR", str(Path.home() / ".atlas"),
        ))
        data_dir.mkdir(parents=True, exist_ok=True)

        quarantine = QuarantineStore(data_dir / "candidates.db")
        ledger = HashChainedLedger(data_dir / "ledger.db")  # noqa: F841

        orch = IngestionOrchestrator()

        # Vault
        vault_root = Path(os.environ.get(
            "ATLAS_VAULT_ROOT",
            str(Path.home() / ".atlas" / "watch" / "vault"),
        ))
        if vault_root.exists():
            orch.register(VaultExtractor(
                quarantine=quarantine,
                vault_roots=[vault_root],
            ))

        # Limitless
        limitless_root = Path(os.environ.get(
            "ATLAS_LIMITLESS_ROOT",
            str(Path.home() / ".atlas" / "watch" / "limitless"),
        ))
        if limitless_root.exists():
            orch.register(LimitlessExtractor(
                quarantine=quarantine,
                archive_root=limitless_root,
            ))

        # Screenpipe
        screenpipe_db = Path(os.environ.get(
            "ATLAS_SCREENPIPE_DB",
            str(Path.home() / ".screenpipe" / "db.sqlite"),
        ))
        if screenpipe_db.exists():
            orch.register(ScreenpipeExtractor(
                quarantine=quarantine,
                db_path=screenpipe_db,
                batch_limit=int(os.environ.get(
                    "ATLAS_SCREENPIPE_LIMIT", "300",
                )),
            ))

        # Claude sessions
        claude_root = Path(os.environ.get(
            "ATLAS_CLAUDE_PROJECTS",
            str(Path.home() / ".claude" / "projects" / "-Users-richardschefren"),
        ))
        if claude_root.exists():
            orch.register(ClaudeSessionExtractor(
                quarantine=quarantine,
                projects_root=claude_root,
            ))

        if not orch.registered_streams():
            health.append(HealthRow(
                daemon="com.atlas.ingestion",
                started_at=started_iso,
                finished_at=health.now_iso(),
                success=True,
                elapsed_sec=time.time() - started,
                summary={"reason": "no streams registered (paths missing)"},
            ))
            return 0

        report = orch.run_cycle()
        elapsed = time.time() - started

        health.append(HealthRow(
            daemon="com.atlas.ingestion",
            started_at=started_iso,
            finished_at=health.now_iso(),
            success=(report.total_errors == 0),
            elapsed_sec=elapsed,
            summary={
                "streams": [s.value for s in report.per_stream],
                "events": report.total_events,
                "claims": report.total_claims,
                "errors": report.total_errors,
            },
        ))
        return 0 if report.total_errors == 0 else 2

    except Exception as exc:
        log.exception("Ingestion cycle crashed")
        health.append(HealthRow(
            daemon="com.atlas.ingestion",
            started_at=started_iso,
            finished_at=health.now_iso(),
            success=False,
            elapsed_sec=time.time() - started,
            error=f"{type(exc).__name__}: {exc}",
        ))
        return 3


def main() -> int:
    """Module entry: `python -m atlas_core.daemon.cycle`."""
    return run_ingestion_cycle()


if __name__ == "__main__":
    sys.exit(main())
