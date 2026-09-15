"""Every HTTP request is logged with a UTC timestamp and its latency.

uvicorn's default access line has neither, which made the 2026-09-14
event-loop stalls unattributable after the fact.
"""

from __future__ import annotations

import logging
import re

import pytest

from tests.unit.test_http_server_security import _auth_headers, _FakeMCPServer

TS_PATTERN = re.compile(r"ts=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")


@pytest.fixture
def http_app():
    from atlas_core.api import create_http_app

    return create_http_app(
        mcp_server=_FakeMCPServer(),
        bearer_token="test-token-that-is-long-enough-for-local-auth",
        allowed_origins=["app://obsidian.md"],
    )


@pytest.fixture
async def client(http_app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=http_app), base_url="http://test"
    ) as value:
        yield value


@pytest.fixture
def access_records(caplog, http_app):
    from atlas_core.api.access_log import ACCESS_LOGGER_NAME

    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER_NAME):
            yield lambda: [r for r in caplog.records if r.name == ACCESS_LOGGER_NAME]
    finally:
        logger.removeHandler(caplog.handler)


async def test_access_line_carries_timestamp_status_and_latency(client, access_records):
    response = await client.post(
        "/tools/memory.list", json={"params": {"limit": 5}}, headers=_auth_headers(),
    )
    assert response.status_code == 200

    records = access_records()
    assert len(records) == 1
    record = records[0]
    message = record.getMessage()
    assert message.startswith("ACCESS ")
    assert TS_PATTERN.search(message), message
    assert "method=POST" in message
    assert "path=/tools/memory.list" in message
    assert "status=200" in message
    assert re.search(r"duration_ms=\d+\.\d", message), message
    assert record.http_method == "POST"
    assert record.http_path == "/tools/memory.list"
    assert record.status_code == 200
    assert isinstance(record.duration_ms, float) and record.duration_ms >= 0.0


async def test_rejected_requests_are_logged_with_their_status(client, access_records):
    assert (await client.get("/tools")).status_code == 401
    assert (await client.get("/health")).status_code == 200

    statuses = [(r.http_method, r.http_path, r.status_code) for r in access_records()]
    assert statuses == [("GET", "/tools", 401), ("GET", "/health", 200)]


def test_access_logger_writes_to_stdout_once_without_propagating():
    from atlas_core.api.access_log import ACCESS_LOGGER_NAME, ensure_access_log_handler

    logger = ensure_access_log_handler()
    ensure_access_log_handler()

    assert logger.name == ACCESS_LOGGER_NAME
    assert logger.propagate is False
    own = [h for h in logger.handlers if getattr(h, "atlas_access_handler", False)]
    assert len(own) == 1
    assert own[0].formatter._fmt == "%(message)s"
