"""Guard: DEPENDS_ON writers must use the property the engine reads.

RippleEngine reads exactly one edge property to attenuate propagation:

    coalesce(r.dependency_strength, 1.0)     # ripple/reassess.py

A writer that spells it `strength` does not error — the value is silently
discarded and the edge propagates at the hard-dependency default of 1.0.
That is how demo.sh's showcase cascade ran unattenuated: the demo wrote
`{strength: 0.9}` while the engine read `dependency_strength`.

These tests scan every Cypher-writing source file for DEPENDS_ON edge maps
and fail if one carries a bare `strength` key. `strength` remains the
correct property name for SUPPORTS edges (lineage/extractor.py), so the
scan is scoped to DEPENDS_ON only.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SCAN_SUFFIXES = {".py", ".sh", ".cypher"}
_SKIP_PARTS = {".git", ".venv", "node_modules", "neo4j-data", "neo4j-logs"}

_EDGE_MAP = re.compile(r"DEPENDS_ON\s*\{([^}]*)\}")
_MAP_KEY = re.compile(r"(\w+)\s*:")


def _sources() -> list[Path]:
    return [
        path
        for path in _REPO_ROOT.rglob("*")
        if path.suffix in _SCAN_SUFFIXES
        and path.is_file()
        and not _SKIP_PARTS.intersection(path.parts)
    ]


def _depends_on_edge_maps() -> list[tuple[Path, str]]:
    found = []
    for path in _sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _EDGE_MAP.finditer(text):
            found.append((path, match.group(1)))
    return found


def test_scan_actually_sees_the_known_writers() -> None:
    """If globbing breaks, the property test below would pass vacuously."""
    writer_files = {path.name for path, _ in _depends_on_edge_maps()}
    assert "demo.sh" in writer_files
    assert "test_ripple_engine.py" in writer_files


def test_depends_on_writers_use_the_property_the_engine_reads() -> None:
    offenders = [
        f"{path.relative_to(_REPO_ROOT)}: DEPENDS_ON {{{body.strip()}}}"
        for path, body in _depends_on_edge_maps()
        for key in _MAP_KEY.findall(body)
        if key == "strength"
    ]
    assert not offenders, (
        "DEPENDS_ON edges written with a bare `strength` key are silently "
        "read as dependency_strength=1.0 (no attenuation). Use "
        "`dependency_strength`:\n" + "\n".join(offenders)
    )
