"""Base abstractions for Atlas ingestion pipeline.

Spec: 07 - Atlas Ingestion Pipeline § 1, 2, 6
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas_core.trust import QuarantineStore


log = logging.getLogger(__name__)


class StreamType(str, Enum):
    """The 6 ingestion streams Atlas supports."""

    SCREENPIPE = "screenpipe"
    LIMITLESS = "limitless"
    FIREFLIES = "fireflies"
    CLAUDE_SESSIONS = "claude_sessions"
    VAULT = "vault"
    IMESSAGE = "imessage"


@dataclass
class IngestionCursor:
    """Per-stream cursor — last successfully processed timestamp/file/event id.

    Cursors persist to disk so ingestion is idempotent across daemon restarts.
    Spec 07 § 6.
    """

    stream: StreamType
    last_processed_at: str  # ISO 8601 UTC
    last_processed_id: str = ""  # event id or file path or row id

    def to_dict(self) -> dict[str, str]:
        return {
            "stream": self.stream.value,
            "last_processed_at": self.last_processed_at,
            "last_processed_id": self.last_processed_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> IngestionCursor:
        return cls(
            stream=StreamType(data["stream"]),
            last_processed_at=data["last_processed_at"],
            last_processed_id=data.get("last_processed_id", ""),
        )

    @classmethod
    def fresh(cls, stream: StreamType) -> IngestionCursor:
        """A new cursor at epoch (process everything from the start)."""
        return cls(
            stream=stream,
            last_processed_at="1970-01-01T00:00:00+00:00",
            last_processed_id="",
        )


@dataclass
class ExtractedClaim:
    """A single claim emerging from an extractor — pre-quarantine.

    The orchestrator calls quarantine.upsert_candidate(...) for each.
    """

    lane: str
    assertion_type: str  # decision | preference | factual_assertion | episode | procedure
    subject_kref: str
    predicate: str
    object_value: str
    confidence: float
    evidence_source: str
    evidence_source_family: str
    evidence_kref: str
    evidence_timestamp: str
    scope: str = "global"


@dataclass
class IngestionResult:
    """What an extractor returns to the orchestrator after a single run."""

    stream: StreamType
    events_processed: int = 0
    claims_extracted: int = 0
    new_quarantine_entries: int = 0
    corroborated: int = 0
    auto_promoted: int = 0
    cursor_advanced_to: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return len(self.errors) == 0


@dataclass
class StreamConfig:
    """Per-stream tunable configuration — passed to BaseExtractor on init."""

    cadence_seconds: int = 1800  # default 30 min
    max_events_per_run: int = 5000
    confidence_floor: float = 0.4
    cursor_dir: Path = Path.home() / ".atlas" / "state"
    daily_token_budget_usd: float = 5.0


class BaseExtractor(ABC):
    """Common machinery for Atlas's stream extractors.

    Subclasses implement `fetch_new_events` and `extract_claims_from_event`.
    The base class handles cursor persistence, error containment, and the
    quarantine upsert path.
    """

    stream: StreamType  # subclasses set this

    def __init__(
        self,
        *,
        quarantine: QuarantineStore,
        config: StreamConfig | None = None,
    ):
        self.quarantine = quarantine
        self.config = config or StreamConfig()
        self.cursor_path = self.config.cursor_dir / f"{self.stream.value}.cursor.json"

    # ── Cursor persistence ──────────────────────────────────────────────────

    def load_cursor(self) -> IngestionCursor:
        """Load cursor from disk, or return fresh cursor if absent."""
        if not self.cursor_path.exists():
            return IngestionCursor.fresh(self.stream)
        data = json.loads(self.cursor_path.read_text(encoding="utf-8"))
        return IngestionCursor.from_dict(data)

    def save_cursor(self, cursor: IngestionCursor) -> None:
        """Persist cursor atomically via temp + rename."""
        self.cursor_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cursor_path.with_suffix(self.cursor_path.suffix + ".tmp")
        tmp.write_text(json.dumps(cursor.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(self.cursor_path)

    # ── Subclass contract ───────────────────────────────────────────────────

    @abstractmethod
    def fetch_new_events(self, cursor: IngestionCursor) -> list[dict[str, Any]]:
        """Pull events newer than the cursor. Returns ordered list."""

    @abstractmethod
    def extract_claims_from_event(
        self,
        event: dict[str, Any],
    ) -> list[ExtractedClaim]:
        """Convert one raw event into 0+ ExtractedClaim instances.

        Phase 2 W5: deterministic extractors (no LLM). Phase 2 W6 wires
        Claude-backed extraction prompts; this method becomes async there.
        """

    @abstractmethod
    def cursor_for_event(self, event: dict[str, Any]) -> IngestionCursor:
        """Build the cursor that, if saved, marks `event` as processed."""

    # ── Top-level run ───────────────────────────────────────────────────────

    def run_once(self) -> IngestionResult:
        """Execute one full ingestion cycle for this stream.

        Idempotent: if cursor is already at the latest event, no-op.
        Atomic per event: a single failure doesn't roll back prior events.
        Cursor advances only on successful claim insertion.
        """
        from atlas_core.trust import CandidateClaim, EvidenceRef

        result = IngestionResult(stream=self.stream)
        cursor = self.load_cursor()

        try:
            events = self.fetch_new_events(cursor)
        except Exception as exc:
            result.errors.append(f"fetch_new_events failed: {exc}")
            log.exception("Extractor %s fetch failed", self.stream.value)
            return result

        if not events:
            return result

        if len(events) > self.config.max_events_per_run:
            events = events[: self.config.max_events_per_run]

        for event in events:
            try:
                raw_claims = self.extract_claims_from_event(event)
            except Exception as exc:
                result.errors.append(f"extract failed at {event}: {exc}")
                continue

            for claim in raw_claims:
                # Apply per-stream confidence floor
                if claim.confidence < self.config.confidence_floor:
                    continue

                upsert = self.quarantine.upsert_candidate(
                    CandidateClaim(
                        lane=claim.lane,
                        assertion_type=claim.assertion_type,
                        subject_kref=claim.subject_kref,
                        predicate=claim.predicate,
                        object_value=claim.object_value,
                        confidence=claim.confidence,
                        evidence_ref=EvidenceRef(
                            source=claim.evidence_source,
                            source_family=claim.evidence_source_family,
                            kref=claim.evidence_kref,
                            timestamp=claim.evidence_timestamp,
                        ),
                        scope=claim.scope,
                    )
                )
                result.claims_extracted += 1
                if upsert.is_new:
                    result.new_quarantine_entries += 1
                if upsert.is_corroborated:
                    result.corroborated += 1
                if upsert.is_auto_promoted:
                    result.auto_promoted += 1

            # Advance cursor on success
            cursor = self.cursor_for_event(event)
            result.events_processed += 1

        # Persist final cursor
        if result.events_processed > 0:
            self.save_cursor(cursor)
            result.cursor_advanced_to = cursor.last_processed_at

        log.info(
            "Stream %s: %d events, %d claims, %d new, %d corroborated, %d auto-promoted",
            self.stream.value,
            result.events_processed,
            result.claims_extracted,
            result.new_quarantine_entries,
            result.corroborated,
            result.auto_promoted,
        )
        return result
