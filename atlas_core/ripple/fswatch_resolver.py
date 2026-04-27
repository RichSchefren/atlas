"""fswatch-driven adjudication resolver.

Backup path to the Obsidian plugin for users who prefer headless
operation. Watches the adjudication queue directory for file
modifications; when a saved file has a checked decision box,
fires `resolve_adjudication()` and archives the file.

Uses watchdog (already a dependency) for cross-platform file
watching — works on macOS without fswatch installed.

Spec: PHASE-5-AND-BEYOND.md § 1.2 (fallback to Obsidian plugin)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from atlas_core.trust import HashChainedLedger


log = logging.getLogger(__name__)


# Regex matchers for the four decision checkboxes in the queue file
_DECISION_REGEXES = (
    (re.compile(r"^- \[x\] \*\*Accept\*\*", re.IGNORECASE | re.MULTILINE), "accept"),
    (re.compile(r"^- \[x\] \*\*Reject\*\*", re.IGNORECASE | re.MULTILINE), "reject"),
    (re.compile(r"^- \[x\] \*\*Adjust\*\*", re.IGNORECASE | re.MULTILINE), "adjust"),
    (re.compile(r"^- \[x\] \*\*Demote core conviction\*\*", re.IGNORECASE | re.MULTILINE), "demote_core"),
)

_FRONTMATTER_PROPOSAL_ID = re.compile(
    r"^proposal_id:\s*(\S+)", re.MULTILINE,
)

_ADJUST_CONFIDENCE = re.compile(
    r"^- \[x\] \*\*Adjust\*\* — set confidence to:\s*([0-9.]+)",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class ResolverEvent:
    """One file-modification observation the resolver acted on."""

    path: Path
    proposal_id: str
    decision: str
    applied: bool
    error: str | None = None


def parse_decision(text: str) -> tuple[str | None, float | None]:
    """Inspect the markdown body. Returns (decision, adjusted_confidence)
    or (None, None) if no checkbox is checked."""
    for pattern, label in _DECISION_REGEXES:
        if pattern.search(text):
            if label == "adjust":
                m = _ADJUST_CONFIDENCE.search(text)
                conf = float(m.group(1)) if m else None
                return label, conf
            return label, None
    return None, None


def parse_proposal_id(text: str) -> str | None:
    m = _FRONTMATTER_PROPOSAL_ID.search(text)
    return m.group(1).strip() if m else None


async def resolve_one(
    path: Path,
    *,
    driver: AsyncDriver,
    ledger: HashChainedLedger,
    actor: str = "rich",
    directory: Path | None = None,
) -> ResolverEvent:
    """Read one adjudication file, detect a checked decision, fire
    resolve_adjudication. Used by both the live watcher and the
    one-shot CLI."""
    from atlas_core.ripple.resolver import resolve_adjudication

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ResolverEvent(
            path=path, proposal_id="", decision="",
            applied=False, error=f"read failed: {exc}",
        )

    proposal_id = parse_proposal_id(text)
    if not proposal_id:
        return ResolverEvent(
            path=path, proposal_id="", decision="",
            applied=False, error="no proposal_id in frontmatter",
        )

    decision, adjusted_conf = parse_decision(text)
    if decision is None:
        # No decision yet — file is still being edited
        return ResolverEvent(
            path=path, proposal_id=proposal_id, decision="",
            applied=False, error="no checked decision",
        )

    try:
        outcome = await resolve_adjudication(
            proposal_id=proposal_id,
            decision=decision,
            driver=driver,
            ledger=ledger,
            adjusted_confidence=adjusted_conf,
            actor=actor,
            directory=directory or path.parent,
        )
        return ResolverEvent(
            path=path, proposal_id=proposal_id, decision=decision,
            applied=outcome.applied,
        )
    except Exception as exc:
        log.exception("Resolve failed for %s", path)
        return ResolverEvent(
            path=path, proposal_id=proposal_id, decision=decision,
            applied=False, error=f"{type(exc).__name__}: {exc}",
        )


class AdjudicationWatcher:
    """Long-running watcher over the adjudication directory.

    Uses watchdog's PollingObserver (works on macOS + Linux + Windows
    without OS-level events). On every modify event, calls
    `resolve_one()` and emits an SSE event so the Obsidian plugin
    sidebar updates in real time.
    """

    def __init__(
        self,
        adjudication_dir: Path,
        *,
        driver: AsyncDriver,
        ledger: HashChainedLedger,
        actor: str = "rich",
    ):
        self.adjudication_dir = Path(adjudication_dir)
        self.driver = driver
        self.ledger = ledger
        self.actor = actor

    async def scan_once(self) -> list[ResolverEvent]:
        """One-shot pass: process every .md file currently in the
        directory. Returns the list of events. Useful as a CLI
        without committing to the long-running watcher."""
        events: list[ResolverEvent] = []
        if not self.adjudication_dir.exists():
            return events
        for path in sorted(self.adjudication_dir.glob("*.md")):
            ev = await resolve_one(
                path,
                driver=self.driver,
                ledger=self.ledger,
                actor=self.actor,
                directory=self.adjudication_dir,
            )
            events.append(ev)
        return events

    async def run_forever(self, *, poll_interval_sec: float = 2.0) -> None:
        """Block on a polling loop. Call from an asyncio task; cancel
        the task to stop. Best invoked from a launchd plist or a
        terminal session you'll keep open."""
        log.info(
            "AdjudicationWatcher polling %s every %.1fs",
            self.adjudication_dir, poll_interval_sec,
        )
        seen_mtimes: dict[Path, float] = {}
        while True:
            try:
                if self.adjudication_dir.exists():
                    for path in sorted(self.adjudication_dir.glob("*.md")):
                        try:
                            mtime = path.stat().st_mtime
                        except OSError:
                            continue
                        if seen_mtimes.get(path) == mtime:
                            continue
                        seen_mtimes[path] = mtime
                        ev = await resolve_one(
                            path,
                            driver=self.driver,
                            ledger=self.ledger,
                            actor=self.actor,
                            directory=self.adjudication_dir,
                        )
                        if ev.applied:
                            from atlas_core.api.events import (
                                emit_adjudication_resolved,
                            )
                            emit_adjudication_resolved(
                                proposal_id=ev.proposal_id,
                                decision=ev.decision,
                                applied=True,
                            )
            except Exception:
                log.exception("Watcher tick failed; continuing")
            await asyncio.sleep(poll_interval_sec)
