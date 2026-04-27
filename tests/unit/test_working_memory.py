"""Unit tests for the Tier 4 working-memory block manager.

Spec: PHASE-5-AND-BEYOND.md § 4
"""

from unittest.mock import MagicMock

import pytest


class TestMemoryBlock:
    def test_estimated_tokens_grows_with_content(self):
        from atlas_core.working import MemoryBlock
        b1 = MemoryBlock(name="x", content="hello")
        b2 = MemoryBlock(name="x", content="hello world hello world hello world")
        assert b2.estimated_tokens > b1.estimated_tokens

    def test_utilization_and_threshold(self):
        from atlas_core.working import MemoryBlock
        # max_tokens=4 → "X" * 16 chars ≈ 4 tokens → 1.0 utilization
        b = MemoryBlock(name="x", content="X" * 16, max_tokens=4)
        assert b.utilization >= 1.0
        assert b.needs_summarization is True

    def test_low_utilization_does_not_need_summarization(self):
        from atlas_core.working import MemoryBlock
        b = MemoryBlock(name="x", content="hi", max_tokens=1500)
        assert b.utilization < 0.1
        assert b.needs_summarization is False

    def test_update_content_refreshes_timestamp(self):
        from atlas_core.working import MemoryBlock
        b = MemoryBlock(name="x", content="a")
        original_ts = b.last_updated
        # ensure the timestamp changes by sleeping a tick
        import time
        time.sleep(0.01)
        b.update_content("a longer content string")
        assert b.last_updated >= original_ts


class TestWorkingMemoryManager:
    def test_pin_unpin_round_trip(self):
        from atlas_core.working import MemoryBlock, WorkingMemoryManager
        m = WorkingMemoryManager(agent_id="agent_1")
        m.pin_block(MemoryBlock(name="A", content="alpha"))
        m.pin_block(MemoryBlock(name="B", content="beta"))
        assert sorted(m.block_names()) == ["A", "B"]
        assert m.get_block("A").content == "alpha"
        m.unpin_block("A")
        assert m.block_names() == ["B"]
        m.unpin_block("nonexistent")  # no-op

    def test_pin_replaces_same_name(self):
        from atlas_core.working import MemoryBlock, WorkingMemoryManager
        m = WorkingMemoryManager(agent_id="agent_1")
        m.pin_block(MemoryBlock(name="A", content="v1"))
        m.pin_block(MemoryBlock(name="A", content="v2"))
        assert m.get_block("A").content == "v2"
        assert m.block_names() == ["A"]

    def test_assemble_concatenates_blocks(self):
        from atlas_core.working import MemoryBlock, WorkingMemoryManager
        m = WorkingMemoryManager(agent_id="agent_1")
        m.pin_block(MemoryBlock(name="A", content="alpha"))
        m.pin_block(MemoryBlock(name="B", content="beta"))
        ctx = m.assemble(max_tokens=500)
        assert "### A" in ctx.text
        assert "### B" in ctx.text
        assert "alpha" in ctx.text
        assert "beta" in ctx.text
        assert ctx.total_tokens > 0
        assert ctx.truncated_blocks == []
        assert len(ctx.block_manifest) == 2

    def test_assemble_respects_max_tokens(self):
        from atlas_core.working import MemoryBlock, WorkingMemoryManager
        m = WorkingMemoryManager(agent_id="agent_1")
        m.pin_block(MemoryBlock(name="A", content="x" * 800))
        m.pin_block(MemoryBlock(name="B", content="y" * 800))
        # Tiny budget — should drop the second block
        ctx = m.assemble(max_tokens=250)
        assert "B" in ctx.truncated_blocks
        assert "A" not in ctx.truncated_blocks

    def test_assemble_uses_block_order_override(self):
        from atlas_core.working import MemoryBlock, WorkingMemoryManager
        m = WorkingMemoryManager(agent_id="agent_1")
        m.pin_block(MemoryBlock(name="A", content="alpha"))
        m.pin_block(MemoryBlock(name="B", content="beta"))
        ctx = m.assemble(max_tokens=500, block_order=["B", "A"])
        assert ctx.text.index("beta") < ctx.text.index("alpha")

    def test_summarize_skips_human_policy(self):
        from atlas_core.working import MemoryBlock, WorkingMemoryManager
        m = WorkingMemoryManager(agent_id="agent_1")
        # Over-limit but write_policy='human' — should NOT be summarized
        m.pin_block(MemoryBlock(
            name="Human",
            content="X" * 16,
            max_tokens=4,
            write_policy="human",
        ))
        compressed = m.summarize_if_over_limit()
        assert "Human" not in compressed

    def test_summarize_invokes_summarizer_for_auto_blocks(self):
        from atlas_core.working import MemoryBlock, WorkingMemoryManager
        m = WorkingMemoryManager(agent_id="agent_1")
        # Inject a fake summarizer that just truncates
        fake = MagicMock()
        fake.summarize.side_effect = lambda b, **kw: MemoryBlock(
            name=b.name,
            content=b.content[:5],
            max_tokens=b.max_tokens,
            write_policy=b.write_policy,
        )
        m._summarizer = fake
        m.pin_block(MemoryBlock(
            name="Notes",
            content="X" * 100,
            max_tokens=10,
            write_policy="auto",
        ))
        compressed = m.summarize_if_over_limit()
        assert "Notes" in compressed
        assert m.get_block("Notes").content == "XXXXX"


class TestStandardBlocks:
    def test_human_block_default_content(self):
        from atlas_core.working import build_human_block
        b = build_human_block()
        assert b.name == "Human"
        assert b.write_policy == "human"
        # Default content is now a neutral placeholder (sanitized
        # 2026-04-27 audit pass — no personal info baked into defaults).
        assert "unconfigured" in b.content
        assert "Atlas" in b.content

    def test_human_block_custom_content(self):
        from atlas_core.working import build_human_block
        b = build_human_block("I am a test user")
        assert b.content == "I am a test user"

    def test_persona_block_default(self):
        from atlas_core.working import build_persona_block
        b = build_persona_block()
        assert b.name == "Persona"
        assert b.write_policy == "auto"
        assert "Atlas" in b.content

    def test_standard_block_set_returns_three(self):
        from atlas_core.working import standard_block_set
        blocks = standard_block_set()
        assert len(blocks) == 3
        names = {b.name for b in blocks}
        assert names == {"Human", "Persona", "CurrentPriorities"}
