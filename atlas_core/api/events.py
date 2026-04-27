"""Server-Sent Events (SSE) stream for live Atlas activity.

Mounts at /events on the FastAPI app. Pushes one JSON line per
event: ripple cascades, adjudication state changes, ledger
SUPERSEDE events. The Obsidian plugin and the live-Ripple
visualization both subscribe to this.

Spec: PHASE-5-AND-BEYOND.md § 3.4
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


log = logging.getLogger(__name__)


DEFAULT_BUFFER_SIZE: int = 200
"""Replay-on-connect buffer. New subscribers get the last N events
so they don't have to wait for the next live event to confirm the
stream is working."""


@dataclass
class AtlasEvent:
    """One stream event."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def to_sse_line(self) -> str:
        """Format as one SSE `data:` frame followed by a blank line."""
        body = json.dumps(asdict(self), separators=(",", ":"))
        return f"data: {body}\n\n"


class EventBroadcaster:
    """Process-local pubsub for Atlas events.

    Producers call .emit() (Ripple, adjudication, ledger).
    Subscribers call .subscribe() and get an asyncio.Queue.
    A rolling buffer holds the last DEFAULT_BUFFER_SIZE events
    so reconnecting clients see recent history.
    """

    def __init__(self, *, buffer_size: int = DEFAULT_BUFFER_SIZE):
        self._buffer: deque[AtlasEvent] = deque(maxlen=buffer_size)
        self._subscribers: list[asyncio.Queue[AtlasEvent]] = []

    def emit(self, event: AtlasEvent) -> None:
        """Producer entry point. Buffers + fans out to every
        subscriber. Failed subscriber sends are logged + skipped
        so a slow consumer can't block producers."""
        self._buffer.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.debug("Subscriber queue full; dropping event")

    def subscribe(self) -> asyncio.Queue[AtlasEvent]:
        """Returns a Queue. Caller is responsible for unsubscribing
        when the connection closes (call .unsubscribe(queue))."""
        q: asyncio.Queue[AtlasEvent] = asyncio.Queue(maxsize=200)
        # Replay the buffer so the new subscriber sees recent state
        for event in self._buffer:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                break
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    @property
    def n_subscribers(self) -> int:
        return len(self._subscribers)

    @property
    def n_buffered(self) -> int:
        return len(self._buffer)


# Process-local singleton — every Atlas process gets one.
GLOBAL_BROADCASTER = EventBroadcaster()


def emit_ripple_cascade(*, upstream_kref: str, impacted_count: int) -> None:
    GLOBAL_BROADCASTER.emit(AtlasEvent(
        kind="ripple_cascade",
        payload={
            "upstream_kref": upstream_kref,
            "impacted_count": impacted_count,
        },
    ))


def emit_adjudication_resolved(
    *, proposal_id: str, decision: str, applied: bool,
) -> None:
    GLOBAL_BROADCASTER.emit(AtlasEvent(
        kind="adjudication_resolved",
        payload={
            "proposal_id": proposal_id,
            "decision": decision,
            "applied": applied,
        },
    ))


def emit_ledger_supersede(
    *, target_kref: str, ledger_event_id: str,
) -> None:
    GLOBAL_BROADCASTER.emit(AtlasEvent(
        kind="ledger_supersede",
        payload={
            "target_kref": target_kref,
            "ledger_event_id": ledger_event_id,
        },
    ))
