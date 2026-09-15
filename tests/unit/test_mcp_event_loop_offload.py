"""The SQLite-backed MCP tools must not block uvicorn's event loop.

Background (2026-09-14): ``memory.list`` / ``memory.search`` / ``memory.get``
/ ``ledger.verify_chain`` ran synchronous SQLite inside ``async def``
handlers, so one stalled call delayed every other request on the single
uvicorn loop and the MCC atlas-owner sidecar timed out 541 times on a call
that takes 20-40 ms when the loop is free.

These tests drive the real ``AtlasMCPServer.dispatch`` path with stores
whose calls block for a fixed wall-clock interval and prove that a ticker
coroutine keeps running meanwhile. They also pin the results to the
synchronous store output so the offload changes timing only.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from tests.unit.test_quarantine import make_claim

BLOCK_SECONDS = 0.25
TICK_SECONDS = 0.01
# A free loop ticks ~25 times during BLOCK_SECONDS; a blocked loop ticks 0-1.
MIN_TICKS_WHEN_RESPONSIVE = 5


class _BlockingQuarantine:
    """Store double whose reads block the calling thread like a busy SQLite."""

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []
        self.threads: list[str] = []
        self.row = {
            "candidate_id": "cand-1",
            "object_value": "text",
            "status": "pending",
            "lane": "atlas_sessions",
            "subject_kref": "kref://test/People/a.person",
            "predicate": "role",
            "confidence": 0.8,
            "trust_score": 0.5,
            "retrieval_score": 0.9,
            "created_at": "2026-09-14T00:00:00+00:00",
            "updated_at": "2026-09-14T00:00:00+00:00",
        }

    def _block(self, name, args, kwargs):
        self.calls.append((name, args, kwargs))
        self.threads.append(threading.current_thread().name)
        time.sleep(BLOCK_SECONDS)

    def list_memories(self, *args, **kwargs):
        self._block("list_memories", args, kwargs)
        return [self.row]

    def search_memories(self, *args, **kwargs):
        self._block("search_memories", args, kwargs)
        return [self.row]

    def get_candidate(self, *args, **kwargs):
        self._block("get_candidate", args, kwargs)
        return self.row


class _BlockingLedger:
    def __init__(self):
        self.calls = 0

    def verify_chain(self):
        from atlas_core.trust.ledger import ChainVerificationResult

        self.calls += 1
        time.sleep(BLOCK_SECONDS)
        return ChainVerificationResult(
            intact=True, last_verified_sequence=3, last_verified_event_id="e3",
        )


@pytest.fixture
def blocking_server():
    from atlas_core.api import AtlasMCPServer

    return AtlasMCPServer(
        driver=None, quarantine=_BlockingQuarantine(), ledger=_BlockingLedger(),
    )


async def _dispatch_with_ticker(server, tool_name, params):
    ticks = 0
    stop = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(TICK_SECONDS)

    ticker_task = asyncio.create_task(ticker())
    await asyncio.sleep(0)  # let the ticker start before the dispatch
    try:
        result = await server.dispatch(tool_name, params)
    finally:
        stop.set()
        await ticker_task
    return result, ticks


@pytest.mark.parametrize(
    ("tool_name", "params", "store_attr", "store_call"),
    [
        ("memory.list", {"limit": 5}, "quarantine", "list_memories"),
        ("memory.search", {"query": "text", "limit": 5}, "quarantine", "search_memories"),
        ("memory.get", {"memory_id": "cand-1"}, "quarantine", "get_candidate"),
        ("ledger.verify_chain", {}, "ledger", "verify_chain"),
    ],
)
async def test_blocking_store_call_leaves_event_loop_responsive(
    blocking_server, tool_name, params, store_attr, store_call,
):
    result, ticks = await _dispatch_with_ticker(blocking_server, tool_name, params)

    assert result.ok, result.error
    assert ticks >= MIN_TICKS_WHEN_RESPONSIVE, (
        f"{tool_name} blocked the event loop: only {ticks} ticks during a "
        f"{BLOCK_SECONDS}s store call"
    )
    store = getattr(blocking_server, store_attr)
    if store_attr == "ledger":
        assert store.calls == 1
    else:
        assert [c[0] for c in store.calls] == [store_call]


async def test_store_calls_are_serialized_on_one_dedicated_thread(blocking_server):
    """Parallel SQLite reads are GIL-bound and measured slower than serial."""
    started = time.perf_counter()
    (first, ticks), (second, _) = await asyncio.gather(
        _dispatch_with_ticker(blocking_server, "memory.list", {"limit": 5}),
        _dispatch_with_ticker(blocking_server, "memory.search", {"query": "text"}),
    )
    elapsed = time.perf_counter() - started

    assert first.ok and second.ok
    assert elapsed >= 2 * BLOCK_SECONDS, "store calls ran in parallel"
    assert ticks >= MIN_TICKS_WHEN_RESPONSIVE
    threads = blocking_server.quarantine.threads
    assert len(threads) == 2
    assert len(set(threads)) == 1
    assert threads[0].startswith("atlas-sqlite")
    assert threads[0] != threading.main_thread().name


async def test_store_arguments_are_forwarded_unchanged(blocking_server):
    await blocking_server.dispatch("memory.list", {"lane": "atlas_sessions", "limit": 7})
    await blocking_server.dispatch("memory.search", {"query": "q", "limit": 3, "lane": "x"})
    await blocking_server.dispatch("memory.get", {"memory_id": "cand-1"})

    calls = blocking_server.quarantine.calls
    assert calls[0] == ("list_memories", (), {"lane": "atlas_sessions", "limit": 7})
    assert calls[1] == ("search_memories", ("q",), {"limit": 3, "lane": "x"})
    assert calls[2] == ("get_candidate", ("cand-1",), {})


async def test_missing_required_param_is_still_reported_as_invalid_params(blocking_server):
    result = await blocking_server.dispatch("memory.get", {})

    assert not result.ok
    assert result.error.startswith("invalid params for memory.get")
    assert blocking_server.quarantine.calls == []


@pytest.fixture
def real_server(tmp_path: Path):
    from atlas_core.api import AtlasMCPServer
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    quarantine = QuarantineStore(tmp_path / "candidates.db")
    ledger = HashChainedLedger(tmp_path / "ledger.db")
    quarantine.upsert_candidate(make_claim(
        predicate="schedule.launch",
        object_value="Launch webinar happens Thursday morning",
    ))
    quarantine.upsert_candidate(make_claim(
        lane="atlas_meeting",
        predicate="schedule.review",
        object_value="Webinar review happens Friday",
    ))
    denied = quarantine.upsert_candidate(make_claim(
        predicate="schedule.cancelled",
        object_value="Cancelled launch webinar",
    ))
    quarantine.deny_candidate(denied.candidate_id, reason="test", decision_id="test")
    return AtlasMCPServer(driver=None, quarantine=quarantine, ledger=ledger)


async def test_results_match_the_synchronous_store(real_server):
    from atlas_core.api import AtlasMCPServer

    store = real_server.quarantine

    listed = await real_server.dispatch("memory.list", {"limit": 10})
    assert listed.ok
    expected_rows = [AtlasMCPServer._memory_row(r) for r in store.list_memories(limit=10)]
    assert listed.result == {"memories": expected_rows, "count": 2, "backend": "sqlite"}

    lane_only = await real_server.dispatch("memory.list", {"lane": "atlas_meeting", "limit": 10})
    assert [m["lane"] for m in lane_only.result["memories"]] == ["atlas_meeting"]

    searched = await real_server.dispatch("memory.search", {"query": "launch webinar Thursday", "limit": 5})
    assert searched.ok
    expected_hits = [
        AtlasMCPServer._memory_row(r)
        for r in store.search_memories("launch webinar Thursday", limit=5)
    ]
    assert searched.result == {"memories": expected_hits, "count": len(expected_hits), "backend": "sqlite"}
    assert len(expected_hits) == 2  # denied row hidden

    first_id = expected_rows[0]["memory_id"]
    fetched = await real_server.dispatch("memory.get", {"memory_id": first_id})
    assert fetched.result == {"memory": AtlasMCPServer._memory_row(store.get_candidate(first_id))}
    assert (await real_server.dispatch("memory.get", {"memory_id": "missing"})).result == {"memory": None}

    verified = await real_server.dispatch("ledger.verify_chain", {})
    assert verified.ok
    assert set(verified.result) == {
        "intact", "last_verified_sequence", "last_verified_event_id",
        "broken_at_sequence", "breakage_reason",
    }
    assert verified.result["intact"] is True


async def test_concurrent_reads_against_one_sqlite_file_all_succeed(real_server):
    results = await asyncio.gather(*[
        real_server.dispatch("memory.list", {"limit": 10}) for _ in range(16)
    ])

    assert all(r.ok for r in results), [r.error for r in results if not r.ok]
    assert len({str(r.result) for r in results}) == 1
