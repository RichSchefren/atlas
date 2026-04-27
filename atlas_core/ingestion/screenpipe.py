"""Screenpipe extractor — reads ~/.screenpipe/db.sqlite for audio
transcriptions Atlas turns into ambient observational claims.

Spec 07 § 2.1: Screenpipe is the lowest-trust ambient stream — it captures
everything on screen + microphone, so the floor is `low` confidence and
everything lands in `atlas_observational`. Only after corroboration with
a higher-trust stream (Limitless transcript, vault note) does anything
escape the medium-risk REQUIRES_APPROVAL bucket.

Schema (verified against Rich's machine 2026-04-25):
  audio_transcriptions(id, audio_chunk_id, timestamp, transcription,
                       device, is_input_device, speaker_id, ...)

Phase 2 W7 ships: deterministic SQLite reader + per-speaker claim grouping.
LLM-driven claim extraction lands when the orchestrator gets a token budget.
"""

from __future__ import annotations

import logging
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


DEFAULT_SCREENPIPE_DB: Path = Path.home() / ".screenpipe" / "db.sqlite"

# Minimum transcription length we accept. Single words and "uh"-noise
# blow up the claim count without adding signal.
MIN_TRANSCRIPTION_CHARS: int = 40

# Per-run cap on rows pulled from the SQLite snapshot. Screenpipe writes
# millions of rows; we slice in cycles so a single run stays bounded.
DEFAULT_BATCH_LIMIT: int = 500


class ScreenpipeExtractor(BaseExtractor):
    """Pulls Screenpipe audio transcriptions newer than the cursor.

    Each transcription becomes a single ExtractedClaim with predicate
    `said` and the transcription text as the object value. The cursor
    tracks the last `id` (auto-increment), guaranteeing strict ordering
    even when timestamps collide.
    """

    stream = StreamType.SCREENPIPE

    def __init__(
        self,
        *,
        quarantine,
        db_path: Path | None = None,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
        config: StreamConfig | None = None,
    ):
        super().__init__(
            quarantine=quarantine,
            config=config or StreamConfig(
                confidence_floor=STREAM_CONFIDENCE_FLOORS[StreamType.SCREENPIPE],
            ),
        )
        self.db_path = Path(db_path or DEFAULT_SCREENPIPE_DB)
        self.batch_limit = batch_limit

    # ── BaseExtractor contract ──────────────────────────────────────────────

    def fetch_new_events(self, cursor: IngestionCursor) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            log.warning("Screenpipe DB missing at %s", self.db_path)
            return []

        # Cursor stores the last successfully processed row id.
        last_id = int(cursor.last_processed_id or "0")

        # Read-only connection — we never mutate Screenpipe's database.
        uri = f"file:{self.db_path}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, timestamp, transcription, device,
                       is_input_device, speaker_id
                FROM audio_transcriptions
                WHERE id > ?
                  AND length(transcription) >= ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (last_id, MIN_TRANSCRIPTION_CHARS, self.batch_limit),
            ).fetchall()

        return [dict(r) for r in rows]

    def extract_claims_from_event(
        self, event: dict[str, Any],
    ) -> list[ExtractedClaim]:
        """One transcription → one claim.

        Speaker resolution defers to W7+ (we have speaker_id but no
        speaker → kref dictionary yet). For now subject is the device.
        """
        transcription = (event.get("transcription") or "").strip()
        if not transcription:
            return []

        device = event.get("device") or "unknown_device"
        speaker_id = event.get("speaker_id")
        timestamp = self._normalize_timestamp(event.get("timestamp"))

        subject_kref = (
            f"kref://Atlas/Speakers/{speaker_id}.speaker"
            if speaker_id is not None
            else f"kref://Atlas/Devices/{self._slugify(device)}.device"
        )

        return [
            ExtractedClaim(
                lane="atlas_observational",
                assertion_type="episode",
                subject_kref=subject_kref,
                predicate="said",
                object_value=transcription[:2000],
                confidence=self.config.confidence_floor,
                evidence_source=f"screenpipe:audio_transcription/{event['id']}",
                evidence_source_family="screenpipe",
                evidence_kref=(
                    f"kref://Atlas/Screenpipe/audio.{event['id']}.transcript"
                ),
                evidence_timestamp=timestamp,
            )
        ]

    def cursor_for_event(self, event: dict[str, Any]) -> IngestionCursor:
        return IngestionCursor(
            stream=self.stream,
            last_processed_at=self._normalize_timestamp(event.get("timestamp")),
            last_processed_id=str(event["id"]),
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_timestamp(raw: Any) -> str:
        """Screenpipe stores timestamps as 'YYYY-MM-DD HH:MM:SS.sss';
        coerce to ISO-8601 UTC."""
        if raw is None:
            return datetime.now(timezone.utc).isoformat()
        s = str(raw).strip()
        # Accept already-ISO strings unchanged.
        try:
            dt = datetime.fromisoformat(s.replace(" ", "T"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _slugify(value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in value).strip("_") or "unknown"
