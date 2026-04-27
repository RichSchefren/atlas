"""Tier 5 — multi-tenant Atlas.

Multiple humans share one Neo4j substrate while keeping their own
trust ledgers, adjudication queues, and per-kref sharing policies.

Three modules:
  tenant.py       — TenantContext + per-tenant TrustStorePair
  sharing.py      — explicit sharing policies + Cypher rewriter
  federated.py    — federated adjudication across tenants

Spec: PHASE-5-AND-BEYOND.md § 5
"""

from atlas_core.multi_tenant.federated import (
    FederatedAdjudication,
    route_to_tenants,
)
from atlas_core.multi_tenant.sharing import (
    SharingGrant,
    SharingPolicy,
    can_read,
    grant_share,
    revoke_share,
)
from atlas_core.multi_tenant.tenant import (
    TenantContext,
    TenantStorageFactory,
    tenant_data_dir,
)

__all__ = [
    "FederatedAdjudication",
    "SharingGrant",
    "SharingPolicy",
    "TenantContext",
    "TenantStorageFactory",
    "can_read",
    "grant_share",
    "route_to_tenants",
    "revoke_share",
    "tenant_data_dir",
]
