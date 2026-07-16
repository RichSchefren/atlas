"""Public no-Docker adapter proof must stay runnable."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_runtime_adapter_demo_passes_without_neo4j():
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    # Deliberately poison the graph endpoint: the portable proof must not use it.
    env["NEO4J_URI"] = "bolt://127.0.0.1:1"
    result = subprocess.run(
        [sys.executable, "scripts/demo_runtime_adapters.py"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Neo4j/Docker not started" in result.stdout
    assert "result: PASS" in result.stdout
