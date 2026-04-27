"""WorkingMemoryManager — the per-agent block container.

One instance per (agent_id, tenant_id) pair. Holds named blocks,
enforces token caps via the auto-summarizer, assembles them into
LLM-ready context strings.

Standard blocks Rich gets out of the box:
  Human       — who Rich is (populated from his Person kref)
  Persona     — Atlas's role description
  CurrentPriorities — auto-populated from open Commitments due <14d

Spec: PHASE-5-AND-BEYOND.md § 4.1 + § 4.2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from atlas_core.working.auto_summarizer import AutoSummarizer
from atlas_core.working.blocks import MemoryBlock

if TYPE_CHECKING:
    from neo4j import AsyncDriver


log = logging.getLogger(__name__)


@dataclass
class AssembledContext:
    """Output of WorkingMemoryManager.assemble() — a single context
    string ready to drop into an LLM prompt + a manifest of which
    blocks contributed and their token shares."""

    text: str
    block_manifest: list[dict] = field(default_factory=list)
    total_tokens: int = 0
    truncated_blocks: list[str] = field(default_factory=list)


class WorkingMemoryManager:
    """Per-agent block manager.

    Construct one per agent. The manager owns:
      - A dict of named blocks
      - An auto-summarizer for size enforcement
      - Optional Neo4j driver for Atlas-graph-driven block updates
        (e.g., refreshing CurrentPriorities from open Commitments)
    """

    def __init__(
        self,
        agent_id: str,
        *,
        driver: Optional[AsyncDriver] = None,
        summarizer: AutoSummarizer | None = None,
    ):
        self.agent_id = agent_id
        self.driver = driver
        self._blocks: dict[str, MemoryBlock] = {}
        self._summarizer = summarizer

    # ── Block registration ────────────────────────────────────────────

    def pin_block(self, block: MemoryBlock) -> None:
        """Add or replace a named block. Idempotent on name."""
        self._blocks[block.name] = block

    def unpin_block(self, name: str) -> None:
        """Remove a block. No-op if missing."""
        self._blocks.pop(name, None)

    def get_block(self, name: str) -> MemoryBlock | None:
        return self._blocks.get(name)

    def block_names(self) -> list[str]:
        return list(self._blocks.keys())

    # ── Size enforcement ─────────────────────────────────────────────

    def summarize_if_over_limit(
        self,
        *,
        human_name: str = "the user",
        persona_name: str = "Atlas",
    ) -> list[str]:
        """Auto-summarize every block that's hit the threshold.

        Returns the list of block names that got compressed. Skips
        blocks with write_policy='human' — Rich's edits are
        load-bearing, we don't paraphrase his words.
        """
        if self._summarizer is None:
            self._summarizer = AutoSummarizer()
        compressed: list[str] = []
        for name, block in list(self._blocks.items()):
            if not block.needs_summarization:
                continue
            if block.write_policy == "human":
                log.info(
                    "Block %s is over limit but write_policy=human; "
                    "leaving as-is",
                    name,
                )
                continue
            new_block = self._summarizer.summarize(
                block, human_name=human_name, persona_name=persona_name,
            )
            self._blocks[name] = new_block
            compressed.append(name)
        return compressed

    # ── Context assembly ─────────────────────────────────────────────

    def assemble(
        self,
        *,
        max_tokens: int = 4000,
        block_order: list[str] | None = None,
    ) -> AssembledContext:
        """Concatenate blocks into a single context string with a
        token budget. Block order defaults to insertion order; pass
        block_order to override (e.g., put CurrentPriorities first).

        Truncates by dropping the lowest-priority blocks (last in
        order) when over budget.
        """
        order = block_order or list(self._blocks.keys())
        sections: list[str] = []
        manifest: list[dict] = []
        truncated: list[str] = []
        total = 0
        for name in order:
            block = self._blocks.get(name)
            if block is None:
                continue
            block_text = f"### {name}\n{block.content}\n"
            block_tokens = max(1, len(block_text) // 4)
            if total + block_tokens > max_tokens:
                truncated.append(name)
                continue
            sections.append(block_text)
            manifest.append({
                "name": name,
                "tokens": block_tokens,
                "utilization": block.utilization,
            })
            total += block_tokens

        return AssembledContext(
            text="\n".join(sections),
            block_manifest=manifest,
            total_tokens=total,
            truncated_blocks=truncated,
        )

    # ── Atlas-graph-driven block refresh ─────────────────────────────

    async def refresh_current_priorities(self, days_window: int = 14) -> None:
        """Rebuild the CurrentPriorities block by querying open
        Commitments due within `days_window`.

        Skips silently when no driver is configured (testing path).
        """
        if self.driver is None:
            return
        cypher = (
            "MATCH (c:Commitment) "
            "WHERE coalesce(c.status, 'open') = 'open' "
            "  AND coalesce(c.deadline, '9999') < $cutoff "
            "RETURN c.kref AS k, "
            "       coalesce(c.description, c.text, '') AS desc, "
            "       coalesce(c.deadline, '') AS deadline, "
            "       coalesce(c.owner, '') AS owner "
            "ORDER BY coalesce(c.deadline, '') ASC LIMIT 20"
        )
        from datetime import datetime, timedelta, timezone
        cutoff = (
            datetime.now(timezone.utc) + timedelta(days=days_window)
        ).date().isoformat()
        async with self.driver.session() as s:
            result = await s.run(cypher, cutoff=cutoff)
            rows = [r async for r in result]
        if not rows:
            content = "(no open commitments due within window)"
        else:
            lines = [
                f"- {r.get('desc') or '(no description)'} — "
                f"owner: {r.get('owner') or 'unassigned'}, "
                f"due: {r.get('deadline') or 'no deadline'}"
                for r in rows
            ]
            content = "\n".join(lines)
        self.pin_block(MemoryBlock(
            name="CurrentPriorities",
            content=content,
            write_policy="auto",
        ))
