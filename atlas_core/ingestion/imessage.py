"""iMessage extractor — reads ~/Library/Messages/chat.db for messages
matching the per-thread opt-in policy.

Spec 07 § 2.6: iMessage is the most-sensitive stream. Atlas defaults to
metadata-only (sender, timestamp, thread_id) and never reads message
text unless the thread is on the explicit opt-in list. Even on opt-in
threads, the lane is `atlas_chat_history` and confidence_floor is low —
nothing escapes quarantine without manual review.

REQUIRES: macOS Full Disk Access for the Python interpreter running
Atlas. Grant via System Settings → Privacy & Security → Full Disk
Access → '+' → /opt/homebrew/.../python3.14 (or the venv's python).

Without FDA, sqlite3.connect raises 'unable to open database file' —
caught here as ImessageNotConfiguredError so the orchestrator marks the
stream errored without crashing the whole cycle.

Setup needed (Rich's hand):
  1. Grant Full Disk Access to the Python binary running Atlas.
  2. Add opted-in thread chat_identifier strings to ATLAS_IMESSAGE_OPT_IN
     env var (comma-separated). Example:
       export ATLAS_IMESSAGE_OPT_IN='+15555550100,+15555550101'
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_core.ingestion.base import (
    BaseExtractor,
    ExtractedClaim,
    IngestionCursor,
    StreamConfig,
    StreamType,
)
from atlas_core.ingestion.confidence import STREAM_CONFIDENCE_FLOORS


log = logging.getLogger(__name__)


DEFAULT_IMESSAGE_DB: Path = Path.home() / "Library" / "Messages" / "chat.db"
DEFAULT_BATCH_LIMIT: int = 200


class ImessageNotConfiguredError(RuntimeError):
    """Raised when chat.db is not readable (Full Disk Access not granted).

    Orchestrator catches and continues other streams.
    """


class ImessageExtractor(BaseExtractor):
    """Reads iMessage chat.db for opt-in threads only.

    Subject is the sender's chat_identifier (phone or email); object_value
    is the message text (or '<metadata-only>' for non-opt-in threads).
    """

    stream = StreamType.IMESSAGE

    def __init__(
        self,
        *,
        quarantine,
        db_path: Path | None = None,
        opt_in_env: str = "ATLAS_IMESSAGE_OPT_IN",
        batch_limit: int = DEFAULT_BATCH_LIMIT,
        config: StreamConfig | None = None,
    ):
        super().__init__(
            quarantine=quarantine,
            config=config or StreamConfig(
                confidence_floor=STREAM_CONFIDENCE_FLOORS[StreamType.IMESSAGE],
            ),
        )
        self.db_path = Path(db_path or DEFAULT_IMESSAGE_DB)
        self.opt_in_env = opt_in_env
        self.batch_limit = batch_limit

    # ── BaseExtractor contract ──────────────────────────────────────────────

    def _opt_in_set(self) -> set[str]:
        raw = os.environ.get(self.opt_in_env, "")
        return {s.strip() for s in raw.split(",") if s.strip()}

    def fetch_new_events(self, cursor: IngestionCursor) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            log.warning("iMessage chat.db missing at %s", self.db_path)
            return []

        try:
            uri = f"file:{self.db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.OperationalError as exc:
            raise ImessageNotConfiguredError(
                "Cannot open iMessage chat.db — Full Disk Access required. "
                "See atlas_core/ingestion/imessage.py docstring."
            ) from exc

        last_rowid = int(cursor.last_processed_id or "0")

        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT m.ROWID as rowid,
                       m.text as text,
                       m.date as date_apple_epoch,
                       m.is_from_me as is_from_me,
                       h.id as chat_identifier
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.ROWID > ?
                ORDER BY m.ROWID ASC
                LIMIT ?
                """,
                (last_rowid, self.batch_limit),
            ).fetchall()
        finally:
            conn.close()

        return [dict(r) for r in rows]

    def extract_claims_from_event(
        self, event: dict[str, Any],
    ) -> list[ExtractedClaim]:
        chat_identifier = event.get("chat_identifier") or "unknown"
        is_opted_in = chat_identifier in self._opt_in_set()
        text = event.get("text") or ""
        if not is_opted_in:
            text = "<metadata-only>"
        elif not text.strip():
            return []

        # Apple's `date` column is nanoseconds since 2001-01-01 UTC.
        ts = self._apple_epoch_to_iso(event.get("date_apple_epoch"))
        sender = "rich" if event.get("is_from_me") else chat_identifier
        rowid = event.get("rowid")

        return [
            ExtractedClaim(
                lane="atlas_chat_history",
                assertion_type="episode",
                subject_kref=(
                    f"kref://Atlas/People/{self._slugify(sender)}.person"
                ),
                predicate=("said" if is_opted_in else "messaged"),
                object_value=text[:2000],
                confidence=self.config.confidence_floor,
                evidence_source=f"imessage:{rowid}",
                evidence_source_family="imessage",
                evidence_kref=(
                    f"kref://Atlas/iMessage/thread/"
                    f"{self._slugify(chat_identifier)}.thread"
                ),
                evidence_timestamp=ts,
            )
        ]

    def cursor_for_event(self, event: dict[str, Any]) -> IngestionCursor:
        return IngestionCursor(
            stream=self.stream,
            last_processed_at=self._apple_epoch_to_iso(
                event.get("date_apple_epoch")
            ),
            last_processed_id=str(event.get("rowid", "0")),
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _apple_epoch_to_iso(apple_ns: Any) -> str:
        """Apple `date` columns store nanoseconds since 2001-01-01 UTC.

        Older messages used seconds. We detect by magnitude: > 1e15 → ns,
        else seconds.
        """
        if apple_ns is None:
            return datetime.now(timezone.utc).isoformat()
        try:
            v = int(apple_ns)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc).isoformat()
        seconds = v / 1_000_000_000 if v > 1_000_000_000_000_000 else v
        unix = seconds + 978_307_200  # 2001-01-01 UTC in unix seconds
        return datetime.fromtimestamp(unix, tz=timezone.utc).isoformat()

    @staticmethod
    def _slugify(value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in value).strip("_") or "unknown"
