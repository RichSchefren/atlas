"""Regression test for the messy-input demo (`scripts/demo_messy.py`).

Asserts that the full pipeline — deterministic regex extraction →
quarantine → ledger → Ripple → SHA-256 chain verify — runs end-to-end on
the inputs in `examples/messy_demo/` without raising, and exits 0. The
internal correctness of each stage is covered by its own unit tests; this
test exists so the demo *binary* doesn't silently rot.

If the script's exit code drifts to non-zero, or its stdout no longer
contains the LOOP CLOSED marker, CI fails. That's the point: the demo
is the front door, and a broken front door is worse than no front door.

Spec: docs/LAUNCH_BACKLOG.md → P0 "messy real-world demo".
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "demo_messy.py"


def test_demo_messy_runs_end_to_end() -> None:
    """Full pipeline on the markdown + transcript inputs ends in chain-intact."""
    out = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, (
        f"demo_messy.py exited non-zero ({out.returncode}).\n"
        f"stdout:\n{out.stdout[-2000:]}\n"
        f"stderr:\n{out.stderr[-2000:]}"
    )
    assert "LOOP CLOSED." in out.stdout, (
        f"demo_messy.py finished without printing the LOOP CLOSED marker.\n"
        f"stdout (last 1000 chars):\n{out.stdout[-1000:]}"
    )
    assert "chain intact at sequence" in out.stdout, (
        f"ledger chain verification didn't print intact line.\n"
        f"stdout (last 1000 chars):\n{out.stdout[-1000:]}"
    )
    # Real-shape extraction sanity: both prices made it through
    assert "$2,995" in out.stdout
    assert "$3,495" in out.stdout
    # Ripple actually fired on the planted downstream
    assert "reassessment proposal(s) computed" in out.stdout
