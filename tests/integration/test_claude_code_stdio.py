"""Wire-level smoke test for the Claude Code MCP adapter.

Forks a subprocess running `python -m atlas_core.adapters.claude_code`
and exchanges actual JSON-RPC 2.0 frames over stdin/stdout. Asserts:

  - initialize handshake returns protocol version + serverInfo
  - tools/list returns all 10 Atlas tools
  - tools/call dispatches a real tool (ledger.verify_chain) and the
    response chain is intact
  - tools/call on an unknown tool surfaces isError=True

This is the live round-trip: a real MCP client talking to a real
Atlas server over a real pipe. No mocks, no in-process shortcuts.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


@pytest.fixture
def stdio_server():
    """Spawn the adapter as a subprocess and tear it down on exit."""
    pytest.importorskip("neo4j")

    tmp = tempfile.mkdtemp(prefix="atlas_stdio_")
    env = os.environ.copy()
    env.update({
        "ATLAS_NEO4J_URI": os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        "ATLAS_NEO4J_USER": os.environ.get("NEO4J_USER", "neo4j"),
        "ATLAS_NEO4J_PASSWORD": os.environ.get("NEO4J_PASSWORD", "atlasdev"),
        "ATLAS_QUARANTINE_DB": str(Path(tmp) / "candidates.db"),
        "ATLAS_LEDGER_DB": str(Path(tmp) / "ledger.db"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "atlas_core.adapters.claude_code"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,
    )
    # Give the subprocess a moment to import + connect to Neo4j
    time.sleep(0.6)
    if proc.poll() is not None:
        out = proc.stdout.read() if proc.stdout else ""
        err = proc.stderr.read() if proc.stderr else ""
        pytest.skip(f"adapter failed to launch: {err[:300]}")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()


def send(proc, msg: dict) -> dict | None:
    """Write a JSON-RPC frame; read one line back. Returns None for
    notification messages that have no response."""
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" not in msg:
        return None
    line = proc.stdout.readline()
    if not line:
        return None
    return json.loads(line.strip())


class TestStdioWireProtocol:
    def test_initialize_handshake(self, stdio_server):
        response = send(stdio_server, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
        })
        assert response is not None
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["result"]["protocolVersion"]
        assert response["result"]["serverInfo"]["name"] == "atlas"

    def test_tools_list_returns_eight(self, stdio_server):
        # Initialize first per MCP spec
        send(stdio_server, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
        })
        send(stdio_server, {
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        response = send(stdio_server, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        })
        assert response is not None
        tools = response["result"]["tools"]
        assert len(tools) == 10
        names = {t["name"] for t in tools}
        # Spot check the headline tools
        assert "ripple.analyze_impact" in names
        assert "ledger.verify_chain" in names
        assert "adjudication.resolve" in names

    def test_tools_call_verify_chain(self, stdio_server):
        send(stdio_server, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
        })
        response = send(stdio_server, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "ledger.verify_chain", "arguments": {}},
        })
        assert response is not None
        assert response["result"]["isError"] is False
        body = json.loads(response["result"]["content"][0]["text"])
        assert body["intact"] is True
        assert body["last_verified_sequence"] == 0

    def test_tools_call_unknown_marks_error(self, stdio_server):
        send(stdio_server, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
        })
        response = send(stdio_server, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "totally.bogus", "arguments": {}},
        })
        assert response is not None
        assert response["result"]["isError"] is True
