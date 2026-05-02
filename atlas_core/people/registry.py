"""People registry — load people.yaml, resolve aliases, classify by tier."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


_PACKAGED_REGISTRY = Path(__file__).parent / "people.yaml"
_USER_OVERRIDE = Path(
    os.path.expanduser(
        os.environ.get("ATLAS_PEOPLE_REGISTRY", "~/.atlas/config/people.yaml")
    )
)


# ─── Types ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PersonInfo:
    """Resolved info for a single canonical person."""

    canonical_name: str
    type: str  # "employee" | "external" | "non_human"
    tier: int  # 0 (Rich) → 5 (most distant). 99 = non_human / drop.
    notes: str = ""

    @property
    def is_human(self) -> bool:
        return self.type != "non_human"


# ─── Registry ───────────────────────────────────────────────────────────────


class PeopleRegistry:
    """Alias → canonical name resolver with tier + type classification."""

    def __init__(self, registry_path: Path | None = None):
        self._alias_to_canonical: dict[str, str] = {}
        self._info_by_canonical: dict[str, PersonInfo] = {}
        path = registry_path or self._discover_registry_path()
        self._load(path)

    @staticmethod
    def _discover_registry_path() -> Path:
        if _USER_OVERRIDE.exists():
            return _USER_OVERRIDE
        return _PACKAGED_REGISTRY

    def _load(self, path: Path) -> None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            log.warning("could not load people registry %s: %s", path, exc)
            return
        for entry in data.get("people", []):
            if not isinstance(entry, dict):
                continue
            canonical = entry.get("canonical_name")
            if not canonical:
                continue
            info = PersonInfo(
                canonical_name=canonical,
                type=entry.get("type", "external"),
                tier=int(entry.get("tier", 5)),
                notes=entry.get("notes", "") or "",
            )
            self._info_by_canonical[canonical] = info
            # Canonical name resolves to itself
            self._alias_to_canonical[canonical.lower()] = canonical
            for alias in entry.get("aliases", []) or []:
                if isinstance(alias, str):
                    self._alias_to_canonical[alias.strip().lower()] = canonical

    # ── Public API ─────────────────────────────────────────────────────────

    def resolve(self, name: str | None) -> tuple[str, PersonInfo] | None:
        """Look up a name. Returns (canonical_name, PersonInfo) or None.

        Strips Obsidian wiki-link brackets, surrounding whitespace, and
        case-insensitively matches against the alias table. Returns None
        if the name doesn't appear in the registry — caller decides
        whether to keep, drop, or build a placeholder.
        """
        if not name:
            return None
        cleaned = self._clean(name)
        if not cleaned:
            return None
        canonical = self._alias_to_canonical.get(cleaned.lower())
        if canonical is None:
            return None
        info = self._info_by_canonical[canonical]
        return canonical, info

    def is_known(self, name: str) -> bool:
        return self.resolve(name) is not None

    def is_non_human(self, name: str) -> bool:
        result = self.resolve(name)
        return result is not None and result[1].type == "non_human"

    def all_canonical(self) -> list[str]:
        return sorted(self._info_by_canonical.keys())

    @staticmethod
    def _clean(name: str) -> str:
        s = name.strip()
        # Strip Obsidian wiki-link brackets: [[name]] → name
        if s.startswith("[[") and s.endswith("]]"):
            s = s[2:-2]
        # Strip parenthetical handles: "Tom (tomhammaker)" → "Tom"
        if "(" in s and s.endswith(")"):
            s = s.split("(", 1)[0].strip()
        return s


# Module-level singleton — loaded once per process
registry = PeopleRegistry()


def resolve(name: str | None) -> tuple[str, PersonInfo] | None:
    """Convenience: PeopleRegistry singleton resolve."""
    return registry.resolve(name)
