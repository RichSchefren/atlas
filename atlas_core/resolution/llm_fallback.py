"""LLM-fallback entity resolver — last stop when alias and fuzzy both miss.

When a surface form can't be mapped exactly or fuzzily, we fire one
Claude Haiku call asking "is X the same entity as any of these
known kref candidates?" The candidates pool is a structured slice
of the graph (e.g., when resolving a Person mention, we send the
list of all known Person krefs and their aliases).

Aggressively cached: every (surface, candidate_pool_hash) tuple
maps to one cached answer in ~/.atlas/resolution_cache.sqlite. The
LLM call is the cost driver, so the cache earns back the budget
within hours of normal use.

Spec: PHASE-5-AND-BEYOND.md § 1.3
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from atlas_core.resolution.aliases import AliasDictionary

log = logging.getLogger(__name__)


DEFAULT_CACHE_PATH: Path = Path.home() / ".atlas" / "resolution_cache.sqlite"

# Claude Haiku 4.5 is the cheapest correct-enough model for entity
# resolution. Atlas does not chain to Sonnet/Opus here — accuracy
# beyond Haiku doesn't pay the cost.
DEFAULT_LLM_MODEL: str = "claude-haiku-4-5-20251001"
DEFAULT_MAX_CANDIDATES: int = 25
"""Cap candidates we send to the LLM — past 25 the prompt loses focus."""


@dataclass
class LLMMatch:
    kref: str
    surface: str
    confidence: float       # parsed from LLM's stated certainty
    rationale: str
    source: str = "llm_fallback"


@dataclass
class NoMatch:
    """Returned when the LLM concludes no candidate is the right one.

    `should_create_new` is True if the LLM thinks this is a new
    entity Atlas hasn't seen — caller can mint a fresh kref.
    """

    surface: str
    rationale: str
    should_create_new: bool


def _cache_key(surface: str, candidate_pool: list[str]) -> str:
    """Stable hash of (surface, pool) so cache lookups are
    deterministic across runs."""
    payload = json.dumps(
        {"surface": surface.lower().strip(), "pool": sorted(candidate_pool)},
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResolutionCache:
    """SQLite-backed cache for the LLM fallback. Per-host file."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or DEFAULT_CACHE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS resolution_cache ("
                "  cache_key TEXT PRIMARY KEY,"
                "  surface TEXT NOT NULL,"
                "  result_json TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")"
            )

    def get(self, key: str) -> dict | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT result_json FROM resolution_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def put(self, key: str, surface: str, result: dict) -> None:
        from datetime import datetime, timezone
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO resolution_cache "
                "(cache_key, surface, result_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    key, surface, json.dumps(result),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


class LLMEntityResolver:
    """Constructed once, called many times. Holds the Anthropic client
    and the resolution cache."""

    def __init__(
        self,
        aliases: AliasDictionary,
        *,
        cache: ResolutionCache | None = None,
        model: str = DEFAULT_LLM_MODEL,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ):
        self.aliases = aliases
        self.cache = cache or ResolutionCache()
        self.model = model
        self.max_candidates = max_candidates
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY required for LLM-fallback resolution. "
                "Set it or rely on alias + fuzzy layers only."
            )
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic SDK required") from exc
        self._client = Anthropic(api_key=api_key)

    async def resolve(
        self,
        surface: str,
        kref_kind: str = "Person",
    ) -> LLMMatch | NoMatch:
        """Resolve a surface form against candidates of the given kind.

        `kref_kind` filters the candidate pool by the entity type
        suffix in the kref (e.g., "Person" matches "kref://*/People/
        *.person"). Limits the LLM's choice space to relevant entities.
        """
        candidates = [
            k for k in self.aliases.known_krefs()
            if k.endswith(f".{kref_kind.lower()}")
        ][: self.max_candidates]

        # Cache lookup
        key = _cache_key(surface, candidates)
        cached = self.cache.get(key)
        if cached is not None:
            log.debug("Resolution cache HIT for %r", surface)
            return self._cached_to_result(cached, surface)

        # Live LLM call
        if not candidates:
            return NoMatch(
                surface=surface,
                rationale=f"No known {kref_kind} candidates yet",
                should_create_new=True,
            )

        self._ensure_client()
        candidates_text = "\n".join(
            f"- {kref}  ({', '.join(self.aliases.all_surfaces_for(kref))})"
            for kref in candidates
        )
        prompt = (
            f"Surface form: {surface!r}\n"
            f"Known {kref_kind} candidates:\n{candidates_text}\n\n"
            "Reply with one JSON line. Pick the kref of the best match,"
            " or 'NEW' if this is a new entity, or 'AMBIGUOUS' if you "
            "can't decide.\n"
            'Format: {"kref":"<chosen_kref_or_NEW_or_AMBIGUOUS>",'
            ' "confidence":<0..1>, "rationale":"<one short sentence>"}'
        )

        response = self._client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return NoMatch(
                surface=surface,
                rationale=f"LLM returned non-JSON: {text[:100]}",
                should_create_new=False,
            )

        # Cache before returning
        self.cache.put(key, surface, parsed)
        return self._cached_to_result(parsed, surface)

    def _cached_to_result(
        self, parsed: dict, surface: str,
    ) -> LLMMatch | NoMatch:
        kref = parsed.get("kref", "")
        if kref in {"NEW", "AMBIGUOUS"}:
            return NoMatch(
                surface=surface,
                rationale=parsed.get("rationale", ""),
                should_create_new=(kref == "NEW"),
            )
        return LLMMatch(
            kref=kref,
            surface=surface,
            confidence=float(parsed.get("confidence", 0.5)),
            rationale=parsed.get("rationale", ""),
        )
