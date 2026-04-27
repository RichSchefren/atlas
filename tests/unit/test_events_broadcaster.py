"""Unit tests for the Server-Sent Events broadcaster.

Spec: PHASE-5-AND-BEYOND.md § 3.4
"""

import asyncio
import json

import pytest


class TestAtlasEvent:
    def test_to_sse_line_format(self):
        from atlas_core.api.events import AtlasEvent
        e = AtlasEvent(kind="test", payload={"x": 1})
        line = e.to_sse_line()
        assert line.startswith("data: ")
        assert line.endswith("\n\n")
        body = json.loads(line[len("data: "):].strip())
        assert body["kind"] == "test"
        assert body["payload"] == {"x": 1}
        assert "occurred_at" in body


class TestEventBroadcaster:
    async def test_emit_then_subscribe_replays_buffer(self):
        from atlas_core.api.events import AtlasEvent, EventBroadcaster
        b = EventBroadcaster(buffer_size=10)
        b.emit(AtlasEvent(kind="early", payload={}))
        q = b.subscribe()
        # Replayed event should be available immediately
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        assert event.kind == "early"

    async def test_subscribe_receives_live_events(self):
        from atlas_core.api.events import AtlasEvent, EventBroadcaster
        b = EventBroadcaster(buffer_size=10)
        q = b.subscribe()
        b.emit(AtlasEvent(kind="live", payload={"i": 1}))
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        assert event.kind == "live"
        assert event.payload["i"] == 1

    async def test_unsubscribe_stops_delivery(self):
        from atlas_core.api.events import AtlasEvent, EventBroadcaster
        b = EventBroadcaster(buffer_size=10)
        q = b.subscribe()
        b.unsubscribe(q)
        assert b.n_subscribers == 0
        b.emit(AtlasEvent(kind="dropped"))
        # Queue should remain empty
        assert q.empty()

    async def test_buffer_rolls(self):
        from atlas_core.api.events import AtlasEvent, EventBroadcaster
        b = EventBroadcaster(buffer_size=3)
        for i in range(5):
            b.emit(AtlasEvent(kind=f"event_{i}"))
        # Only the last 3 are buffered
        assert b.n_buffered == 3

    async def test_multiple_subscribers_each_receive(self):
        from atlas_core.api.events import AtlasEvent, EventBroadcaster
        b = EventBroadcaster(buffer_size=10)
        q1 = b.subscribe()
        q2 = b.subscribe()
        b.emit(AtlasEvent(kind="broadcast"))
        e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert e1.kind == "broadcast"
        assert e2.kind == "broadcast"

    async def test_emit_helpers(self):
        from atlas_core.api.events import (
            GLOBAL_BROADCASTER,
            emit_adjudication_resolved,
            emit_ledger_supersede,
            emit_ripple_cascade,
        )
        # Use a fresh subscription to isolate this test from prior state
        q = GLOBAL_BROADCASTER.subscribe()
        try:
            # Drain any pre-existing buffered events
            while not q.empty():
                q.get_nowait()
            emit_ripple_cascade(
                upstream_kref="kref://test/x", impacted_count=3,
            )
            emit_adjudication_resolved(
                proposal_id="adj_x", decision="accept", applied=True,
            )
            emit_ledger_supersede(
                target_kref="kref://test/y", ledger_event_id="ev_001",
            )
            kinds = []
            for _ in range(3):
                e = await asyncio.wait_for(q.get(), timeout=1.0)
                kinds.append(e.kind)
            assert set(kinds) == {
                "ripple_cascade",
                "adjudication_resolved",
                "ledger_supersede",
            }
        finally:
            GLOBAL_BROADCASTER.unsubscribe(q)
