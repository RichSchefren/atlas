"""Unit tests for the ingestion pipeline framework + Vault + Limitless extractors."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as t:
        yield Path(t)


@pytest.fixture
def quarantine(tmp_dir):
    from atlas_core.trust import QuarantineStore
    return QuarantineStore(tmp_dir / "candidates.db")


def write_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ─── Cursor persistence ─────────────────────────────────────────────────────


class TestCursorPersistence:
    def test_fresh_cursor_when_no_file(self, tmp_dir, quarantine):
        from atlas_core.ingestion import VaultExtractor
        from atlas_core.ingestion.base import StreamConfig

        ex = VaultExtractor(
            quarantine=quarantine,
            vault_roots=[tmp_dir],
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        cursor = ex.load_cursor()
        assert cursor.last_processed_at.startswith("1970-01-01")

    def test_cursor_round_trip(self, tmp_dir, quarantine):
        from atlas_core.ingestion import VaultExtractor
        from atlas_core.ingestion.base import IngestionCursor, StreamConfig, StreamType

        ex = VaultExtractor(
            quarantine=quarantine,
            vault_roots=[tmp_dir],
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        new_cursor = IngestionCursor(
            stream=StreamType.VAULT,
            last_processed_at="2026-04-25T22:00:00+00:00",
            last_processed_id="some/file.md",
        )
        ex.save_cursor(new_cursor)
        loaded = ex.load_cursor()
        assert loaded.last_processed_at == "2026-04-25T22:00:00+00:00"
        assert loaded.last_processed_id == "some/file.md"


# ─── Vault extractor ────────────────────────────────────────────────────────


class TestVaultExtractor:
    def test_finds_modified_files(self, tmp_dir, quarantine):
        from atlas_core.ingestion import VaultExtractor
        from atlas_core.ingestion.base import StreamConfig

        vault = tmp_dir / "vault"
        write_md(vault / "people" / "ashley.md", "---\naliases: [Ash]\n---\nbody")

        ex = VaultExtractor(
            quarantine=quarantine,
            vault_roots=[vault],
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        cursor = ex.load_cursor()
        events = ex.fetch_new_events(cursor)
        assert len(events) == 1
        assert events[0]["relpath"] == "people/ashley.md"

    def test_ignores_atlas_self_writes(self, tmp_dir, quarantine):
        from atlas_core.ingestion import VaultExtractor
        from atlas_core.ingestion.base import StreamConfig

        vault = tmp_dir / "vault"
        write_md(vault / "00 Atlas" / "ripple_report.md", "ignored")
        write_md(vault / "00 Atlas" / "adjudication" / "x.md", "also ignored")
        write_md(vault / "real" / "person.md", "---\nrole: ops\n---\n")

        ex = VaultExtractor(
            quarantine=quarantine,
            vault_roots=[vault],
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        events = ex.fetch_new_events(ex.load_cursor())
        relpaths = {e["relpath"] for e in events}
        assert "real/person.md" in relpaths
        assert not any("00 Atlas" in r for r in relpaths)

    def test_ignores_briefing_session_context(self, tmp_dir, quarantine):
        from atlas_core.ingestion import VaultExtractor
        from atlas_core.ingestion.base import StreamConfig

        vault = tmp_dir / "vault"
        write_md(vault / "memory" / "BRIEFING.md", "ignored")
        write_md(vault / "memory" / "session-context.md", "ignored")
        write_md(vault / "memory" / "real-note.md", "kept")

        ex = VaultExtractor(
            quarantine=quarantine, vault_roots=[vault],
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        events = ex.fetch_new_events(ex.load_cursor())
        relpaths = {e["relpath"] for e in events}
        assert "memory/real-note.md" in relpaths
        assert "memory/BRIEFING.md" not in relpaths
        assert "memory/session-context.md" not in relpaths

    def test_extracts_frontmatter_claims(self, tmp_dir, quarantine):
        from atlas_core.ingestion import VaultExtractor
        from atlas_core.ingestion.base import StreamConfig

        vault = tmp_dir / "vault"
        path = vault / "people" / "ashley.md"
        write_md(
            path,
            '---\naliases: ["Ashley", "Ash", "A.Shaw"]\nrole: operations\n---\nbody',
        )

        ex = VaultExtractor(
            quarantine=quarantine, vault_roots=[vault],
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        events = ex.fetch_new_events(ex.load_cursor())
        claims = ex.extract_claims_from_event(events[0])

        predicates = {c.predicate for c in claims}
        assert "vault.frontmatter.aliases" in predicates
        assert "vault.frontmatter.role" in predicates

        alias_values = {c.object_value for c in claims if "aliases" in c.predicate}
        assert "Ashley" in alias_values
        assert "Ash" in alias_values
        assert "A.Shaw" in alias_values

    def test_run_once_inserts_into_quarantine(self, tmp_dir, quarantine):
        from atlas_core.ingestion import VaultExtractor
        from atlas_core.ingestion.base import StreamConfig

        vault = tmp_dir / "vault"
        write_md(vault / "ashley.md", "---\nrole: operations\n---\n")

        ex = VaultExtractor(
            quarantine=quarantine, vault_roots=[vault],
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        result = ex.run_once()

        assert result.events_processed == 1
        assert result.claims_extracted >= 1
        assert result.cursor_advanced_to != ""

        # Re-running with no new files is a no-op
        result2 = ex.run_once()
        assert result2.events_processed == 0


# ─── Limitless extractor ────────────────────────────────────────────────────


class TestLimitlessExtractor:
    def test_extracts_decisions_and_action_items(self, tmp_dir, quarantine):
        from atlas_core.ingestion import LimitlessExtractor
        from atlas_core.ingestion.base import StreamConfig

        archive = tmp_dir / "limitless-archive"
        write_md(
            archive / "2026-04-25-team-call.md",
            (
                "---\n"
                "duration_minutes: 47\n"
                "participants:\n"
                "  - Rich\n"
                "  - Ashley\n"
                "decisions:\n"
                "  - Move ZenithPro Q3 launch to Q4\n"
                "action_items:\n"
                "  - Rich to send proposal by Friday\n"
                "projects:\n"
                "  - ZenithPro\n"
                "---\n"
                "transcript body here\n"
            ),
        )

        ex = LimitlessExtractor(
            quarantine=quarantine, archive_root=archive,
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        result = ex.run_once()

        assert result.events_processed == 1
        # Should produce: 1 person (Ashley, Rich filtered) + 1 decision +
        # 1 action_item (Commitment) + 1 project = 4 claims
        assert result.claims_extracted >= 4

    def test_filters_rich_from_participants(self, tmp_dir, quarantine):
        from atlas_core.ingestion import LimitlessExtractor
        from atlas_core.ingestion.base import StreamConfig

        archive = tmp_dir / "Limitless"
        write_md(
            archive / "session.md",
            "---\nparticipants:\n  - Rich\n  - rich\n---\nbody",
        )
        ex = LimitlessExtractor(
            quarantine=quarantine, archive_root=archive,
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        events = ex.fetch_new_events(ex.load_cursor())
        claims = ex.extract_claims_from_event(events[0])
        # No Person claims for Rich himself
        for c in claims:
            assert "rich" not in c.subject_kref.lower() or "rich" != c.subject_kref.split("/")[-1].split(".")[0]

    def test_no_frontmatter_returns_no_claims(self, tmp_dir, quarantine):
        from atlas_core.ingestion import LimitlessExtractor
        from atlas_core.ingestion.base import StreamConfig

        archive = tmp_dir / "Limitless"
        write_md(archive / "plain.md", "just text, no frontmatter")
        ex = LimitlessExtractor(
            quarantine=quarantine, archive_root=archive,
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        )
        events = ex.fetch_new_events(ex.load_cursor())
        claims = ex.extract_claims_from_event(events[0])
        assert claims == []


# ─── Per-stream confidence floors ───────────────────────────────────────────


class TestConfidenceFloors:
    def test_all_six_streams_have_floors(self):
        from atlas_core.ingestion import STREAM_CONFIDENCE_FLOORS
        from atlas_core.ingestion.base import StreamType

        for stream in StreamType:
            assert stream in STREAM_CONFIDENCE_FLOORS, (
                f"Missing confidence floor for {stream.value}"
            )

    def test_vault_highest_screenpipe_lowest(self):
        from atlas_core.ingestion import STREAM_CONFIDENCE_FLOORS
        from atlas_core.ingestion.base import StreamType

        assert (
            STREAM_CONFIDENCE_FLOORS[StreamType.VAULT]
            > STREAM_CONFIDENCE_FLOORS[StreamType.LIMITLESS]
        )
        assert (
            STREAM_CONFIDENCE_FLOORS[StreamType.LIMITLESS]
            > STREAM_CONFIDENCE_FLOORS[StreamType.SCREENPIPE]
        )


# ─── Orchestrator ───────────────────────────────────────────────────────────


class TestOrchestrator:
    def test_register_and_list(self, tmp_dir, quarantine):
        from atlas_core.ingestion import (
            IngestionOrchestrator,
            LimitlessExtractor,
            VaultExtractor,
        )
        from atlas_core.ingestion.base import StreamConfig, StreamType

        orch = IngestionOrchestrator()
        orch.register(VaultExtractor(
            quarantine=quarantine, vault_roots=[tmp_dir / "v"],
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        ))
        orch.register(LimitlessExtractor(
            quarantine=quarantine, archive_root=tmp_dir / "l",
            config=StreamConfig(cursor_dir=tmp_dir / "cursors2"),
        ))

        streams = orch.registered_streams()
        assert StreamType.VAULT in streams
        assert StreamType.LIMITLESS in streams

    def test_duplicate_register_raises(self, tmp_dir, quarantine):
        from atlas_core.ingestion import IngestionOrchestrator, VaultExtractor
        from atlas_core.ingestion.base import StreamConfig

        orch = IngestionOrchestrator()
        orch.register(VaultExtractor(
            quarantine=quarantine, vault_roots=[tmp_dir],
            config=StreamConfig(cursor_dir=tmp_dir / "c"),
        ))
        with pytest.raises(ValueError, match="already registered"):
            orch.register(VaultExtractor(
                quarantine=quarantine, vault_roots=[tmp_dir],
                config=StreamConfig(cursor_dir=tmp_dir / "c2"),
            ))

    def test_run_cycle_aggregates(self, tmp_dir, quarantine):
        from atlas_core.ingestion import (
            IngestionOrchestrator,
            LimitlessExtractor,
            VaultExtractor,
        )
        from atlas_core.ingestion.base import StreamConfig

        vault = tmp_dir / "vault"
        write_md(vault / "x.md", "---\nrole: ops\n---\n")

        archive = tmp_dir / "Limitless"
        write_md(
            archive / "s.md",
            "---\nparticipants:\n  - Rich\n  - Ashley\n---\nbody",
        )

        orch = IngestionOrchestrator()
        orch.register(VaultExtractor(
            quarantine=quarantine, vault_roots=[vault],
            config=StreamConfig(cursor_dir=tmp_dir / "cursors"),
        ))
        orch.register(LimitlessExtractor(
            quarantine=quarantine, archive_root=archive,
            config=StreamConfig(cursor_dir=tmp_dir / "cursors2"),
        ))

        report = orch.run_cycle()
        assert report.total_events >= 2  # at least 1 vault + 1 limitless
        assert report.total_claims >= 2
        assert report.total_errors == 0
