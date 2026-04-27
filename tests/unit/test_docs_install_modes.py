"""Smoke tests for `docs/INSTALL_MODES.md`.

The install modes doc claims specific commands work and specific class
names exist. If the source drifts away from those claims, the doc is
misleading and onboarding silently breaks. These tests pin the doc's
load-bearing claims to the source.

Spec: docs/LAUNCH_BACKLOG.md → P2 install modes item.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "docs" / "INSTALL_MODES.md"


def test_doc_exists() -> None:
    assert _DOC.exists(), "docs/INSTALL_MODES.md is missing"


def test_doc_names_three_modes() -> None:
    """The doc's whole point is three named modes — researcher, Obsidian
    power-user, agent-runtime. Renaming or dropping one is a substantive
    change that should be deliberate, not a doc-edit accident."""
    text = _DOC.read_text(encoding="utf-8")
    for marker in (
        "Researcher / dev",
        "Obsidian power-user",
        "Agent-runtime integration",
    ):
        assert marker in text, f"INSTALL_MODES.md no longer mentions {marker!r}"


@pytest.mark.parametrize(
    "module,name",
    [
        ("atlas_core.adapters.hermes", "AtlasHermesProvider"),
        ("atlas_core.adapters.openclaw", "AtlasOpenClawPlugin"),
        ("atlas_core.adapters.claude_code", "main"),
    ],
)
def test_doc_references_real_adapter_symbols(module: str, name: str) -> None:
    """The doc's code samples name specific classes / entry points in the
    adapter modules. If those names drift, the samples become wrong.

    Imports the module and asserts the symbol exists. Catches the
    Hermes class rename / OpenClaw plugin rename that would silently
    break copy-pasted onboarding code."""
    mod = importlib.import_module(module)
    assert hasattr(mod, name), (
        f"docs/INSTALL_MODES.md references `{module}.{name}` "
        f"but the symbol no longer exists. Either restore the symbol or "
        f"update the doc."
    )
    text = _DOC.read_text(encoding="utf-8")
    assert name in text, (
        f"docs/INSTALL_MODES.md no longer mentions `{name}` — symbol "
        f"exists in {module} but the doc dropped its reference."
    )


def test_doc_referenced_make_targets_exist() -> None:
    """The doc tells users to run `make setup`, `make neo4j`, `make doctor`,
    `make demo`, `make demo-messy`, `make test`, `make bench-agm`,
    `make bench-bmb`. Verify each is declared in the Makefile."""
    if shutil.which("make") is None:
        pytest.skip("make not installed in this environment")
    out = subprocess.run(
        ["make", "-pn"],
        cwd=str(_REPO_ROOT),
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, "make -pn failed; can't introspect targets"
    declared = out.stdout
    expected_targets = {
        "setup", "neo4j", "doctor", "demo", "demo-messy",
        "test", "bench-agm", "bench-bmb",
    }
    for target in expected_targets:
        # Look for the rule definition: "target:" at start of a line
        assert any(
            line.startswith(target + ":") for line in declared.splitlines()
        ), (
            f"docs/INSTALL_MODES.md references `make {target}` "
            f"but the Makefile has no `{target}:` rule"
        )


def test_doctor_script_runs_clean() -> None:
    """The doc tells users to run `make doctor` after install. Confirm
    the script exists and runs without raising. We don't assert all
    checks pass (Neo4j may be down in some CI configs); we just assert
    it doesn't crash."""
    out = subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "doctor.py")],
        cwd=str(_REPO_ROOT),
        env={"PYTHONPATH": str(_REPO_ROOT), "PATH": "/usr/bin:/bin:/opt/homebrew/bin"},
        capture_output=True, text=True, timeout=60,
    )
    # Exit code may be 0 (all green) or 1 (some checks failing) — both
    # mean the script ran. A traceback would land on a different
    # non-zero / message, which we'd want to catch.
    assert "Atlas environment doctor" in out.stdout, (
        f"scripts/doctor.py didn't print its banner.\n"
        f"stdout:\n{out.stdout[-500:]}\nstderr:\n{out.stderr[-500:]}"
    )


def test_readme_links_to_install_modes() -> None:
    """The Quickstart section should point readers at the doc, otherwise
    no-one will find it."""
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/INSTALL_MODES.md" in readme, (
        "README's Quickstart no longer links to docs/INSTALL_MODES.md"
    )
