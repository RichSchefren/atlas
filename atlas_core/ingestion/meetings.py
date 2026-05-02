"""Meetings extractor — filesystem-based ingestion of structured meeting notes.

Replaces the deferred Fireflies GraphQL stub with a much-better source: the
Strategic-Profits/2026 Meetings/ folder where Rich already has 800+ meeting
markdown files. Many of them are pre-processed by an upstream LCL pipeline
that adds structured YAML frontmatter — action_items, decisions, people —
which means Atlas doesn't need an LLM to extract claims; it just parses
the frontmatter directly.

Three classes of meeting file are handled:

1. **LCL-processed** (frontmatter has `lcl_processed: true`):
     - Each item in `action_items` → `commitment.action_item` claim
     - Each item in `decisions` → `decision.outcome` claim
     - Each name in `people` → `episode.attended_meeting` claim
   Confidence 0.85 — these are already structured.

2. **Morning Standups** (filename starts `Standup-Brief-`):
     - Parses the `## Open Action Items` section by person header
     - Parses the `## Key Outcomes` section by bullet
     - Confidence 0.70 — section-regex parse, less rigorous than LCL.

3. **Other** (no recognizable structure):
     - Skipped silently. Future LLM extraction is the right path.

The cursor is the latest file mtime processed; on rerun, only files newer
than the cursor are touched. Idempotent.

Lane: `atlas_meetings` — distinct from `atlas_observational` (Limitless
ambient) so the trust layer can promote business-grade meeting commitments
without contamination from coding-session dictation.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from atlas_core.ingestion.base import (
    BaseExtractor,
    ExtractedClaim,
    IngestionCursor,
    StreamConfig,
    StreamType,
)
from atlas_core.ingestion.confidence import STREAM_CONFIDENCE_FLOORS
from atlas_core.people import registry as _people_registry

log = logging.getLogger(__name__)


# ─── Configuration ──────────────────────────────────────────────────────────


DEFAULT_MEETINGS_ROOT = Path.home() / "Obsidian" / "Strategic-Profits" / "2026 Meetings"

LANE_NAME = "atlas_meeting"

# Confidence tiers for the three parse paths
CONF_LCL_PROCESSED = 0.85   # YAML-tagged structured extraction
CONF_STANDUP_PARSED = 0.70  # section-regex on Morning Standup briefs


# ─── kref helpers ───────────────────────────────────────────────────────────


def _slug(text: str, max_len: int = 80) -> str:
    """Lowercase + underscore-normalize for kref construction."""
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:max_len] or "unknown"


def _canonical_person_name(name: str) -> str | None:
    """Resolve a name through the People Registry.

    Returns the canonical name if known, the original cleaned name if
    unknown but human-shaped, or None if the registry classifies it as
    non-human (Claude, Cloud, Team, etc.).
    """
    result = _people_registry.resolve(name)
    if result is None:
        return name.strip() or None  # unknown person — keep as-is
    canonical, info = result
    if info.type == "non_human":
        return None
    return canonical


def _person_kref(name: str) -> str:
    """Person kref under canonical name. Returns empty string for non-humans."""
    canonical = _canonical_person_name(name)
    if canonical is None:
        return ""
    return f"kref://Atlas/People/{_slug(canonical)}.person"


def _commitment_kref(person: str, what: str) -> str:
    """Commitment kref using canonical person name (or original if unknown)."""
    canonical = _canonical_person_name(person)
    if canonical is None:
        # Non-human — fall back to the original raw person string so the
        # commitment isn't silently dropped, but it won't merge with a
        # person entity either. Caller may decide to skip.
        canonical = person
    return (
        f"kref://Atlas/Commitments/{_slug(canonical)}__"
        f"{_slug(what, max_len=80)}.commitment"
    )


def _decision_kref(text: str) -> str:
    return f"kref://Atlas/Decisions/{_slug(text, max_len=80)}.decision"


def _meeting_kref(meeting_path: Path) -> str:
    """Stable kref for a meeting file based on its repo-relative path."""
    rel = meeting_path.name.replace(".md", "")
    return f"kref://Atlas/Meetings/{_slug(rel)}.meeting"


# ─── Frontmatter parsing ────────────────────────────────────────────────────


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


_RICH_NAME_PATTERNS = (
    "richard schefren",
    "rich schefren",
    "rich-schefren",
    "richard-schefren",
    "richonly@strategicprofits.com",
)


def _is_rich(name: object) -> bool:
    """Loose match — Rich appears under several names across LCL formats."""
    s = str(name).lower().strip()
    if s in {"rich", "richard"}:
        return True
    return any(p in s for p in _RICH_NAME_PATTERNS)


# Filenames that indicate a meeting Rich ran or attended even when no
# participant list is in the frontmatter. These names are about Rich's
# business by definition (standups about him, weekly reports for him,
# his VIP sessions, calls he's named in).
_RICH_FILENAME_INDICATORS = (
    "standup-brief",
    "standup-extract",
    "weekly-report",
    "compression window",   # Rich's VIP sessions
    "rich schefren",        # any "X & Rich Schefren" pattern
    "richard schefren",
    " w-rich",              # "ZenithPro Office Hours w-Rich"
    " w/rich",
    " with rich",
    " - rich.",             # "Ben - Rich. Dashboards"
    "rich -",
    "rich. ",
    "& rich ",
)


def _filename_indicates_rich(path: Path) -> bool:
    """True if the filename is a positive Rich-attendance signal."""
    name = path.name.lower()
    return any(p in name for p in _RICH_FILENAME_INDICATORS)


# Filenames that indicate a meeting Tom or another team member ran solo
# with clients/students. These get hard-skipped even if no other signal
# is present.
_NON_RICH_FILENAME_INDICATORS = (
    "tech set up",
    "tech setup",
    "onboarding",
    "coaching acct",       # Tom's accountability calls
    "copy clinic",         # Tom's student copy clinics
    "ops & tech session",  # Tom-led infra
    "office hours",        # student office hours (default Tom; explicit "w-Rich" caught above)
)


def _filename_indicates_not_rich(path: Path) -> bool:
    """True if the filename strongly signals a Tom-only / client-only call."""
    name = path.name.lower()
    if _filename_indicates_rich(path):
        return False  # explicit Rich indicator wins
    return any(p in name for p in _NON_RICH_FILENAME_INDICATORS)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split frontmatter YAML from body. Returns (frontmatter_dict, body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    yaml_text = match.group(1)
    try:
        fm = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        log.warning("malformed frontmatter, treating as empty: %s", exc)
        fm = {}
    body = text[match.end():]
    if not isinstance(fm, dict):
        return {}, body
    return fm, body


# ─── Action-item parsing ────────────────────────────────────────────────────


# Action items are typically formatted "Person Name: do this thing by date"
# We split on the first colon to extract the responsible party.
_ACTION_PERSON_SPLIT = re.compile(r"^\s*([^:]{1,40}):\s*(.+)$", re.DOTALL)


def parse_action_item(item: object) -> tuple[str | None, str]:
    """Pull the responsible person off an action item.

    Two real-world shapes survive YAML parsing:

      "Sam: Run mimetic research"              → ("Sam", "Run mimetic ...")
      {"Sam": "Run mimetic research"}          → ("Sam", "Run mimetic ...")
                                                 (YAML promotes "- Sam: action"
                                                 to a single-key dict)
      "Schedule the team off-site"             → (None,  "Schedule ...")
    """
    # Dict form: YAML promoted "- Sam: action" to {"Sam": "action"}
    if isinstance(item, dict) and len(item) == 1:
        person, what = next(iter(item.items()))
        person = str(person).strip()
        what = str(what).strip() if what is not None else ""
        if len(person.split()) <= 5 and not person.endswith((".", "?", "!")):
            return person, what
        return None, f"{person}: {what}".strip()

    text = str(item).strip()
    match = _ACTION_PERSON_SPLIT.match(text)
    if not match:
        return None, text
    person, what = match.group(1).strip(), match.group(2).strip()
    # Only treat as person if the prefix looks like a name (not just numbers, not
    # a long sentence). Cheap heuristic: <= 5 words and no terminal punctuation.
    if len(person.split()) > 5 or person.endswith((".", "?", "!")):
        return None, text
    return person, what


# ─── Morning Standup section parser ─────────────────────────────────────────


# Match `### {Person}` headers inside the Open Action Items section
_STANDUP_PERSON_HEADER = re.compile(r"^###\s+(.{1,40})\s*$", re.MULTILINE)


def parse_standup_action_items(body: str) -> list[tuple[str, str]]:
    """Pull (person, action_item_text) pairs from a Morning Standup body.

    Returns the bullets under each `### {Name}` heading inside the
    `## Open Action Items` section.
    """
    out: list[tuple[str, str]] = []
    # Find the Open Action Items section
    section_match = re.search(
        r"^##\s+Open Action Items\s*$(.*?)(?=^##\s|\Z)",
        body, re.DOTALL | re.MULTILINE,
    )
    if not section_match:
        return out
    section = section_match.group(1)

    # Walk the per-person subsections
    for header_match in _STANDUP_PERSON_HEADER.finditer(section):
        person = header_match.group(1).strip()
        # Skip the "Ben / Tom / Others" catch-all heading
        if "/" in person or person.lower() == "others":
            continue
        # Bullets until the next ### or end of section
        start = header_match.end()
        next_header = _STANDUP_PERSON_HEADER.search(section, start)
        block_end = next_header.start() if next_header else len(section)
        block = section[start:block_end]
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("- "):
                action = line[2:].strip()
                # Strip trailing footnote-style references like *(P003)*
                action = re.sub(r"\s*\*\(\w+\)\*\s*$", "", action)
                if action and "no open" not in action.lower():
                    out.append((person, action))
    return out


# ─── Extractor ──────────────────────────────────────────────────────────────


class MeetingsExtractor(BaseExtractor):
    """Filesystem walker for structured meeting markdown files.

    Cursor is `last_processed_at` = ISO of the latest file mtime processed.
    Files are processed in mtime order so the cursor advances monotonically.
    """

    stream = StreamType.FIREFLIES  # reuses the existing slot — distinct lane in candidates

    def __init__(
        self,
        *,
        quarantine,
        meetings_root: Path | None = None,
        config: StreamConfig | None = None,
    ):
        super().__init__(
            quarantine=quarantine,
            config=config or StreamConfig(
                confidence_floor=STREAM_CONFIDENCE_FLOORS[StreamType.FIREFLIES],
            ),
        )
        self.meetings_root = meetings_root or DEFAULT_MEETINGS_ROOT

    # ── Stream contract ─────────────────────────────────────────────────────

    def fetch_new_events(self, cursor: IngestionCursor) -> list[dict[str, Any]]:
        """Walk the meetings folder for files newer than the cursor.

        Each event is `{"path": Path, "mtime_iso": str, "text": str}`.
        """
        if not self.meetings_root.exists():
            log.warning("meetings root %s does not exist; skipping", self.meetings_root)
            return []

        cursor_iso = cursor.last_processed_at
        events: list[dict[str, Any]] = []
        for path in self.meetings_root.rglob("*.md"):
            mtime_iso = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc,
            ).isoformat()
            if mtime_iso <= cursor_iso:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                log.warning("skip unreadable meeting file %s: %s", path, exc)
                continue
            events.append({"path": path, "mtime_iso": mtime_iso, "text": text})

        # Process oldest first so cursor advances monotonically
        events.sort(key=lambda e: e["mtime_iso"])
        if len(events) > self.config.max_events_per_run:
            events = events[: self.config.max_events_per_run]
        return events

    def cursor_for_event(self, event: dict[str, Any]) -> IngestionCursor:
        return IngestionCursor(
            stream=self.stream,
            last_processed_at=event["mtime_iso"],
            last_processed_id=str(event["path"]),
        )

    def extract_claims_from_event(
        self, event: dict[str, Any],
    ) -> list[ExtractedClaim]:
        path: Path = event["path"]
        text: str = event["text"]
        fm, body = parse_frontmatter(text)

        # No attendance-based filtering at ingestion. Atlas wants to know
        # everything happening in the company — Tom's tech setup calls,
        # onboarding calls, copy clinics, accountability calls all stay
        # in the graph. The dashboard/briefing layer (built downstream)
        # is what filters by tier and Rich-attendance for the daily view.
        #
        # The two filename-pattern helpers (_filename_indicates_rich /
        # _filename_indicates_not_rich) remain for later use by the
        # surfacing layer — they're documentation, not gates.
        pass

        meeting_kref = _meeting_kref(path)
        meeting_date = self._meeting_date(fm, event["mtime_iso"])
        evidence_kref = f"kref://Atlas/Meetings/{path.name}"

        if fm.get("lcl_processed") is True:
            return list(self._claims_from_lcl(
                fm=fm, meeting_kref=meeting_kref,
                evidence_source=path.name, evidence_kref=evidence_kref,
                meeting_date=meeting_date,
            ))
        if path.name.startswith("Standup-Brief-"):
            return list(self._claims_from_standup(
                body=body, meeting_kref=meeting_kref,
                evidence_source=path.name, evidence_kref=evidence_kref,
                meeting_date=meeting_date,
            ))
        # Unknown structure — skip cleanly
        return []

    # ── Claim builders ──────────────────────────────────────────────────────

    def _meeting_date(self, fm: dict, fallback_iso: str) -> str:
        """Best ISO timestamp for the meeting — frontmatter date wins, else mtime."""
        d = fm.get("date")
        if isinstance(d, datetime):
            return d.replace(tzinfo=d.tzinfo or timezone.utc).isoformat()
        if isinstance(d, str):
            try:
                # Accept YYYY-MM-DD or full ISO
                return datetime.fromisoformat(d.replace("Z", "+00:00")).isoformat()
            except ValueError:
                pass
        return fallback_iso

    def _claims_from_lcl(
        self,
        *,
        fm: dict,
        meeting_kref: str,
        evidence_source: str,
        evidence_kref: str,
        meeting_date: str,
    ):
        # Action items → commitment claims
        for raw in fm.get("action_items") or []:
            if raw is None:
                continue
            person, what = parse_action_item(raw)
            if person is None:
                # No clear owner — attribute to the meeting itself
                yield self._build_claim(
                    assertion_type="procedure",
                    subject_kref=meeting_kref,
                    predicate="commitment.action_item",
                    object_value=what,
                    confidence=CONF_LCL_PROCESSED,
                    evidence_source=evidence_source,
                    evidence_kref=evidence_kref,
                    evidence_timestamp=meeting_date,
                )
                continue
            yield self._build_claim(
                assertion_type="procedure",
                subject_kref=_commitment_kref(person, what),
                predicate="commitment.action_item",
                object_value=f"{person}: {what}",
                confidence=CONF_LCL_PROCESSED,
                evidence_source=evidence_source,
                evidence_kref=evidence_kref,
                evidence_timestamp=meeting_date,
            )

        # Decisions → decision claims
        for raw in fm.get("decisions") or []:
            if raw is None:
                continue
            raw = str(raw)
            yield self._build_claim(
                assertion_type="decision",
                subject_kref=_decision_kref(raw),
                predicate="decision.outcome",
                object_value=raw,
                confidence=CONF_LCL_PROCESSED,
                evidence_source=evidence_source,
                evidence_kref=evidence_kref,
                evidence_timestamp=meeting_date,
            )

        # People → attendance claims (one per attendee).
        # Non-human entries (Claude, Cloud, "Team", "Someone") get filtered
        # via the People Registry — they should never appear as attendees.
        seen_people = set()
        for raw in (fm.get("people") or fm.get("participants") or []):
            if raw is None:
                continue
            # Strip parenthetical handles: "Tom (tomhammaker)" -> "Tom"
            name = re.sub(r"\s*\([^)]+\)\s*$", "", str(raw)).strip()
            if not name:
                continue
            person_kref = _person_kref(name)
            if not person_kref:
                continue  # non-human, drop
            # Dedup canonical: "Nicole" + "Nicole Mickevicius" both → one claim
            if person_kref in seen_people:
                continue
            seen_people.add(person_kref)
            yield self._build_claim(
                assertion_type="episode",
                subject_kref=person_kref,
                predicate="episode.attended_meeting",
                object_value=meeting_kref,
                confidence=CONF_LCL_PROCESSED,
                evidence_source=evidence_source,
                evidence_kref=evidence_kref,
                evidence_timestamp=meeting_date,
            )

    def _claims_from_standup(
        self,
        *,
        body: str,
        meeting_kref: str,
        evidence_source: str,
        evidence_kref: str,
        meeting_date: str,
    ):
        for person, action in parse_standup_action_items(body):
            yield self._build_claim(
                assertion_type="procedure",
                subject_kref=_commitment_kref(person, action),
                predicate="commitment.action_item",
                object_value=f"{person}: {action}",
                confidence=CONF_STANDUP_PARSED,
                evidence_source=evidence_source,
                evidence_kref=evidence_kref,
                evidence_timestamp=meeting_date,
            )

    def _build_claim(
        self,
        *,
        assertion_type: str,
        subject_kref: str,
        predicate: str,
        object_value: str,
        confidence: float,
        evidence_source: str,
        evidence_kref: str,
        evidence_timestamp: str,
    ) -> ExtractedClaim:
        return ExtractedClaim(
            lane=LANE_NAME,
            assertion_type=assertion_type,
            subject_kref=subject_kref,
            predicate=predicate,
            object_value=object_value,
            confidence=confidence,
            evidence_source=evidence_source,
            evidence_source_family="meeting",
            evidence_kref=evidence_kref,
            evidence_timestamp=evidence_timestamp,
        )
