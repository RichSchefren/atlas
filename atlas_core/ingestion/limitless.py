"""Limitless extractor — pendant transcripts with YAML frontmatter.

Spec 07 § 2.2: Limitless files are pre-processed to YAML with action_items,
decisions, friction_points, projects, and people fields. Atlas reads YAML
first (deterministic) and only falls back to transcript parsing for
ambiguity (Phase 2 W6, LLM-driven).

Phase 2 W5 ships: YAML-only deterministic extractor.
"""

from __future__ import annotations

import logging
import re
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


_FRONTMATTER = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)


class LimitlessExtractor(BaseExtractor):
    """Reads pre-processed Limitless markdown files from a directory tree.

    Each file has YAML frontmatter with structured fields. Atlas extracts
    claims deterministically from those fields:
      - participants → Person mentions (closeness signals)
      - action_items → Commitment claims
      - decisions    → Decision claims
      - projects     → Project mention claims
    """

    stream = StreamType.LIMITLESS

    def __init__(
        self,
        *,
        quarantine,
        archive_root: Path,
        config: StreamConfig | None = None,
    ):
        super().__init__(
            quarantine=quarantine,
            config=config or StreamConfig(
                confidence_floor=STREAM_CONFIDENCE_FLOORS[StreamType.LIMITLESS],
            ),
        )
        self.archive_root = Path(archive_root)

    # ── BaseExtractor contract ──────────────────────────────────────────────

    def fetch_new_events(self, cursor: IngestionCursor) -> list[dict[str, Any]]:
        cursor_dt = datetime.fromisoformat(cursor.last_processed_at)
        events: list[dict[str, Any]] = []
        if not self.archive_root.exists():
            return events

        for path in self.archive_root.rglob("*.md"):
            mtime_dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime_dt <= cursor_dt:
                continue
            events.append({
                "path": str(path),
                "filename": path.name,
                "mtime": mtime_dt.isoformat(),
            })

        events.sort(key=lambda e: e["mtime"])
        return events

    def extract_claims_from_event(
        self,
        event: dict[str, Any],
    ) -> list[ExtractedClaim]:
        path = Path(event["path"])
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("Limitless: cannot read %s: %s", path, exc)
            return []

        frontmatter = self._parse_frontmatter(content)
        if not frontmatter:
            return []

        evidence_kref = f"kref://Atlas/Limitless/{path.stem}.episode"
        evidence_ts = event["mtime"]
        claims: list[ExtractedClaim] = []

        # Participants → Person mentions for closeness scoring
        for participant in self._as_list(frontmatter.get("participants", [])):
            if participant.lower() == "rich":
                continue  # Rich is the sovereign node, not a Person
            claims.append(ExtractedClaim(
                lane="atlas_observational",
                assertion_type="factual_assertion",
                subject_kref=f"kref://Atlas/People/{self._slug(participant)}.person",
                predicate="closeness.limitless_mentions_90d",
                object_value="1",
                confidence=0.6,
                evidence_source=path.name,
                evidence_source_family="capture",
                evidence_kref=evidence_kref,
                evidence_timestamp=evidence_ts,
            ))

        # Action items → Commitment claims
        for item in self._as_list(frontmatter.get("action_items", [])):
            claims.append(ExtractedClaim(
                lane="atlas_observational",
                assertion_type="episode",
                subject_kref=f"kref://Atlas/Commitments/{self._slug(item)}.commitment",
                predicate="commitment.described",
                object_value=item,
                confidence=0.55,
                evidence_source=path.name,
                evidence_source_family="capture",
                evidence_kref=evidence_kref,
                evidence_timestamp=evidence_ts,
            ))

        # Decisions → Decision claims
        for decision in self._as_list(frontmatter.get("decisions", [])):
            claims.append(ExtractedClaim(
                lane="atlas_observational",
                assertion_type="decision",
                subject_kref=f"kref://Atlas/Decisions/{self._slug(decision)}.decision",
                predicate="decision.outcome",
                object_value=decision,
                confidence=0.65,
                evidence_source=path.name,
                evidence_source_family="capture",
                evidence_kref=evidence_kref,
                evidence_timestamp=evidence_ts,
            ))

        # Projects → Project mention claims (status update)
        for project in self._as_list(frontmatter.get("projects", [])):
            claims.append(ExtractedClaim(
                lane="atlas_observational",
                assertion_type="factual_assertion",
                subject_kref=f"kref://Atlas/Projects/{self._slug(project)}.project",
                predicate="project.mentioned_in_session",
                object_value="true",
                confidence=0.55,
                evidence_source=path.name,
                evidence_source_family="capture",
                evidence_kref=evidence_kref,
                evidence_timestamp=evidence_ts,
            ))

        return claims

    def cursor_for_event(self, event: dict[str, Any]) -> IngestionCursor:
        return IngestionCursor(
            stream=self.stream,
            last_processed_at=event["mtime"],
            last_processed_id=event["filename"],
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _parse_frontmatter(self, content: str) -> dict[str, Any]:
        """Minimal YAML-style frontmatter parser handling lists indicated as
        either inline `[a, b]` OR YAML-multiline `- a / - b` form."""
        match = _FRONTMATTER.match(content)
        if not match:
            return {}

        out: dict[str, Any] = {}
        body = match.group(1)
        lines = body.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                i += 1
                continue

            if ":" not in line:
                i += 1
                continue

            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            if value.startswith("[") and value.endswith("]"):
                items = [v.strip().strip('"\'') for v in value[1:-1].split(",")]
                out[key] = [i for i in items if i]
                i += 1
            elif not value:
                # Multiline list — collect indented `- item` lines
                items = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if next_line.strip().startswith("- "):
                        items.append(next_line.strip()[2:].strip().strip('"\''))
                        j += 1
                    elif not next_line.strip():
                        j += 1
                    else:
                        break
                out[key] = items
                i = j
            else:
                if value.startswith('"') and value.endswith('"'):
                    out[key] = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    out[key] = value[1:-1]
                else:
                    out[key] = value
                i += 1

        return out

    def _as_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str) and value:
            return [value]
        return []

    def _slug(self, s: str) -> str:
        return re.sub(r"[^\w\-]", "_", s).strip("_")[:60].lower()
