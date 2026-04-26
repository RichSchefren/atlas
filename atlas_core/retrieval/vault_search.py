"""HTTP client for the vault-search daemon at localhost:9878.

vault-search is Rich's existing 24/7 GPU-accelerated semantic
search service over his Obsidian vault. Atlas delegates rather
than reinventing — Bicameral did this too.

The daemon's API surface:
  POST /search { "q": "...", "k": 10 } → {"hits": [...]}
  GET  /health → {"status": "ok"}

Spec: PHASE-5-AND-BEYOND.md § 1.6
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any


log = logging.getLogger(__name__)


DEFAULT_VAULT_SEARCH_URL: str = "http://localhost:9878"
"""vault-search default endpoint. Override via ATLAS_VAULT_SEARCH_URL."""

DEFAULT_TIMEOUT_SEC: float = 5.0


@dataclass
class VaultSearchHit:
    """One hit returned from vault-search.

    `path` is the absolute Obsidian vault path. `score` is BGE
    similarity (0..1). `excerpt` is the surrounding paragraph
    vault-search returns.
    """

    path: str
    score: float
    excerpt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class VaultSearchClient:
    """Thin HTTP client. Constructed once, used many times.

    Falls back to empty-result list when vault-search is unreachable
    rather than crashing — Atlas continues operating with reduced
    retrieval rather than blocking on an external service.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_VAULT_SEARCH_URL,
        timeout: float = DEFAULT_TIMEOUT_SEC,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def search(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> list[VaultSearchHit]:
        """Synchronous BGE search. Returns up to `k` hits ordered by score."""
        if not query.strip():
            return []
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx required for VaultSearchClient") from exc

        try:
            response = httpx.post(
                f"{self.base_url}/search",
                json={"q": query, "k": k},
                timeout=self.timeout,
            )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            log.warning("vault-search unreachable: %s", exc)
            return []

        if response.status_code != 200:
            log.warning(
                "vault-search returned %d: %s",
                response.status_code, response.text[:200],
            )
            return []

        try:
            payload = response.json()
        except ValueError:
            return []

        hits = payload.get("hits", [])
        return [
            VaultSearchHit(
                path=str(h.get("path", "")),
                score=float(h.get("score", 0.0)),
                excerpt=str(h.get("excerpt", "")),
                metadata=h.get("metadata", {}),
            )
            for h in hits
            if isinstance(h, dict)
        ]

    def health(self) -> bool:
        """Best-effort liveness check. Returns False on any failure."""
        try:
            import httpx
            response = httpx.get(
                f"{self.base_url}/health", timeout=self.timeout,
            )
            return response.status_code == 200
        except Exception:
            return False
