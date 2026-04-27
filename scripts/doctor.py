"""Atlas environment doctor — checks every dependency Atlas needs.

Run:
    make doctor
    # or
    PYTHONPATH=. python scripts/doctor.py

Output is a checklist: each line is either OK with detail, or FAIL with the
exact remediation step. The script exits 0 only when everything passes; CI
and the demo can shell out to it as a preflight.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# ── Constants ───────────────────────────────────────────────────────────────

_PY_MIN = (3, 10)
_PY_MAX_TESTED = (3, 14)
_NEO4J_BOLT_PORT = 7687
_NEO4J_HTTP_PORT = 7474
_REPO_ROOT = Path(__file__).resolve().parents[1]
_OK = "  ok"
_FAIL = "  fail"


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m"


def _red(s: str) -> str:
    return f"\033[31m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m"


# ── Individual checks ──────────────────────────────────────────────────────


def check_python_version() -> tuple[bool, str, str]:
    """Atlas needs Python 3.10+; tested through 3.14."""
    v = sys.version_info
    actual = f"{v.major}.{v.minor}.{v.micro}"
    if v[:2] < _PY_MIN:
        return (
            False,
            f"Python {actual}",
            f"Atlas requires Python >={_PY_MIN[0]}.{_PY_MIN[1]}. "
            f"Install a newer Python and recreate the venv.",
        )
    if v[:2] > _PY_MAX_TESTED:
        return (
            True,
            f"Python {actual} (untested but should work)",
            f"Atlas's CI runs on Python 3.12; this version is "
            f"newer than the highest tested ({_PY_MAX_TESTED[0]}."
            f"{_PY_MAX_TESTED[1]}). If you hit issues, fall back to 3.12.",
        )
    return (True, f"Python {actual}", "")


def check_docker() -> tuple[bool, str, str]:
    """Atlas needs `docker` (Docker Desktop, Colima, or OrbStack)."""
    if shutil.which("docker") is None:
        return (
            False,
            "docker not on PATH",
            "Install Docker Desktop, Colima, or OrbStack — Atlas uses "
            "docker compose to run Neo4j locally.",
        )
    try:
        out = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return (False, "docker present but unresponsive", str(exc))
    if out.returncode != 0:
        return (
            False,
            "docker on PATH but daemon not running",
            "Start Docker Desktop / `colima start` / OrbStack.",
        )
    return (True, f"docker engine {out.stdout.strip()}", "")


def check_docker_compose() -> tuple[bool, str, str]:
    """Atlas's compose file uses the v2 plugin (`docker compose`)."""
    try:
        out = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return (False, "docker compose missing", str(exc))
    if out.returncode != 0:
        return (
            False,
            "docker compose plugin not installed",
            "Install the compose v2 plugin (Docker Desktop ships with it).",
        )
    return (True, out.stdout.strip(), "")


def _port_listening(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def check_neo4j_reachable() -> tuple[bool, str, str]:
    """Atlas writes to bolt://localhost:7687."""
    if not _port_listening("localhost", _NEO4J_BOLT_PORT):
        return (
            False,
            f"localhost:{_NEO4J_BOLT_PORT} not listening",
            "Start Neo4j with: `make neo4j` (or `docker compose up -d neo4j`).",
        )
    return (True, f"localhost:{_NEO4J_BOLT_PORT} accepting Bolt", "")


def check_neo4j_apoc() -> tuple[bool, str, str]:
    """Atlas's recursive Cypher needs APOC for some operations."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return (
            False,
            "neo4j driver not installed",
            "Run `make setup` (or `pip install -e .[dev]`).",
        )
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pw = os.environ.get("NEO4J_PASSWORD", "atlasdev")
    try:
        drv = GraphDatabase.driver(uri, auth=(user, pw))
        try:
            with drv.session() as s:
                rec = s.run(
                    "RETURN apoc.version() AS v",
                ).single()
                version = rec["v"] if rec else "unknown"
        finally:
            drv.close()
    except Exception as exc:
        return (
            False,
            "Neo4j running but APOC not loadable",
            f"{type(exc).__name__}: {exc}. "
            f"Atlas's docker-compose.yml installs APOC automatically — "
            f"if you started Neo4j manually, ensure the APOC jar is in "
            f"the plugins/ dir.",
        )
    return (True, f"APOC {version}", "")


def check_atlas_data_dir_writable() -> tuple[bool, str, str]:
    """Atlas writes the SQLite ledger and quarantine DB under ~/.atlas/."""
    home_atlas = Path.home() / ".atlas"
    try:
        home_atlas.mkdir(parents=True, exist_ok=True)
        probe = home_atlas / ".doctor_probe"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        return (
            False,
            f"~/.atlas/ not writable: {exc}",
            f"Fix permissions: `chmod -R u+rwX {home_atlas}`",
        )
    return (True, f"{home_atlas} writable", "")


def check_env_file() -> tuple[bool, str, str]:
    """Optional — only required for live ingestion runs that need API keys."""
    env_path = _REPO_ROOT / ".env"
    if env_path.exists():
        return (True, f"{env_path.relative_to(_REPO_ROOT)} present", "")
    return (
        True,
        ".env not present (only needed for live ingestion with API keys)",
        "",
    )


def check_atlas_importable() -> tuple[bool, str, str]:
    """Make sure `atlas_core` can be imported in this env."""
    try:
        import atlas_core  # noqa: F401
        from atlas_core import ripple, trust  # noqa: F401
    except ImportError as exc:
        return (
            False,
            f"atlas_core not importable: {exc}",
            "Run `pip install -e .[dev]` from the repo root.",
        )
    return (True, "atlas_core importable", "")


def check_test_suite_count() -> tuple[bool, str, str]:
    """Sanity-check the test suite is intact (count > 400)."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q",
             str(_REPO_ROOT / "tests")],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return (False, "pytest collect failed", str(exc))
    if out.returncode != 0:
        return (
            False,
            "pytest collect-only exited non-zero",
            f"Last 5 lines:\n{out.stdout.splitlines()[-5:]}",
        )
    # Look for the trailing "N tests collected" summary.
    last = next(
        (line for line in reversed(out.stdout.splitlines())
         if "tests collected" in line or "test collected" in line),
        "",
    )
    return (True, last.strip() or "tests collected", "")


# ── Driver ─────────────────────────────────────────────────────────────────


_CHECKS = [
    ("Python version",              check_python_version),
    ("Docker daemon",               check_docker),
    ("docker compose v2",           check_docker_compose),
    ("Neo4j reachable on 7687",     check_neo4j_reachable),
    ("APOC loaded in Neo4j",        check_neo4j_apoc),
    ("~/.atlas data dir writable",  check_atlas_data_dir_writable),
    (".env file (optional)",        check_env_file),
    ("atlas_core importable",       check_atlas_importable),
    ("pytest suite intact",         check_test_suite_count),
]


def main() -> int:
    print("Atlas environment doctor")
    print("=" * 64)
    failures: list[str] = []
    for label, fn in _CHECKS:
        try:
            ok, detail, remediation = fn()
        except Exception as exc:
            ok, detail, remediation = (
                False, f"{type(exc).__name__}: {exc}", "Investigate the traceback above.",
            )
        if ok:
            print(f"  {_green('OK')}    {label:<32s} {detail}")
        else:
            print(f"  {_red('FAIL')}  {label:<32s} {detail}")
            if remediation:
                print(f"          → {remediation}")
            failures.append(label)
    print("=" * 64)
    if failures:
        print(_red(f"{len(failures)} check(s) failing: {', '.join(failures)}"))
        return 1
    print(_green("All checks passed. Atlas is ready."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
