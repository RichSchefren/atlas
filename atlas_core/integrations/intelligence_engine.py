"""Bridge between Atlas events and Rich's existing Intelligence Engine.

Atlas surfaces interesting events (adjudication queue entries, Ripple
cascades that produced strategic-bucket items, ledger SUPERSEDE events)
to a JSONL file the Intelligence Engine pipeline reads on its next run.

The Intelligence Engine then materializes the events into the existing
BRIEFING.md surface Rich already reads every morning. This is the
"Atlas integrates rather than competes" principle.

Spec: PHASE-5-AND-BEYOND.md § 1.7
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


DEFAULT_BRAIN_DIR: Path = (
    Path.home() / ".atlas" / "brain"
)
"""Where Rich's Intelligence Engine reads from. Atlas writes
atlas-events.json here for the brain pipeline to consume."""

DEFAULT_EVENTS_FILE: str = "atlas-events.jsonl"


@dataclass
class AtlasEvent:
    """One event Atlas wants the brain pipeline to know about."""

    kind: str            # "adjudication_resolved" | "ripple_cascade" | "supersede"
    summary: str         # one-line for BRIEFING.md
    occurred_at: str     # ISO 8601 UTC
    actor: str = "atlas"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "occurred_at": self.occurred_at,
            "actor": self.actor,
            "details": self.details,
        }


class IntelligenceEngineBridge:
    """Append-only JSONL writer for Atlas → Intelligence Engine events.

    The Intelligence Engine's pipeline truncates after consuming, so
    Atlas's job is just to append events as they happen.
    """

    def __init__(
        self,
        *,
        brain_dir: Path | None = None,
        events_filename: str = DEFAULT_EVENTS_FILE,
    ):
        self.brain_dir = Path(brain_dir or DEFAULT_BRAIN_DIR)
        self.events_path = self.brain_dir / events_filename

    def emit(self, event: AtlasEvent) -> None:
        """Append the event as a JSONL line. Creates the file + parent
        directory on demand. Errors don't crash the caller — bridge
        failure should not block Atlas's main pipeline."""
        try:
            self.brain_dir.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), separators=(",", ":")))
                f.write("\n")
        except OSError as exc:
            log.warning(
                "IntelligenceEngineBridge emit failed (path=%s): %s",
                self.events_path, exc,
            )

    def emit_adjudication_resolved(
        self,
        *,
        proposal_id: str,
        decision: str,
        target_kref: str,
        applied: bool,
        actor: str = "rich",
    ) -> None:
        """Convenience: shape an adjudication.resolve outcome into an
        AtlasEvent and emit it."""
        verb = {
            "accept": "accepted",
            "reject": "rejected",
            "adjust": "adjusted confidence on",
            "demote_core": "demoted core protection on",
        }.get(decision, decision)
        summary = f"{actor.capitalize()} {verb} adjudication on {target_kref}"
        if not applied:
            summary += " (no graph mutation)"
        self.emit(AtlasEvent(
            kind="adjudication_resolved",
            summary=summary,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            details={
                "proposal_id": proposal_id,
                "decision": decision,
                "target_kref": target_kref,
                "applied": applied,
            },
        ))

    def emit_ripple_cascade(
        self,
        *,
        upstream_kref: str,
        impacted_count: int,
        contradictions_count: int,
    ) -> None:
        """Convenience: shape a Ripple cascade outcome."""
        summary = (
            f"Ripple cascade from {upstream_kref}: "
            f"{impacted_count} impacted, "
            f"{contradictions_count} contradictions"
        )
        self.emit(AtlasEvent(
            kind="ripple_cascade",
            summary=summary,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            details={
                "upstream_kref": upstream_kref,
                "impacted_count": impacted_count,
                "contradictions_count": contradictions_count,
            },
        ))
