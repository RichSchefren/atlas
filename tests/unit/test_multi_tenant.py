"""Unit tests for Tier 5 multi-tenant primitives.

Spec: PHASE-5-AND-BEYOND.md § 5
"""

from datetime import datetime, timedelta, timezone

import pytest


# ─── TenantContext ──────────────────────────────────────────────────────────


class TestTenantContext:
    def test_valid_id_constructs(self):
        from atlas_core.multi_tenant import TenantContext
        ctx = TenantContext(tenant_id="rich", actor="rich")
        assert ctx.tenant_id == "rich"
        assert ctx.kref_namespace == "kref://Tenants/rich/"

    def test_invalid_id_rejects(self):
        from atlas_core.multi_tenant import TenantContext
        for bad in ["", "rich/ben", "../etc/passwd", "rich ben", "x" * 100]:
            with pytest.raises(ValueError):
                TenantContext(tenant_id=bad)

    def test_kref_namespace_is_per_tenant(self):
        from atlas_core.multi_tenant import TenantContext
        a = TenantContext(tenant_id="alice")
        b = TenantContext(tenant_id="bob")
        assert a.kref_namespace != b.kref_namespace


# ─── TenantStorageFactory ──────────────────────────────────────────────────


class TestTenantStorageFactory:
    def test_creates_per_tenant_dirs(self, tmp_path):
        from atlas_core.multi_tenant import TenantStorageFactory
        factory = TenantStorageFactory(root=tmp_path)
        bundle_a = factory.for_tenant("alice")
        assert bundle_a["tenant_id"] == "alice"
        assert bundle_a["data_dir"] == tmp_path / "alice"
        assert bundle_a["data_dir"].exists()
        assert (tmp_path / "alice" / "adjudication").exists()

    def test_caches_per_tenant(self, tmp_path):
        from atlas_core.multi_tenant import TenantStorageFactory
        factory = TenantStorageFactory(root=tmp_path)
        b1 = factory.for_tenant("alice")
        b2 = factory.for_tenant("alice")
        assert b1 is b2  # same dict
        assert b1["quarantine"] is b2["quarantine"]

    def test_separate_tenants_get_separate_storage(self, tmp_path):
        from atlas_core.multi_tenant import TenantStorageFactory
        factory = TenantStorageFactory(root=tmp_path)
        alice = factory.for_tenant("alice")
        bob = factory.for_tenant("bob")
        assert alice["data_dir"] != bob["data_dir"]
        assert alice["quarantine"] is not bob["quarantine"]
        assert alice["ledger"] is not bob["ledger"]

    def test_reset_clears_cache(self, tmp_path):
        from atlas_core.multi_tenant import TenantStorageFactory
        factory = TenantStorageFactory(root=tmp_path)
        b1 = factory.for_tenant("alice")
        factory.reset()
        b2 = factory.for_tenant("alice")
        assert b1 is not b2


# ─── SharingPolicy + can_read ──────────────────────────────────────────────


class TestSharingPolicy:
    def test_grant_then_can_read(self, tmp_path):
        from atlas_core.multi_tenant import SharingPolicy, can_read, grant_share
        policy = SharingPolicy(path=tmp_path / "sharing.sqlite")
        kref = "kref://Tenants/alice/Beliefs/launch.belief"
        grant_share(
            policy,
            granter_tenant="alice",
            grantee_tenant="bob",
            kref_pattern=kref,
        )
        assert can_read(policy, requester_tenant="bob", target_kref=kref) is True

    def test_owner_always_reads_own(self, tmp_path):
        from atlas_core.multi_tenant import SharingPolicy, can_read
        policy = SharingPolicy(path=tmp_path / "sharing.sqlite")
        kref = "kref://Tenants/alice/Beliefs/x.belief"
        assert can_read(policy, requester_tenant="alice", target_kref=kref) is True

    def test_unrelated_tenant_cannot_read(self, tmp_path):
        from atlas_core.multi_tenant import SharingPolicy, can_read
        policy = SharingPolicy(path=tmp_path / "sharing.sqlite")
        kref = "kref://Tenants/alice/Beliefs/secret.belief"
        assert can_read(
            policy, requester_tenant="bob", target_kref=kref,
        ) is False

    def test_glob_pattern(self, tmp_path):
        from atlas_core.multi_tenant import SharingPolicy, can_read, grant_share
        policy = SharingPolicy(path=tmp_path / "sharing.sqlite")
        grant_share(
            policy,
            granter_tenant="alice",
            grantee_tenant="bob",
            kref_pattern="kref://Tenants/alice/Programs/*",
        )
        assert can_read(
            policy,
            requester_tenant="bob",
            target_kref="kref://Tenants/alice/Programs/origins.program",
        ) is True
        assert can_read(
            policy,
            requester_tenant="bob",
            target_kref="kref://Tenants/alice/Beliefs/secret.belief",
        ) is False

    def test_revoke_blocks_read(self, tmp_path):
        from atlas_core.multi_tenant import (
            SharingPolicy, can_read, grant_share, revoke_share,
        )
        policy = SharingPolicy(path=tmp_path / "sharing.sqlite")
        kref = "kref://Tenants/alice/Beliefs/x.belief"
        grant_share(
            policy, granter_tenant="alice", grantee_tenant="bob",
            kref_pattern=kref,
        )
        assert can_read(policy, requester_tenant="bob", target_kref=kref)
        revoked = revoke_share(
            policy, granter_tenant="alice", grantee_tenant="bob",
            kref_pattern=kref,
        )
        assert revoked is True
        assert not can_read(
            policy, requester_tenant="bob", target_kref=kref,
        )

    def test_expired_grant_does_not_grant_read(self, tmp_path):
        from atlas_core.multi_tenant import SharingPolicy, can_read, grant_share
        policy = SharingPolicy(path=tmp_path / "sharing.sqlite")
        kref = "kref://Tenants/alice/Beliefs/x.belief"
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        grant_share(
            policy, granter_tenant="alice", grantee_tenant="bob",
            kref_pattern=kref, expires_at=past,
        )
        assert not can_read(policy, requester_tenant="bob", target_kref=kref)


# ─── FederatedAdjudication ─────────────────────────────────────────────────


class TestFederatedAdjudication:
    def test_routes_to_both_tenant_dirs(self, tmp_path):
        from atlas_core.multi_tenant import (
            FederatedAdjudication, route_to_tenants,
        )
        adj = FederatedAdjudication(
            proposal_id="fed_001",
            asserting_tenant="alice",
            contradicting_tenant="bob",
            target_kref="kref://shared/Programs/launch_date",
            asserted_value="2026-05-15",
            contradicting_value="2026-05-22",
        )
        a_dir = tmp_path / "alice" / "adjudication"
        b_dir = tmp_path / "bob" / "adjudication"
        a_path, b_path = route_to_tenants(
            adj, asserting_dir=a_dir, contradicting_dir=b_dir,
        )
        assert a_path.exists()
        assert b_path.exists()

    def test_perspective_text_differs(self, tmp_path):
        from atlas_core.multi_tenant import FederatedAdjudication
        adj = FederatedAdjudication(
            proposal_id="fed_002",
            asserting_tenant="alice",
            contradicting_tenant="bob",
            target_kref="kref://shared/x",
            asserted_value="A says X",
            contradicting_value="B says Y",
        )
        from_alice = adj.to_markdown("alice")
        from_bob = adj.to_markdown("bob")
        assert "bob disagrees" in from_alice
        assert "alice" in from_bob
        # Each side sees their own value as "you"
        assert "A says X" in from_alice
        assert "B says Y" in from_bob
