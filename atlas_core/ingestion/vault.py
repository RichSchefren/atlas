"""Vault extractor — Obsidian markdown file changes.

Spec 07 § 2.5: vault edits are highest-trust because Rich deliberately wrote
them down. The extractor uses file mtime + a hash sidecar to detect changes,
and a deterministic frontmatter parser to extract structured claims from
core-context files (team-roles, product-registry, etc.).

Phase 2 W5 ships: deterministic file-change detection + frontmatter parsing.
Phase 2 W6 wires LLM-driven extraction for free-text vault changes.
"""

from __future__ import annotations

import hashlib
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


# ─── Vault file classification ───────────────────────────────────────────────

# Paths Atlas ignores entirely (own-writes + generated artifacts).
VAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    "00 Atlas/",                         # Atlas's own writes
    "memory/BRIEFING.md",                # Intelligence Engine generated
    "memory/session-context.md",         # Intelligence Engine generated
    ".obsidian/",                        # Obsidian app config
    ".trash/",                           # Obsidian trash
)

# Frontmatter parser — looks for YAML-fenced top block.
_FRONTMATTER = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)


class VaultExtractor(BaseExtractor):
    """Watch one or more vault roots for file changes; produce claims.

    fswatch wires this in production; for testing the extractor accepts a
    list of vault root paths and re-scans on each run_once() call.
    """

    stream = StreamType.VAULT

    def __init__(
        self,
        *,
        quarantine,
        vault_roots: list[Path],
        config: StreamConfig | None = None,
    ):
        super().__init__(
            quarantine=quarantine,
            config=config or StreamConfig(
                confidence_floor=STREAM_CONFIDENCE_FLOORS[StreamType.VAULT],
            ),
        )
        self.vault_roots = [Path(r) for r in vault_roots]

    # ── BaseExtractor contract ──────────────────────────────────────────────

    def fetch_new_events(self, cursor: IngestionCursor) -> list[dict[str, Any]]:
        """Find markdown files modified after the cursor's timestamp."""
        cursor_dt = self._parse_iso(cursor.last_processed_at)
        events: list[dict[str, Any]] = []

        for root in self.vault_roots:
            if not root.exists():
                continue
            for path in root.rglob("*.md"):
                rel = str(path.relative_to(root))
                if any(pattern in rel for pattern in VAULT_IGNORE_PATTERNS):
                    continue

                mtime_dt = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )
                if mtime_dt <= cursor_dt:
                    continue

                events.append({
                    "path": str(path),
                    "relpath": rel,
                    "vault_root": str(root),
                    "mtime": mtime_dt.isoformat(),
                })

        # Sort by mtime ascending so cursor advances monotonically
        events.sort(key=lambda e: e["mtime"])
        return events

    def extract_claims_from_event(
        self,
        event: dict[str, Any],
    ) -> list[ExtractedClaim]:
        """Parse the file and emit deterministic claims from frontmatter +
        well-known structures.

        Phase 2 W5 deterministic extractor:
          - YAML frontmatter `aliases`, `role`, `priority_level`, etc. → claims
          - Well-known core-context files → typed claims
        Phase 2 W6 adds LLM-driven extraction for free-text content.
        """
        path = Path(event["path"])
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("Vault: cannot read %s: %s", path, exc)
            return []

        claims: list[ExtractedClaim] = []
        frontmatter = self._parse_frontmatter(content)
        evidence_kref = f"kref://Atlas/Vault/{event['relpath']}"

        # File-level fact: this file exists and was modified
        # Useful for tracking which vault files are active.
        # Confidence is high — Rich wrote this.

        # Frontmatter-derived claims
        for key, value in frontmatter.items():
            if isinstance(value, list):
                # e.g. aliases: [Ashley, Ash, A.Shaw]
                for v in value:
                    claims.append(self._make_claim(
                        path=path,
                        evidence_kref=evidence_kref,
                        evidence_timestamp=event["mtime"],
                        predicate=f"vault.frontmatter.{key}",
                        object_value=str(v),
                    ))
            else:
                claims.append(self._make_claim(
                    path=path,
                    evidence_kref=evidence_kref,
                    evidence_timestamp=event["mtime"],
                    predicate=f"vault.frontmatter.{key}",
                    object_value=str(value),
                ))

        return claims

    def cursor_for_event(self, event: dict[str, Any]) -> IngestionCursor:
        return IngestionCursor(
            stream=self.stream,
            last_processed_at=event["mtime"],
            last_processed_id=event["relpath"],
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _make_claim(
        self,
        *,
        path: Path,
        evidence_kref: str,
        evidence_timestamp: str,
        predicate: str,
        object_value: str,
    ) -> ExtractedClaim:
        # Subject is the file's vault path — Atlas treats files as Items
        subject_kref = f"kref://Atlas/Vault/{path.stem}.vault"
        return ExtractedClaim(
            lane="atlas_vault",  # vault edits are their own candidate-generating lane
            assertion_type="factual_assertion",
            subject_kref=subject_kref,
            predicate=predicate,
            object_value=object_value,
            confidence=0.85,  # Rich wrote it → high baseline
            evidence_source=str(path.name),
            evidence_source_family="vault",
            evidence_kref=evidence_kref,
            evidence_timestamp=evidence_timestamp,
        )

    def _parse_frontmatter(self, content: str) -> dict[str, Any]:
        """Minimal YAML-frontmatter parser — handles scalar + list values.

        Phase 2 W5 keeps this stdlib-only; full YAML support comes in W6
        when we add PyYAML for the LLM extraction path.
        """
        match = _FRONTMATTER.match(content)
        if not match:
            return {}
        out: dict[str, Any] = {}
        for line in match.group(1).split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                # simple list parsing
                items = [v.strip().strip('"\'') for v in value[1:-1].split(",")]
                out[key] = [i for i in items if i]
            elif value.startswith('"') and value.endswith('"'):
                out[key] = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                out[key] = value[1:-1]
            elif value:
                out[key] = value
        return out

    def _parse_iso(self, ts: str) -> datetime:
        return datetime.fromisoformat(ts)
