"""The source distribution is an explicit allowlist.

A runtime install from source only needs the importable package plus the
metadata files that build, install, and license the project. The repo tree
also carries docs, site media, benchmarks, examples, CI config, and dev/ops
tooling — none of which belong in a distribution. Rather than maintain an
ever-growing deny list, ``pyproject.toml`` pins ``[tool.hatch.build.targets.sdist]``
to an allowlist so everything else is excluded by construction.

This test builds the sdist and asserts its members are exactly that allowlist,
so a future directory added at the repo root cannot silently start shipping.

Spec: pyproject.toml § [tool.hatch.build.targets.sdist]
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

_HAS_BUILD = importlib.util.find_spec("build") is not None

# Root-level metadata files a runtime source install legitimately carries,
# plus the backend-generated / force-included sdist artifacts (not repo
# content): PKG-INFO is written by the build backend, and hatchling always
# ships the VCS ignore file in an sdist.
ALLOWED_ROOT_FILES = frozenset(
    {
        "README.md",
        "LICENSE",
        "NOTICE",
        "pyproject.toml",
        "PKG-INFO",
        ".gitignore",
    }
)

# The only directory a distribution needs: the importable package itself.
ALLOWED_TOP_DIRS = frozenset({"atlas_core"})

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _build_sdist(outdir: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(outdir)],
        cwd=str(PROJECT_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    tarballs = sorted(outdir.glob("*.tar.gz"))
    assert tarballs, "build produced no sdist tarball"
    return tarballs[-1]


def _extraneous_members(tarball: Path) -> list[str]:
    offenders: list[str] = []
    with tarfile.open(tarball, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            # Strip the "<name>-<version>/" prefix sdists wrap everything in.
            parts = Path(member.name).parts
            rel = Path(*parts[1:]) if len(parts) > 1 else Path(member.name)
            if rel.parts[0] in ALLOWED_TOP_DIRS:
                continue
            if len(rel.parts) == 1 and rel.parts[0] in ALLOWED_ROOT_FILES:
                continue
            offenders.append(str(rel))
    return sorted(offenders)


@pytest.mark.skipif(not _HAS_BUILD, reason="the `build` frontend is not installed")
def test_sdist_contains_only_the_allowlist() -> None:
    with tempfile.TemporaryDirectory() as td:
        tarball = _build_sdist(Path(td))
        offenders = _extraneous_members(tarball)
    assert offenders == [], (
        f"sdist ships {len(offenders)} file(s) outside the allowlist "
        f"(first few: {offenders[:5]}); tighten "
        "[tool.hatch.build.targets.sdist] in pyproject.toml"
    )


@pytest.mark.skipif(not _HAS_BUILD, reason="the `build` frontend is not installed")
def test_sdist_still_ships_the_package() -> None:
    """The allowlist must not starve the actual install."""
    with tempfile.TemporaryDirectory() as td:
        tarball = _build_sdist(Path(td))
        with tarfile.open(tarball, "r:gz") as tf:
            members = [m.name for m in tf.getmembers() if m.isfile()]
    package_files = [m for m in members if "/atlas_core/" in f"/{m}"]
    py_modules = [m for m in package_files if m.endswith(".py")]
    assert len(py_modules) > 50, "sdist is missing package source modules"
    # Package data (non-.py resources under the package) must survive too.
    data_files = [m for m in package_files if not m.endswith(".py")]
    assert data_files, "sdist dropped the package's non-.py data files"
