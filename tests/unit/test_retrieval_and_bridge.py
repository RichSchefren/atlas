"""Unit tests for vault-search client + Intelligence Engine bridge.

Spec: PHASE-5-AND-BEYOND.md § 1.6 + § 1.7
"""

import json
from unittest.mock import MagicMock, patch

# ─── VaultSearchClient ──────────────────────────────────────────────────────


class TestVaultSearchClient:
    def test_empty_query_returns_empty(self):
        from atlas_core.retrieval import VaultSearchClient
        c = VaultSearchClient()
        assert c.search("") == []
        assert c.search("   ") == []

    def test_unreachable_daemon_returns_empty_not_crash(self):
        from atlas_core.retrieval import VaultSearchClient
        c = VaultSearchClient(base_url="http://localhost:1", timeout=0.5)
        assert c.search("hello") == []

    def test_health_returns_false_when_unreachable(self):
        from atlas_core.retrieval import VaultSearchClient
        c = VaultSearchClient(base_url="http://localhost:1", timeout=0.5)
        assert c.health() is False

    def test_parses_well_formed_response(self):
        from atlas_core.retrieval import VaultSearchClient, VaultSearchHit
        c = VaultSearchClient()

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "hits": [
                {"path": "/foo/bar.md", "score": 0.95, "excerpt": "hello"},
                {"path": "/baz.md", "score": 0.82, "excerpt": "world"},
            ],
        }
        with patch("httpx.post", return_value=fake_response):
            hits = c.search("query")
        assert len(hits) == 2
        assert isinstance(hits[0], VaultSearchHit)
        assert hits[0].path == "/foo/bar.md"
        assert hits[0].score == 0.95

    def test_non_200_returns_empty(self):
        from atlas_core.retrieval import VaultSearchClient
        c = VaultSearchClient()
        fake_response = MagicMock()
        fake_response.status_code = 503
        fake_response.text = "service unavailable"
        with patch("httpx.post", return_value=fake_response):
            assert c.search("query") == []


# ─── IntelligenceEngineBridge ───────────────────────────────────────────────


class TestIntelligenceEngineBridge:
    def test_emit_creates_file(self, tmp_path):
        from atlas_core.integrations import (
            AtlasEvent,
            IntelligenceEngineBridge,
        )
        bridge = IntelligenceEngineBridge(brain_dir=tmp_path / "brain")
        bridge.emit(AtlasEvent(
            kind="test",
            summary="hello",
            occurred_at="2026-04-26T00:00:00+00:00",
        ))
        events_file = tmp_path / "brain" / "atlas-events.jsonl"
        assert events_file.exists()
        with events_file.open() as f:
            row = json.loads(f.readline())
        assert row["kind"] == "test"
        assert row["summary"] == "hello"

    def test_emit_appends_not_overwrites(self, tmp_path):
        from atlas_core.integrations import (
            AtlasEvent,
            IntelligenceEngineBridge,
        )
        bridge = IntelligenceEngineBridge(brain_dir=tmp_path / "brain")
        for i in range(3):
            bridge.emit(AtlasEvent(
                kind="test",
                summary=f"event {i}",
                occurred_at="2026-04-26T00:00:00+00:00",
            ))
        events_file = tmp_path / "brain" / "atlas-events.jsonl"
        lines = events_file.read_text().splitlines()
        assert len(lines) == 3
        assert "event 0" in lines[0]
        assert "event 2" in lines[2]

    def test_emit_failure_is_silent(self, tmp_path):
        """Bridge errors must not crash the caller."""
        from atlas_core.integrations import (
            AtlasEvent,
            IntelligenceEngineBridge,
        )
        # Point at an unwritable path
        bridge = IntelligenceEngineBridge(brain_dir=tmp_path / "ro" / "brain")
        # Make parent unwritable
        (tmp_path / "ro").mkdir()
        (tmp_path / "ro").chmod(0o500)
        try:
            # Should not raise
            bridge.emit(AtlasEvent(
                kind="test",
                summary="x",
                occurred_at="2026-04-26T00:00:00+00:00",
            ))
        finally:
            (tmp_path / "ro").chmod(0o700)

    def test_adjudication_helper_shapes_event(self, tmp_path):
        from atlas_core.integrations import IntelligenceEngineBridge
        bridge = IntelligenceEngineBridge(brain_dir=tmp_path / "brain")
        bridge.emit_adjudication_resolved(
            proposal_id="adj_001",
            decision="accept",
            target_kref="kref://x/y",
            applied=True,
            actor="rich",
        )
        with (tmp_path / "brain" / "atlas-events.jsonl").open() as f:
            row = json.loads(f.readline())
        assert row["kind"] == "adjudication_resolved"
        assert "Rich accepted" in row["summary"]
        assert row["details"]["applied"] is True

    def test_ripple_cascade_helper(self, tmp_path):
        from atlas_core.integrations import IntelligenceEngineBridge
        bridge = IntelligenceEngineBridge(brain_dir=tmp_path / "brain")
        bridge.emit_ripple_cascade(
            upstream_kref="kref://x/upstream",
            impacted_count=5,
            contradictions_count=2,
        )
        with (tmp_path / "brain" / "atlas-events.jsonl").open() as f:
            row = json.loads(f.readline())
        assert row["kind"] == "ripple_cascade"
        assert row["details"]["impacted_count"] == 5
        assert row["details"]["contradictions_count"] == 2
