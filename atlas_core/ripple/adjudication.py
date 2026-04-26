"""Adjudication routing — Ripple Spec § 6.

After Reassess produces proposals and contradictions are detected, each
proposal is routed into one of three buckets:

  - ROUTINE          : auto-apply via standard AGM revise() operator
  - STRATEGIC_REVIEW : write to Obsidian markdown adjudication queue;
                       Rich resolves manually via checkbox
  - CORE_PROTECTED   : flag without acting; Rich must explicitly demote

Routing rules (from spec):
  - target.is_core_conviction == True  → CORE_PROTECTED
  - high stakes OR confidence delta ≥ 0.15 OR contradictions present → STRATEGIC
  - otherwise                                                         → ROUTINE

Spec: 06 - Ripple Algorithm Spec § 6
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from atlas_core.ripple.contradiction import ContradictionPair
    from atlas_core.ripple.reassess import ReassessmentProposal


log = logging.getLogger(__name__)


# ─── Calibration constants (Phase 3 empirical tuning) ────────────────────────

CONFIDENCE_DELTA_STRATEGIC_FLOOR: float = 0.15
"""When |new - old confidence| ≥ this, route to strategic review even if no
contradictions and stakes are low. Default 0.15 is the spec lock; calibrated
against BusinessMemBench in Phase 3."""

HIGH_STAKES_LEVELS: frozenset[str] = frozenset({"high", "critical"})
"""StakeLevel values that automatically route to strategic review."""


# ─── Bucket types ────────────────────────────────────────────────────────────


class AdjudicationRoute(str, Enum):
    AUTO_APPLY = "auto_apply"
    """Routine proposal — applied via standard AGM revise() operator."""

    STRATEGIC_REVIEW = "strategic_review"
    """High-stakes or contradiction-bearing — quarantined to Obsidian queue."""

    CORE_PROTECTED = "core_protected"
    """Target is_core_conviction=True — Rich must explicitly demote."""


@dataclass(frozen=True)
class RoutingDecision:
    """Result of routing a single proposal.

    audit-friendly: every routing decision carries the input that produced it
    so Rich can inspect why a particular proposal landed where it did.
    """

    proposal_kref: str
    route: AdjudicationRoute
    rationale: str
    contradictions_count: int = 0
    confidence_delta: float = 0.0
    stakes: str = ""
    is_core_conviction: bool = False


# ─── Routing logic ───────────────────────────────────────────────────────────


async def _fetch_target_metadata(
    driver: AsyncDriver,
    proposal_kref: str,
) -> tuple[bool, str]:
    """Read is_core_conviction + stakes from the target node."""
    cypher = """
    MATCH (n {kref: $kref})
    RETURN coalesce(n.is_core_conviction, false) AS core,
           coalesce(n.stakes, 'medium') AS stakes
    """
    async with driver.session() as session:
        result = await session.run(cypher, kref=proposal_kref)
        record = await result.single()
    if record is None:
        return (False, "medium")
    return (bool(record["core"]), str(record["stakes"]))


async def route_proposal(
    driver: AsyncDriver,
    proposal: ReassessmentProposal,
    contradictions: list[ContradictionPair],
) -> RoutingDecision:
    """Decide what bucket this proposal lands in. See module docstring for rules.

    Args:
        driver: Live Neo4j AsyncDriver — to fetch target metadata
        proposal: ReassessmentProposal from Reassess
        contradictions: full contradiction list — proposal-specific subset
                        is filtered inside

    Returns:
        RoutingDecision with route + audit-friendly rationale
    """
    is_core, stakes = await _fetch_target_metadata(driver, proposal.target_kref)
    confidence_delta = abs(proposal.new_confidence - proposal.old_confidence)
    proposal_contradictions = [
        c for c in contradictions if c.proposal_kref == proposal.target_kref
    ]
    has_contradictions = len(proposal_contradictions) > 0
    high_stakes = stakes in HIGH_STAKES_LEVELS

    if is_core:
        rationale = "Target is marked is_core_conviction=true; only Rich can demote"
        route = AdjudicationRoute.CORE_PROTECTED
    elif has_contradictions:
        rationale = (
            f"{len(proposal_contradictions)} contradiction(s) detected — "
            f"strategic review required"
        )
        route = AdjudicationRoute.STRATEGIC_REVIEW
    elif high_stakes:
        rationale = f"Stakes level '{stakes}' triggers strategic review"
        route = AdjudicationRoute.STRATEGIC_REVIEW
    elif confidence_delta >= CONFIDENCE_DELTA_STRATEGIC_FLOOR:
        rationale = (
            f"Confidence delta {confidence_delta:.2f} ≥ "
            f"{CONFIDENCE_DELTA_STRATEGIC_FLOOR:.2f} threshold"
        )
        route = AdjudicationRoute.STRATEGIC_REVIEW
    else:
        rationale = (
            f"Routine: stakes={stakes}, |Δ|={confidence_delta:.2f}, "
            f"no contradictions"
        )
        route = AdjudicationRoute.AUTO_APPLY

    return RoutingDecision(
        proposal_kref=proposal.target_kref,
        route=route,
        rationale=rationale,
        contradictions_count=len(proposal_contradictions),
        confidence_delta=confidence_delta,
        stakes=stakes,
        is_core_conviction=is_core,
    )


async def route_all(
    driver: AsyncDriver,
    proposals: list[ReassessmentProposal],
    contradictions: list[ContradictionPair],
) -> list[RoutingDecision]:
    """Route every proposal in a cascade. Returns decisions in input order."""
    decisions: list[RoutingDecision] = []
    for proposal in proposals:
        decision = await route_proposal(driver, proposal, contradictions)
        decisions.append(decision)
    log.info(
        "Adjudication routing: %d proposals → auto=%d, review=%d, core=%d",
        len(decisions),
        sum(1 for d in decisions if d.route == AdjudicationRoute.AUTO_APPLY),
        sum(1 for d in decisions if d.route == AdjudicationRoute.STRATEGIC_REVIEW),
        sum(1 for d in decisions if d.route == AdjudicationRoute.CORE_PROTECTED),
    )
    return decisions


# ─── Obsidian markdown queue writer ──────────────────────────────────────────

DEFAULT_ADJUDICATION_DIR = Path(
    "/Users/richardschefren/Obsidian/Active-Brain/00 Atlas/adjudication"
)
"""Default adjudication queue location. Overridable per environment / per
test via the directory parameter on write_adjudication_entry()."""


def _slug(s: str) -> str:
    """Filesystem-safe slug from a kref string."""
    s = re.sub(r"[^\w\-]", "_", s)
    return s.strip("_")[:80]


def _format_adjudication_markdown(
    proposal: ReassessmentProposal,
    decision: RoutingDecision,
    contradictions: list[ContradictionPair],
    proposal_id: str,
    upstream_belief_text: str = "",
) -> str:
    """Render a single adjudication queue file.

    Format follows Ripple Spec § 6.4 — checkbox-driven decision surface that
    Rich resolves directly in Obsidian. fswatch hook (Phase 2 W6) reads
    saved files and invokes the corresponding AGM operator.
    """
    now = datetime.now(timezone.utc).isoformat()

    proposal_contras = [c for c in contradictions if c.proposal_kref == proposal.target_kref]

    contradictions_section = ""
    if proposal_contras:
        contradictions_section = "\n## Contradictions detected\n\n"
        for i, c in enumerate(proposal_contras, start=1):
            contradictions_section += (
                f"{i}. **{c.category.value}** ({c.severity.value} severity)\n"
                f"   - Opposing kref: `{c.opposed_kref}`\n"
                f"   - Rationale: {c.rationale}\n\n"
            )

    components_section = ""
    if proposal.components:
        components_section = "\n## Atlas reasoning components\n\n"
        for k, v in sorted(proposal.components.items()):
            components_section += f"- `{k}` = {v:+.4f}\n"

    upstream_summary = ""
    if upstream_belief_text:
        upstream_summary = f"\n## Upstream change\n\n> {upstream_belief_text}\n"

    return f"""---
type: ripple_adjudication
status: pending
created: {now}
proposal_id: {proposal_id}
target_kref: {proposal.target_kref}
upstream_kref: {proposal.upstream_kref}
route: {decision.route.value}
contradictions_count: {decision.contradictions_count}
---

# Ripple Adjudication

**Routing decision:** `{decision.route.value}`
**Reason:** {decision.rationale}

## Confidence change proposed

- **Current:** {proposal.old_confidence:.3f}
- **Proposed:** {proposal.new_confidence:.3f}
- **Delta:** {proposal.new_confidence - proposal.old_confidence:+.3f}
{upstream_summary}{contradictions_section}{components_section}
## LLM rationale

{proposal.llm_rationale or "_no rationale provided_"}

## Decide

Pick one and save:

- [ ] **Accept** — apply proposed confidence ({proposal.new_confidence:.3f})
- [ ] **Reject** — keep current confidence ({proposal.old_confidence:.3f})
- [ ] **Adjust** — set confidence to: ____
- [ ] **Demote core conviction** — only valid if route=core_protected
- [ ] **Resolve contradiction** — pick: A wins / B wins / both partial / new synthesis: ____

### Notes

_(your notes here)_
"""


async def write_adjudication_entry(
    proposal: ReassessmentProposal,
    decision: RoutingDecision,
    contradictions: list[ContradictionPair],
    *,
    directory: Path | None = None,
    upstream_belief_text: str = "",
) -> Path:
    """Write a single adjudication-queue markdown file.

    Filename pattern: `{YYYY-MM-DD}-{NNN}-{kref-slug}.md`

    NNN is a per-day sequence number — directory is scanned to find the next
    available index. Atomic write via tempfile + rename.

    Args:
        proposal: The ReassessmentProposal being routed
        decision: The RoutingDecision (route + rationale)
        contradictions: Full contradiction list — filtered to this proposal
        directory: Override target directory (default: DEFAULT_ADJUDICATION_DIR)
        upstream_belief_text: Optional human-readable description of the
            upstream change that triggered the cascade

    Returns:
        Path to the written file
    """
    target_dir = directory or DEFAULT_ADJUDICATION_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = list(target_dir.glob(f"{today}-*.md"))
    next_seq = len(existing) + 1
    proposal_id = f"adj_{today}_{next_seq:03d}"

    slug = _slug(proposal.target_kref.replace("kref://", ""))
    filename = f"{today}-{next_seq:03d}-{slug}.md"
    file_path = target_dir / filename

    content = _format_adjudication_markdown(
        proposal=proposal,
        decision=decision,
        contradictions=contradictions,
        proposal_id=proposal_id,
        upstream_belief_text=upstream_belief_text,
    )

    # Atomic write — temp + rename
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(file_path)

    log.info("Adjudication entry written: %s (%s)", file_path, decision.route.value)
    return file_path


async def write_strategic_entries(
    proposals: list[ReassessmentProposal],
    decisions: list[RoutingDecision],
    contradictions: list[ContradictionPair],
    *,
    directory: Path | None = None,
    upstream_belief_text: str = "",
) -> list[Path]:
    """Convenience: write Obsidian queue entries for every proposal whose
    routing decision is STRATEGIC_REVIEW or CORE_PROTECTED. Routine proposals
    are NOT written to the queue — they're auto-applied via AGM revise()
    upstream.
    """
    written: list[Path] = []
    for proposal, decision in zip(proposals, decisions, strict=True):
        if decision.route == AdjudicationRoute.AUTO_APPLY:
            continue
        path = await write_adjudication_entry(
            proposal=proposal,
            decision=decision,
            contradictions=contradictions,
            directory=directory,
            upstream_belief_text=upstream_belief_text,
        )
        written.append(path)
    return written
