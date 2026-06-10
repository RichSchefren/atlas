"""resolve_vault_roots — multi-vault config exposure (issue #14).

ATLAS_VAULT_ROOTS (colon-separated, PATH convention) with backward-compatible
fallback to the original single-path ATLAS_VAULT_ROOT, then to a caller
default. Missing paths are skipped, order is preserved, duplicates dropped,
tildes expanded (launchd passes env values literally — no shell expansion).
"""

from __future__ import annotations

import os
from pathlib import Path

from atlas_core.ingestion import resolve_vault_roots


def test_multiple_roots_resolved_in_order(tmp_path: Path):
    a = tmp_path / "business"
    b = tmp_path / "personal"
    a.mkdir()
    b.mkdir()
    env = {"ATLAS_VAULT_ROOTS": f"{a}{os.pathsep}{b}"}
    assert resolve_vault_roots(env) == [a, b]


def test_missing_paths_are_skipped(tmp_path: Path):
    a = tmp_path / "exists"
    a.mkdir()
    gone = tmp_path / "does-not-exist"
    env = {"ATLAS_VAULT_ROOTS": f"{gone}{os.pathsep}{a}"}
    assert resolve_vault_roots(env) == [a]


def test_backward_compatible_single_root(tmp_path: Path):
    a = tmp_path / "vault"
    a.mkdir()
    env = {"ATLAS_VAULT_ROOT": str(a)}
    assert resolve_vault_roots(env) == [a]


def test_roots_takes_precedence_over_root(tmp_path: Path):
    plural = tmp_path / "plural"
    singular = tmp_path / "singular"
    plural.mkdir()
    singular.mkdir()
    env = {
        "ATLAS_VAULT_ROOTS": str(plural),
        "ATLAS_VAULT_ROOT": str(singular),
    }
    assert resolve_vault_roots(env) == [plural]


def test_default_used_when_env_unset(tmp_path: Path):
    default = tmp_path / "watch-vault"
    default.mkdir()
    assert resolve_vault_roots({}, default=default) == [default]


def test_empty_when_nothing_exists(tmp_path: Path):
    assert resolve_vault_roots({}, default=tmp_path / "missing") == []
    assert resolve_vault_roots({}) == []


def test_whitespace_and_empty_segments_ignored(tmp_path: Path):
    a = tmp_path / "a"
    a.mkdir()
    env = {"ATLAS_VAULT_ROOTS": f"  {a}  {os.pathsep}{os.pathsep}   "}
    assert resolve_vault_roots(env) == [a]


def test_duplicates_dropped_preserving_order(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    env = {"ATLAS_VAULT_ROOTS": os.pathsep.join([str(a), str(b), str(a)])}
    assert resolve_vault_roots(env) == [a, b]


def test_tilde_expansion(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    (home / "vault").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    env = {"ATLAS_VAULT_ROOTS": "~/vault"}
    assert resolve_vault_roots(env) == [home / "vault"]
