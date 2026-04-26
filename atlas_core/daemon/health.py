"""Rolling health log for the Atlas daemons.

Each daemon invocation appends a JSONL row to
~/.atlas/health/<daemon_name>.jsonl with start/finish timestamps,
events processed, errors, elapsed wall time, and budget spend if
applicable. Rolls files at 10MB to keep history bounded.

Spec: PHASE-5-AND-BEYOND.md § 1.1
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


DEFAULT_HEALTH_DIR: Path = Path.home() / ".atlas" / "health"
ROLLOVER_BYTES: int = 10 * 1024 * 1024


@dataclass
class HealthRow:
    """One daemon-cycle health record."""

    daemon: str
    started_at: str
    finished_at: str = ""
    success: bool = False
    elapsed_sec: float = 0.0
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HealthLogger:
    """Append-only JSONL writer with size-based rollover."""

    def __init__(
        self,
        daemon_name: str,
        *,
        health_dir: Path | None = None,
    ):
        self.daemon = daemon_name
        self.dir = Path(health_dir or DEFAULT_HEALTH_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{daemon_name}.jsonl"

    def append(self, row: HealthRow) -> None:
        """Append one health row. Rolls the file to .1 if past the
        rollover threshold."""
        try:
            if self.path.exists() and self.path.stat().st_size > ROLLOVER_BYTES:
                rollover = self.dir / f"{self.daemon}.jsonl.1"
                if rollover.exists():
                    rollover.unlink()
                self.path.rename(rollover)
        except OSError as exc:
            log.warning("Health log rollover failed: %s", exc)

        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row.to_dict(), separators=(",", ":")))
                f.write("\n")
        except OSError as exc:
            log.warning("Health log append failed: %s", exc)

    def latest(self) -> HealthRow | None:
        """Read the most recent row from the current file. None if empty."""
        if not self.path.exists():
            return None
        try:
            with self.path.open("r", encoding="utf-8") as f:
                last_line = ""
                for line in f:
                    if line.strip():
                        last_line = line
            if not last_line:
                return None
            data = json.loads(last_line)
            return HealthRow(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
