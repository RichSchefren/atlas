"""Adjudication resolver — closes the Ripple loop.

When Rich resolves a markdown adjudication entry (or an MCP client
calls `adjudication.resolve`), this module:

  1. Locates the queue file by `proposal_id` (frontmatter scan)
  2. Parses the proposal context (target_kref, current/proposed confidence)
  3. Applies the decision through the AGM operator:
       accept / adjust  → revise(target, {confidence: chosen_value})
       reject           → no AGM op; archive only
       demote_core      → clear core flag, then revise
  4. Appends a `ripple_adjudication_resolved` event to the hash-chained
     ledger (audit trail; tamper detectable via verify_chain())
  5. Moves the markdown file to `<adjudication>/resolved/`
  6. Returns ResolveOutcome — the value MCP / HTTP / fswatch all surface

Spec: 06 - Ripple Algorithm Spec § 6.4 (resolution roundtrip)
       05 - Architecture & Schema § 4 (AGM revise contract)
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from atlas_core.revision.uri import Kref
from atlas_core.ripple.adjudication import DEFAULT_ADJUDICATION_DIR

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from atlas_core.trust import HashChainedLedger


log = logging.getLogger(__name__)


# Decisions an MCP client can send in. Mirror the markdown checkbox values.
VALID_DECISIONS: frozenset[str] = frozenset(
    {"accept", "reject", "adjust", "demote_core"}
)

RESOLVED_SUBDIR: str = "resolved"
"""Files move here once the AGM op has been applied + ledger entry written."""


# ─── Result shape ───────────────────────────────────────────────────────────


@dataclass
class ResolveOutcome:
    """Returned to the caller of `resolve_adjudication()`.

    `applied` is True iff the AGM operator actually mutated the graph.
    `reject` always returns applied=False even on success — the proposal
    is dropped intentionally.
    """

    proposal_id: str
    decision: str
    target_kref: str
    applied: bool
    new_revision_kref: Optional[str] = None
    superseded_kref: Optional[str] = None
    confidence_set: Optional[float] = None
    ledger_event_id: Optional[str] = None
    archived_to: Optional[str] = None
    notes: list[str] = field(default_factory=list)


# ─── Frontmatter parser ─────────────────────────────────────────────────────


_FRONTMATTER = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract the YAML-style frontmatter from an adjudication markdown.

    We don't need a full YAML parser — every adjudication file is written
    by `_format_adjudication_markdown` with `key: value` lines only, no
    nesting or lists.
    """
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


_CONFIDENCE_LINE = re.compile(r"\*\*Proposed:\*\*\s+([0-9.]+)")
_CURRENT_LINE = re.compile(r"\*\*Current:\*\*\s+([0-9.]+)")


def _parse_confidences(text: str) -> tuple[float, float]:
    """Extract (current, proposed) confidence from the markdown body."""
    cur_match = _CURRENT_LINE.search(text)
    prop_match = _CONFIDENCE_LINE.search(text)
    cur = float(cur_match.group(1)) if cur_match else 0.0
    prop = float(prop_match.group(1)) if prop_match else cur
    return cur, prop


# ─── Lookup ─────────────────────────────────────────────────────────────────


def find_pending_entry(
    proposal_id: str,
    *,
    directory: Path | None = None,
) -> Optional[Path]:
    """Scan the adjudication directory for a file whose frontmatter
    `proposal_id` matches. Returns None if not found.

    Phase 2 W6 stub callers got `applied=False`; this is the lookup the
    real resolver uses to find what to act on.
    """
    target_dir = directory or DEFAULT_ADJUDICATION_DIR
    if not target_dir.exists():
        return None
    for path in sorted(target_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        if fm.get("proposal_id") == proposal_id:
            return path
    return None


# ─── Resolver ───────────────────────────────────────────────────────────────


async def resolve_adjudication(
    proposal_id: str,
    decision: str,
    *,
    driver: AsyncDriver,
    ledger: HashChainedLedger,
    adjusted_confidence: Optional[float] = None,
    actor: str = "rich",
    directory: Path | None = None,
) -> ResolveOutcome:
    """Apply a human decision on a queued adjudication entry.

    Args:
        proposal_id: Frontmatter id from the markdown queue file
        decision: One of accept / reject / adjust / demote_core
        driver: Live Neo4j driver — passed through to AGM `revise()`
        ledger: Hash-chained ledger — gets an audit event for every
            non-reject outcome
        adjusted_confidence: Required when decision == 'adjust'
        actor: Audit attribution; defaults to 'rich'
        directory: Override adjudication queue directory (testing)

    Returns:
        ResolveOutcome with applied / new_revision_kref / ledger_event_id

    Raises:
        ValueError: invalid decision, missing adjusted_confidence,
            or proposal_id not found
    """
    from atlas_core.revision.agm import revise

    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"decision must be one of {sorted(VALID_DECISIONS)}; got {decision!r}"
        )
    if decision == "adjust" and adjusted_confidence is None:
        raise ValueError("adjusted_confidence required when decision='adjust'")

    target_dir = directory or DEFAULT_ADJUDICATION_DIR
    entry_path = find_pending_entry(proposal_id, directory=target_dir)
    if entry_path is None:
        raise ValueError(
            f"adjudication entry not found for proposal_id={proposal_id!r} "
            f"under {target_dir}"
        )

    text = entry_path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    target_kref_str = fm.get("target_kref", "")
    if not target_kref_str:
        raise ValueError(
            f"adjudication entry {entry_path} has no target_kref in frontmatter"
        )

    current_conf, proposed_conf = _parse_confidences(text)

    outcome = ResolveOutcome(
        proposal_id=proposal_id,
        decision=decision,
        target_kref=target_kref_str,
        applied=False,
    )

    if decision == "reject":
        outcome.notes.append("decision=reject; no AGM op applied")
    else:
        chosen_conf = (
            adjusted_confidence if decision == "adjust" else proposed_conf
        )
        outcome.confidence_set = chosen_conf

        # Build minimal new content. A full revision in production carries
        # the belief text + typed schema; for a confidence-only resolve
        # the AGM operator records the supersession with the new value.
        new_content: dict[str, Any] = {
            "confidence": chosen_conf,
            "previous_confidence": current_conf,
            "proposal_id": proposal_id,
        }
        if decision == "demote_core":
            new_content["core_protected"] = False
            outcome.notes.append("core_protected flag cleared")

        target_kref = Kref.parse(target_kref_str)
        revision_outcome = await revise(
            driver=driver,
            target_kref=target_kref,
            new_content=new_content,
            revision_reason=(
                f"adjudication.resolve {decision} (proposal_id={proposal_id})"
            ),
            actor=actor,
        )
        outcome.applied = True
        outcome.new_revision_kref = revision_outcome.new_revision_kref.to_string()
        outcome.superseded_kref = (
            revision_outcome.superseded_kref.to_string()
            if revision_outcome.superseded_kref else None
        )

    # Audit event — every resolve writes to the ledger, even rejects.
    # Accept/adjust/demote_core actually superseded a revision; reject is
    # a refinement (audit-only annotation, no graph mutation).
    from atlas_core.trust.ledger import EventType

    event_type = (
        EventType.SUPERSEDE if outcome.applied else EventType.REFINE
    )
    # Object/root parsing — for resolver audit, the target's root kref
    # is the object_id + root_id (the revision is the new_revision_kref).
    target_kref_obj = Kref.parse(target_kref_str)
    object_id = (
        outcome.new_revision_kref or target_kref_obj.root_kref().to_string()
    )
    root_id = target_kref_obj.root_kref().to_string()

    ledger_event = ledger.append_event(
        event_type=event_type,
        actor_id=actor,
        object_id=object_id,
        object_type="ripple_adjudication",
        root_id=root_id,
        target_object_id=outcome.superseded_kref,
        reason=f"adjudication.resolve {decision} (proposal_id={proposal_id})",
        payload={
            "proposal_id": proposal_id,
            "target_kref": target_kref_str,
            "decision": decision,
            "actor": actor,
            "applied": outcome.applied,
            "confidence_set": outcome.confidence_set,
            "new_revision_kref": outcome.new_revision_kref,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    outcome.ledger_event_id = ledger_event.event_id

    # Archive the markdown file regardless of decision.
    resolved_dir = target_dir / RESOLVED_SUBDIR
    resolved_dir.mkdir(parents=True, exist_ok=True)
    archive_path = resolved_dir / entry_path.name
    shutil.move(str(entry_path), str(archive_path))
    outcome.archived_to = str(archive_path)

    log.info(
        "Adjudication resolved: id=%s decision=%s applied=%s "
        "new_revision=%s ledger_event=%s",
        proposal_id, decision, outcome.applied,
        outcome.new_revision_kref, outcome.ledger_event_id,
    )
    return outcome
