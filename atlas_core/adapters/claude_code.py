"""Claude Code MCP plugin — stdio bridge to AtlasMCPServer.

Claude Code's MCP plugin spec (modelcontextprotocol.io/specification) talks
JSON-RPC 2.0 over stdio. Atlas already has a transport-agnostic
AtlasMCPServer with 8 tools; this module is the thin stdio loop.

Install on Claude Code:
  ~/.claude/.mcp.json:
  {
    "mcpServers": {
      "atlas": {
        "command": "python",
        "args": ["-m", "atlas_core.adapters.claude_code"],
        "env": {
          "ATLAS_NEO4J_URI": "bolt://localhost:7687",
          "ATLAS_NEO4J_USER": "neo4j",
          "ATLAS_NEO4J_PASSWORD": "atlasdev",
          "ATLAS_QUARANTINE_DB": "/Users/richardschefren/.atlas/candidates.db",
          "ATLAS_LEDGER_DB": "/Users/richardschefren/.atlas/ledger.db"
        }
      }
    }
  }

Spec: 05 - Atlas Architecture & Schema § 2 (API Layer)
      MCP spec: https://modelcontextprotocol.io/specification
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2024-11-05"  # MCP spec rev that Claude Code negotiates


def _err(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


async def _build_server():
    """Read env vars, open Neo4j driver + trust stores, return AtlasMCPServer."""
    from neo4j import AsyncGraphDatabase

    from atlas_core.api import AtlasMCPServer
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    uri = os.environ.get("ATLAS_NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("ATLAS_NEO4J_USER", "neo4j")
    password = os.environ.get("ATLAS_NEO4J_PASSWORD", "atlasdev")
    quarantine_db = Path(
        os.environ.get(
            "ATLAS_QUARANTINE_DB",
            str(Path.home() / ".atlas" / "candidates.db"),
        )
    )
    ledger_db = Path(
        os.environ.get(
            "ATLAS_LEDGER_DB",
            str(Path.home() / ".atlas" / "ledger.db"),
        )
    )

    quarantine_db.parent.mkdir(parents=True, exist_ok=True)
    ledger_db.parent.mkdir(parents=True, exist_ok=True)

    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    quarantine = QuarantineStore(quarantine_db)
    ledger = HashChainedLedger(ledger_db)
    return AtlasMCPServer(
        driver=driver, quarantine=quarantine, ledger=ledger,
    ), driver


async def _handle(server, req: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch a single JSON-RPC request. Returns None for notifications."""
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "atlas", "version": "0.1.0a1"},
        })

    if method == "notifications/initialized":
        return None  # No response for notifications

    if method == "tools/list":
        return _ok(req_id, {"tools": server.list_tools()})

    if method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = await server.dispatch(tool_name, arguments)
        # MCP tools/call returns {content: [{type: "text", text: "..."}]}
        if result.ok:
            return _ok(req_id, {
                "content": [
                    {"type": "text", "text": json.dumps(result.result)}
                ],
                "isError": False,
            })
        return _ok(req_id, {
            "content": [{"type": "text", "text": result.error or ""}],
            "isError": True,
        })

    return _err(req_id, -32601, f"method not found: {method!r}")


async def _stdio_loop() -> None:
    """Read JSON-RPC requests from stdin, dispatch, write responses to stdout."""
    server, driver = await _build_server()
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    transport_protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: transport_protocol, sys.stdin)

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue
            try:
                req = json.loads(line_str)
            except json.JSONDecodeError as exc:
                sys.stdout.write(json.dumps(_err(None, -32700, str(exc))) + "\n")
                sys.stdout.flush()
                continue
            try:
                response = await _handle(server, req)
            except Exception as exc:
                log.exception("dispatch failed")
                response = _err(req.get("id"), -32603, f"{type(exc).__name__}: {exc}")
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
    finally:
        await driver.close()


def main() -> None:
    asyncio.run(_stdio_loop())


if __name__ == "__main__":
    main()
