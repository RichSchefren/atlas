"""Atlas HTTP server — FastAPI on localhost:9879.

Mirrors the MCP tool surface as REST endpoints for non-MCP clients (the
web dashboard, programmatic curl access, integration tests).

Phase 2 W6 ships the minimal surface: health, tool listing, tool dispatch,
and a /verify-chain shortcut. Phase 2 W7 layers in WebSocket streaming for
the live-Ripple visualization the launch demo needs.

Spec: 05 - Atlas Architecture & Schema § 2
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from atlas_core.api.mcp_server import AtlasMCPServer


log = logging.getLogger(__name__)


DEFAULT_HTTP_PORT: int = 9879
"""Atlas HTTP port — vault-search uses 9878, Atlas takes 9879."""


# Defined at module scope (not inside create_http_app) so FastAPI can resolve
# the annotation. `from __future__ import annotations` turns annotations into
# strings, and FastAPI resolves them against module globals.
from pydantic import BaseModel as _BaseModel, Field as _Field


class DispatchBody(_BaseModel):
    params: dict[str, Any] = _Field(default_factory=dict)


def create_http_app(*, mcp_server: AtlasMCPServer) -> FastAPI:
    """Build the FastAPI app wrapping the MCP server.

    Endpoints:
      GET  /health          — liveness probe
      GET  /tools           — list registered MCP tools
      POST /tools/{name}    — dispatch a tool with JSON body params
      GET  /verify-chain    — shortcut for ledger.verify_chain
    """
    from fastapi import FastAPI, HTTPException

    app = FastAPI(
        title="Atlas API",
        version="0.1.0a1",
        description=(
            "Open-source local-first cognitive memory with AGM-compliant "
            "belief revision and automatic downstream reassessment."
        ),
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "atlas",
            "version": "0.1.0a1",
        }

    @app.get("/tools")
    async def list_tools() -> dict[str, Any]:
        return {"tools": mcp_server.list_tools()}

    @app.post("/tools/{tool_name}")
    async def dispatch_tool(tool_name: str, body: DispatchBody) -> dict[str, Any]:
        result = await mcp_server.dispatch(tool_name, body.params)
        if not result.ok:
            raise HTTPException(status_code=400, detail=result.error)
        return {"ok": True, "result": result.result}

    @app.get("/verify-chain")
    async def verify_chain() -> dict[str, Any]:
        result = await mcp_server.dispatch("ledger.verify_chain", {})
        if not result.ok:
            raise HTTPException(status_code=500, detail=result.error)
        return result.result

    @app.get("/events")
    async def events_stream():
        """Server-Sent Events stream for live Atlas activity. The
        Obsidian plugin and live-Ripple visualization both subscribe.
        Format: text/event-stream with one `data: {json}` per event."""
        from fastapi.responses import StreamingResponse

        from atlas_core.api.events import GLOBAL_BROADCASTER

        async def event_generator():
            queue = GLOBAL_BROADCASTER.subscribe()
            try:
                while True:
                    event = await queue.get()
                    yield event.to_sse_line()
            finally:
                GLOBAL_BROADCASTER.unsubscribe(queue)

        return StreamingResponse(
            event_generator(), media_type="text/event-stream",
        )

    @app.get("/events/stats")
    async def events_stats() -> dict[str, Any]:
        """Liveness check for the event broadcaster — useful for
        debugging when the Obsidian plugin shows no events."""
        from atlas_core.api.events import GLOBAL_BROADCASTER
        return {
            "subscribers": GLOBAL_BROADCASTER.n_subscribers,
            "buffered_events": GLOBAL_BROADCASTER.n_buffered,
        }

    return app
