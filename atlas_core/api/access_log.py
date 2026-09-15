"""Structured access log for the Atlas HTTP surface.

uvicorn's built-in access line (``client - "METHOD /path HTTP/1.1" 200 OK``)
has no timestamp and no latency, so a stalled request cannot be attributed
after the fact. This pure-ASGI middleware writes one line per request to the
``atlas.access`` logger on stdout (the same stream uvicorn uses)::

    ACCESS ts=2026-09-14T21:55:01.123Z client=127.0.0.1:65509 method=POST \
        path=/tools/memory.list status=200 duration_ms=23.4

``ts`` is the moment the response finished (UTC, millisecond precision);
``duration_ms`` is wall-clock from the first ASGI call to the last byte
sent, so ``ts - duration_ms`` is when the request started. The launchd
plist passes ``--no-access-log`` to uvicorn so each request appears once.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any

ACCESS_LOGGER_NAME = "atlas.access"

log = logging.getLogger(ACCESS_LOGGER_NAME)


def ensure_access_log_handler() -> logging.Logger:
    """Attach exactly one stdout handler to the access logger.

    Idempotent, so repeated ``create_http_app`` calls (tests build many apps)
    never duplicate lines. The logger does not propagate: uvicorn configures
    no root handler, and a root handler added later (``basicConfig``) must not
    mirror access lines onto stderr.
    """
    if not any(getattr(h, "atlas_access_handler", False) for h in log.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.atlas_access_handler = True  # type: ignore[attr-defined]
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log


def _utc_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y-%m-%dT%H:%M:%S}.{now.microsecond // 1000:03d}Z"


class AccessLogMiddleware:
    """Log ``method path status duration_ms`` for every HTTP request."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code: int | None = None

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            # Starlette's ServerErrorMiddleware (outside us) answers 500.
            self._emit(scope, 500 if status_code is None else status_code, started)
            raise
        self._emit(scope, status_code, started)

    @staticmethod
    def _emit(scope: dict[str, Any], status_code: int | None, started: float) -> None:
        duration_ms = (time.perf_counter() - started) * 1000.0
        client = scope.get("client")
        client_addr = f"{client[0]}:{client[1]}" if client else "-"
        method = scope.get("method", "-")
        path = scope.get("path", "") or "/"
        query = scope.get("query_string", b"")
        if query:
            path = f"{path}?{query.decode('latin-1')}"
        log.info(
            "ACCESS ts=%s client=%s method=%s path=%s status=%s duration_ms=%.1f",
            _utc_timestamp(),
            client_addr,
            method,
            path,
            "-" if status_code is None else status_code,
            duration_ms,
            extra={
                "client_addr": client_addr,
                "http_method": method,
                "http_path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            },
        )
