"""Unit tests for the daemon health logger.

Spec: PHASE-5-AND-BEYOND.md § 1.1
"""

import json

import pytest


class TestHealthLogger:
    def test_append_creates_file(self, tmp_path):
        from atlas_core.daemon import HealthLogger
        from atlas_core.daemon.health import HealthRow
        h = HealthLogger("test_daemon", health_dir=tmp_path)
        h.append(HealthRow(
            daemon="test_daemon",
            started_at="2026-04-26T00:00:00+00:00",
            finished_at="2026-04-26T00:00:30+00:00",
            success=True,
            elapsed_sec=30.0,
            summary={"events": 5},
        ))
        assert (tmp_path / "test_daemon.jsonl").exists()

    def test_latest_returns_most_recent(self, tmp_path):
        from atlas_core.daemon import HealthLogger
        from atlas_core.daemon.health import HealthRow
        h = HealthLogger("test_daemon", health_dir=tmp_path)
        for i in range(3):
            h.append(HealthRow(
                daemon="test_daemon",
                started_at=f"2026-04-26T00:0{i}:00+00:00",
                finished_at=f"2026-04-26T00:0{i}:30+00:00",
                success=True,
                elapsed_sec=float(i),
                summary={"i": i},
            ))
        latest = h.latest()
        assert latest is not None
        assert latest.elapsed_sec == 2.0
        assert latest.summary["i"] == 2

    def test_latest_returns_none_when_empty(self, tmp_path):
        from atlas_core.daemon import HealthLogger
        h = HealthLogger("noexist", health_dir=tmp_path)
        assert h.latest() is None

    def test_health_row_round_trips_through_json(self, tmp_path):
        from atlas_core.daemon import HealthLogger
        from atlas_core.daemon.health import HealthRow
        h = HealthLogger("test_daemon", health_dir=tmp_path)
        h.append(HealthRow(
            daemon="test_daemon",
            started_at="2026-04-26T00:00:00+00:00",
            finished_at="2026-04-26T00:00:30+00:00",
            success=False,
            elapsed_sec=12.5,
            summary={"streams": ["vault", "limitless"]},
            error="connection refused",
        ))
        latest = h.latest()
        assert latest.error == "connection refused"
        assert latest.summary["streams"] == ["vault", "limitless"]
        assert latest.success is False

    def test_silent_on_unwritable_path(self, tmp_path):
        """Health logging is best-effort. If the path becomes unwritable,
        the daemon must continue."""
        from atlas_core.daemon import HealthLogger
        from atlas_core.daemon.health import HealthRow
        ro_dir = tmp_path / "ro"
        ro_dir.mkdir()
        ro_dir.chmod(0o500)
        try:
            h = HealthLogger("test", health_dir=ro_dir)
            # Should not raise
            h.append(HealthRow(
                daemon="test",
                started_at="2026-04-26T00:00:00+00:00",
                success=True,
            ))
        finally:
            ro_dir.chmod(0o700)
