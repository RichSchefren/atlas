"""Federated adjudication — when one tenant's assertion contradicts
another's ledger, the adjudication entry routes to BOTH queues.

Use case: Rich and Ben both observe a meeting; their independent
extractions feed one shared adjudication entry. Resolution requires
both to agree, OR one to explicitly override with audit log.

Spec: PHASE-5-AND-BEYOND.md § 5.3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class FederatedAdjudication:
    """One adjudication entry that lives in two tenants' queues."""

    proposal_id: str
    asserting_tenant: str
    contradicting_tenant: str
    target_kref: str
    asserted_value: str
    contradicting_value: str
    severity: str = "medium"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def to_markdown(self, tenant_perspective: str) -> str:
        """Format for the named tenant's queue. The framing changes
        depending on which side you're reading from."""
        if tenant_perspective == self.asserting_tenant:
            opening = (
                f"# Federated Adjudication — {self.contradicting_tenant} disagrees\n"
            )
            you_said = self.asserted_value
            they_said = self.contradicting_value
            other = self.contradicting_tenant
        else:
            opening = (
                f"# Federated Adjudication — your prior conflicts with {self.asserting_tenant}\n"
            )
            you_said = self.contradicting_value
            they_said = self.asserted_value
            other = self.asserting_tenant
        return (
            f"---\n"
            f"type: federated_adjudication\n"
            f"proposal_id: {self.proposal_id}\n"
            f"target_kref: {self.target_kref}\n"
            f"severity: {self.severity}\n"
            f"asserting_tenant: {self.asserting_tenant}\n"
            f"contradicting_tenant: {self.contradicting_tenant}\n"
            f"created: {self.created_at}\n"
            f"---\n\n"
            f"{opening}\n"
            f"## Target\n`{self.target_kref}`\n\n"
            f"## What you have\n> {you_said}\n\n"
            f"## What {other} has\n> {they_said}\n\n"
            f"## Decide\n\n"
            f"- [ ] **Accept their value** — overwrite your ledger\n"
            f"- [ ] **Defend yours** — push your value back to {other}\n"
            f"- [ ] **Synthesize** — propose a new value: ____\n"
            f"- [ ] **Defer** — wait for the other tenant to weigh in first\n"
        )


def route_to_tenants(
    adjudication: FederatedAdjudication,
    *,
    asserting_dir: Path,
    contradicting_dir: Path,
) -> tuple[Path, Path]:
    """Write the same adjudication into both tenants' queues with
    perspective-appropriate framing. Returns (asserting_path,
    contradicting_path)."""
    asserting_dir.mkdir(parents=True, exist_ok=True)
    contradicting_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"{today}-fed-{adjudication.proposal_id}.md"

    asserting_path = asserting_dir / filename
    contradicting_path = contradicting_dir / filename

    asserting_path.write_text(
        adjudication.to_markdown(adjudication.asserting_tenant),
        encoding="utf-8",
    )
    contradicting_path.write_text(
        adjudication.to_markdown(adjudication.contradicting_tenant),
        encoding="utf-8",
    )
    return asserting_path, contradicting_path
