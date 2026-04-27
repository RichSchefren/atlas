"""Alias dictionary — first stop for entity resolution.

Maps surface forms ('Sarah', '@sarah', 'Sarah C') to canonical kref
strings ('kref://AtlasCoffee/People/sarah_chen.person'). Backed by
a YAML file at ~/.atlas/aliases.yaml that Rich edits directly.

The YAML shape:
    aliases:
      kref://AtlasCoffee/People/sarah_chen.person:
        - "Sarah"
        - "Sarah Chen"
        - "Sarah C"
        - "@sarah"
        - "sarah.chen@example.com"
      kref://AtlasCoffee/Programs/origins.program:
        - "Origins"
        - "the origins line"
        - "p01"

Spec: PHASE-5-AND-BEYOND.md § 1.3 (Tier 1 entity resolution)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


DEFAULT_ALIAS_PATH: Path = Path.home() / ".atlas" / "aliases.yaml"
"""Standard location. Override per-test via AliasDictionary(path=...)."""


@dataclass
class AliasMatch:
    """Returned by AliasDictionary.lookup(). `confidence` is 1.0 for
    exact alias hits — the fuzzy + LLM layers are separate modules
    and produce their own confidences."""

    kref: str
    surface: str
    confidence: float = 1.0
    source: str = "alias_dictionary"


class AliasDictionary:
    """In-memory inverted index over the YAML alias file.

    Lookup is O(1) for exact matches (case-insensitive), backed by a
    pre-built reverse map. The forward map (kref → list[alias]) is
    preserved for round-trip writes when Rich adds aliases.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path or DEFAULT_ALIAS_PATH)
        self._forward: dict[str, list[str]] = {}     # kref → aliases
        self._reverse: dict[str, str] = {}           # alias_lc → kref
        self._loaded = False

    # ── Load / save ──────────────────────────────────────────────────

    def load(self) -> None:
        """Read the YAML from disk. Missing file = empty dictionary."""
        self._forward.clear()
        self._reverse.clear()
        if not self.path.exists():
            self._loaded = True
            return
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML required for alias dictionary. pip install pyyaml"
            ) from exc

        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        aliases = data.get("aliases", {})
        if not isinstance(aliases, dict):
            log.warning("aliases.yaml has no 'aliases' map; ignoring")
            self._loaded = True
            return

        for kref, surfaces in aliases.items():
            if not isinstance(surfaces, list):
                continue
            self._forward[kref] = [str(s) for s in surfaces]
            for surface in surfaces:
                self._reverse[str(surface).lower().strip()] = kref
        self._loaded = True
        log.info(
            "Loaded %d aliases for %d entities from %s",
            len(self._reverse), len(self._forward), self.path,
        )

    def save(self) -> None:
        """Write the current state back to disk. Atomic via temp + rename."""
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML required to save alias dictionary"
            ) from exc

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            yaml.safe_dump({"aliases": self._forward}, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # ── Lookup / mutation ────────────────────────────────────────────

    def lookup(self, surface: str) -> AliasMatch | None:
        """Case-insensitive exact match. Returns None if no hit."""
        if not self._loaded:
            self.load()
        if not surface:
            return None
        kref = self._reverse.get(surface.lower().strip())
        if kref is None:
            return None
        return AliasMatch(kref=kref, surface=surface)

    def add(self, kref: str, surface: str) -> None:
        """Add a new alias surface for a kref. No-op if already present.

        The new alias is persisted via save() — caller decides when to
        flush.
        """
        if not self._loaded:
            self.load()
        surfaces = self._forward.setdefault(kref, [])
        if surface not in surfaces:
            surfaces.append(surface)
            self._reverse[surface.lower().strip()] = kref

    def all_surfaces_for(self, kref: str) -> list[str]:
        """Reverse lookup — every surface form pointing at a kref."""
        if not self._loaded:
            self.load()
        return list(self._forward.get(kref, []))

    def known_krefs(self) -> list[str]:
        """List of every kref that has at least one alias."""
        if not self._loaded:
            self.load()
        return list(self._forward.keys())

    def __len__(self) -> int:
        if not self._loaded:
            self.load()
        return len(self._reverse)
