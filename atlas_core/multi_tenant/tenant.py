"""TenantContext + per-tenant trust storage factory.

Atlas's storage substrate stays single-instance (one Neo4j, shared
graph) but each tenant gets its own SQLite trust ledger + quarantine
+ adjudication queue. Identity boundary = tenant_id stamped onto
every write that originates with that tenant's actor.

Spec: PHASE-5-AND-BEYOND.md § 5.1
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


# Tenant IDs are filesystem-safe slugs. Reject anything else early.
_VALID_TENANT_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")

DEFAULT_TENANT_ROOT: Path = Path.home() / ".atlas" / "tenants"


@dataclass(frozen=True)
class TenantContext:
    """The carrier identity for every multi-tenant operation.

    `tenant_id` is the durable identifier (filesystem-safe). `actor`
    is the human or agent name within that tenant — used for ledger
    audit + adjudication routing.
    """

    tenant_id: str
    actor: str = ""

    def __post_init__(self):
        if not _VALID_TENANT_ID.match(self.tenant_id):
            raise ValueError(
                f"tenant_id must match {_VALID_TENANT_ID.pattern}; "
                f"got {self.tenant_id!r}"
            )

    @property
    def kref_namespace(self) -> str:
        """Per-tenant kref prefix. Lets the Cypher query rewriter
        scope reads/writes by tenant when sharing policies kick in."""
        return f"kref://Tenants/{self.tenant_id}/"


def tenant_data_dir(tenant_id: str, *, root: Path | None = None) -> Path:
    """Returns the per-tenant data directory. Creates on first access."""
    if not _VALID_TENANT_ID.match(tenant_id):
        raise ValueError(f"invalid tenant_id: {tenant_id!r}")
    base = Path(root or DEFAULT_TENANT_ROOT)
    out = base / tenant_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "adjudication").mkdir(exist_ok=True)
    return out


class TenantStorageFactory:
    """Constructs per-tenant trust storage instances on demand.

    Caches by tenant_id so repeated calls to .for_tenant() return
    the same QuarantineStore + HashChainedLedger instance per
    tenant. Cleared via .reset().
    """

    def __init__(self, *, root: Path | None = None):
        self.root = Path(root or DEFAULT_TENANT_ROOT)
        self._cache: dict[str, dict] = {}

    def for_tenant(self, tenant_id: str) -> dict:
        """Returns a dict with `quarantine`, `ledger`, and
        `adjudication_dir` for the tenant. Creates on demand."""
        if tenant_id in self._cache:
            return self._cache[tenant_id]

        from atlas_core.trust import HashChainedLedger, QuarantineStore

        data_dir = tenant_data_dir(tenant_id, root=self.root)
        bundle = {
            "tenant_id": tenant_id,
            "data_dir": data_dir,
            "quarantine": QuarantineStore(data_dir / "candidates.db"),
            "ledger": HashChainedLedger(data_dir / "ledger.db"),
            "adjudication_dir": data_dir / "adjudication",
        }
        self._cache[tenant_id] = bundle
        return bundle

    def reset(self) -> None:
        """Clear the in-memory cache. Does not delete on-disk data."""
        self._cache.clear()
