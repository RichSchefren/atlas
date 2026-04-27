"""Claude session log extractor — reads ~/.claude/projects/<slug>/*.jsonl
session transcripts and extracts user-authored prompts.

Spec 07 § 2.4: Claude session logs are highest-trust among ambient streams
because they're verbatim records of what Rich actually told Claude. Each
user prompt becomes a single ExtractedClaim:

  subject = kref://Atlas/Sessions/<sessionId>.session
  predicate = "user.prompt"
  object_value = the prompt text (truncated to 4000 chars)

Phase 2 W7 ships: deterministic JSONL streaming + cursor advancement by
file mtime + last-line offset. Phase 3 wires per-prompt LLM extraction
of decisions / commitments / preferences.

JSONL row shape (verified 2026-04-25):
  {type: "user", message: {role: "user", content: "..."},
   uuid, timestamp, sessionId, cwd, gitBranch, ...}

Skipped row types: file-history-snapshot, attachment, system, assistant,
last-prompt, plus user rows where message is missing/non-user-role.
"""

from __future__ import annotations

import json
import logging
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


DEFAULT_PROJECTS_ROOT: Path = (
    Path.home() / ".claude" / "projects" / "-Users-richardschefren"
)

# Skip noise content blocks Claude Code injects: local-command-caveat,
# command-name, system-reminder, etc. These aren't real user intent.
NOISE_PREFIXES: tuple[str, ...] = (
    "<local-command-",
    "<command-name>",
    "<system-reminder>",
    "<command-message>",
    "<bash-",
)

MIN_PROMPT_CHARS: int = 12
MAX_PROMPT_CHARS: int = 4000


class ClaudeSessionExtractor(BaseExtractor):
    """Walk the session JSONL files newer than the cursor mtime."""

    stream = StreamType.CLAUDE_SESSIONS

    def __init__(
        self,
        *,
        quarantine,
        projects_root: Path | None = None,
        config: StreamConfig | None = None,
    ):
        super().__init__(
            quarantine=quarantine,
            config=config or StreamConfig(
                confidence_floor=STREAM_CONFIDENCE_FLOORS[
                    StreamType.CLAUDE_SESSIONS
                ],
            ),
        )
        self.projects_root = Path(projects_root or DEFAULT_PROJECTS_ROOT)

    # ── BaseExtractor contract ──────────────────────────────────────────────

    def fetch_new_events(self, cursor: IngestionCursor) -> list[dict[str, Any]]:
        if not self.projects_root.exists():
            log.warning("Claude projects root missing: %s", self.projects_root)
            return []

        cursor_dt = self._parse_iso(cursor.last_processed_at)
        events: list[dict[str, Any]] = []

        # Iterate JSONL files in mtime order so cursor advances monotonically.
        files = sorted(
            self.projects_root.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
        )
        for path in files:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime <= cursor_dt:
                continue
            for row in self._iter_jsonl(path):
                ts_str = row.get("timestamp")
                if not ts_str:
                    continue
                row_dt = self._parse_iso(ts_str)
                if row_dt <= cursor_dt:
                    continue
                events.append(row)

        # Stable order — JSONL writes are append-only timestamped lines.
        events.sort(key=lambda r: r.get("timestamp", ""))
        return events

    def extract_claims_from_event(
        self, event: dict[str, Any],
    ) -> list[ExtractedClaim]:
        if event.get("type") != "user":
            return []

        msg = event.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "user":
            return []

        text = self._extract_text(msg.get("content"))
        if not text:
            return []
        if len(text) < MIN_PROMPT_CHARS:
            return []
        if any(text.startswith(p) for p in NOISE_PREFIXES):
            return []

        session_id = event.get("sessionId") or "unknown_session"
        timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
        cwd = event.get("cwd") or "unknown_cwd"
        uuid = event.get("uuid") or session_id

        return [
            ExtractedClaim(
                lane="atlas_chat_history",
                assertion_type="episode",
                subject_kref=f"kref://Atlas/Sessions/{session_id}.session",
                predicate="user.prompt",
                object_value=text[:MAX_PROMPT_CHARS],
                confidence=self.config.confidence_floor,
                evidence_source=f"claude_session:{session_id}",
                evidence_source_family="claude_session",
                evidence_kref=f"kref://Atlas/Sessions/{session_id}/{uuid}.message",
                evidence_timestamp=timestamp,
                scope=cwd,
            )
        ]

    def cursor_for_event(self, event: dict[str, Any]) -> IngestionCursor:
        return IngestionCursor(
            stream=self.stream,
            last_processed_at=event.get("timestamp")
                or datetime.now(timezone.utc).isoformat(),
            last_processed_id=event.get("uuid", ""),
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _iter_jsonl(self, path: Path):
        """Yield parsed rows; skip malformed lines without aborting the file."""
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        log.debug("malformed JSONL row in %s", path)
        except OSError as exc:
            log.warning("could not read %s: %s", path, exc)

    @staticmethod
    def _extract_text(content: Any) -> str:
        """Claude Code stores user content as either a str or a list of
        {type, text} blocks. Normalize to a single string."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(p for p in parts if p).strip()
        return ""

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, AttributeError):
            return datetime.fromtimestamp(0, tz=timezone.utc)
