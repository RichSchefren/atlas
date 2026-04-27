"""Per-kref sharing policies + Cypher-level read filter.

A SharingPolicy holds explicit grants of the form: tenant A can
read these specific krefs of tenant B (with optional expiry). The
Cypher query rewriter filters every read by the requester's tenant
+ active grants.

Spec: PHASE-5-AND-BEYOND.md § 5.2
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_SHARING_DB: Path = Path.home() / ".atlas" / "sharing.sqlite"


@dataclass(frozen=True)
class SharingGrant:
    """One row in the sharing table."""

    granter_tenant: str   # who owns the kref
    grantee_tenant: str   # who is being granted read access
    kref_pattern: str     # exact kref OR a kref://prefix/* glob
    expires_at: Optional[str] = None
    granted_at: str = ""

    def is_active(self, *, now: Optional[datetime] = None) -> bool:
        if not self.expires_at:
            return True
        cmp_now = (now or datetime.now(timezone.utc)).isoformat()
        return cmp_now < self.expires_at


class SharingPolicy:
    """SQLite-backed grant store. One file per Atlas instance."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or DEFAULT_SHARING_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sharing_grants ("
                "  granter_tenant TEXT NOT NULL,"
                "  grantee_tenant TEXT NOT NULL,"
                "  kref_pattern TEXT NOT NULL,"
                "  expires_at TEXT,"
                "  granted_at TEXT NOT NULL,"
                "  PRIMARY KEY (granter_tenant, grantee_tenant, kref_pattern)"
                ")"
            )

    def grant(
        self,
        *,
        granter_tenant: str,
        grantee_tenant: str,
        kref_pattern: str,
        expires_at: Optional[str] = None,
    ) -> SharingGrant:
        granted_at = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sharing_grants "
                "(granter_tenant, grantee_tenant, kref_pattern, "
                " expires_at, granted_at) VALUES (?, ?, ?, ?, ?)",
                (granter_tenant, grantee_tenant, kref_pattern,
                 expires_at, granted_at),
            )
        return SharingGrant(
            granter_tenant=granter_tenant,
            grantee_tenant=grantee_tenant,
            kref_pattern=kref_pattern,
            expires_at=expires_at,
            granted_at=granted_at,
        )

    def revoke(
        self,
        *,
        granter_tenant: str,
        grantee_tenant: str,
        kref_pattern: str,
    ) -> bool:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "DELETE FROM sharing_grants "
                "WHERE granter_tenant = ? AND grantee_tenant = ? "
                "  AND kref_pattern = ?",
                (granter_tenant, grantee_tenant, kref_pattern),
            )
            return cursor.rowcount > 0

    def grants_for_grantee(self, grantee_tenant: str) -> list[SharingGrant]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM sharing_grants WHERE grantee_tenant = ?",
                (grantee_tenant,),
            ).fetchall()
        return [SharingGrant(**dict(r)) for r in rows]

    def grants_from_granter(self, granter_tenant: str) -> list[SharingGrant]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM sharing_grants WHERE granter_tenant = ?",
                (granter_tenant,),
            ).fetchall()
        return [SharingGrant(**dict(r)) for r in rows]


def can_read(
    policy: SharingPolicy,
    *,
    requester_tenant: str,
    target_kref: str,
) -> bool:
    """Permission check: does requester_tenant have read access on
    target_kref? Owner-tenant always reads its own krefs."""
    owner_prefix = f"kref://Tenants/{requester_tenant}/"
    if target_kref.startswith(owner_prefix):
        return True
    for grant in policy.grants_for_grantee(requester_tenant):
        if not grant.is_active():
            continue
        if grant.kref_pattern == target_kref:
            return True
        if grant.kref_pattern.endswith("*"):
            prefix = grant.kref_pattern[:-1]
            if target_kref.startswith(prefix):
                return True
    return False


def grant_share(
    policy: SharingPolicy,
    *,
    granter_tenant: str,
    grantee_tenant: str,
    kref_pattern: str,
    expires_at: Optional[str] = None,
) -> SharingGrant:
    """Convenience surface for the MCP `sharing.grant` tool."""
    return policy.grant(
        granter_tenant=granter_tenant,
        grantee_tenant=grantee_tenant,
        kref_pattern=kref_pattern,
        expires_at=expires_at,
    )


def revoke_share(
    policy: SharingPolicy,
    *,
    granter_tenant: str,
    grantee_tenant: str,
    kref_pattern: str,
) -> bool:
    return policy.revoke(
        granter_tenant=granter_tenant,
        grantee_tenant=grantee_tenant,
        kref_pattern=kref_pattern,
    )
