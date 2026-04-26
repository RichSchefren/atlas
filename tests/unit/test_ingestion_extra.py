"""Unit tests for the four W7+ extractors: Screenpipe, Claude sessions,
Fireflies (stub), iMessage."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def quarantine(tmp_path):
    from atlas_core.trust import QuarantineStore
    return QuarantineStore(tmp_path / "candidates.db")


# ─── Screenpipe ──────────────────────────────────────────────────────────────


@pytest.fixture
def screenpipe_db(tmp_path):
    """Fixture: a tiny audio_transcriptions table mimicking Screenpipe."""
    db_path = tmp_path / "screenpipe_fake.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE audio_transcriptions(
            id INTEGER PRIMARY KEY,
            audio_chunk_id INTEGER,
            timestamp TEXT,
            transcription TEXT,
            device TEXT,
            is_input_device INTEGER DEFAULT 1,
            speaker_id INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO audio_transcriptions(id, audio_chunk_id, timestamp, "
        "transcription, device, speaker_id) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "2026-04-25 12:00:00", "Short", "MacBook Mic", None),  # too short
            (2, 1, "2026-04-25 12:00:30", "This is a longer transcription that meets the floor.", "MacBook Mic", 7),
            (3, 1, "2026-04-25 12:01:00", "Another solid sentence captured by Screenpipe today.", "MacBook Mic", 7),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


class TestScreenpipeExtractor:
    def test_skips_short_transcriptions(self, quarantine, screenpipe_db):
        from atlas_core.ingestion import ScreenpipeExtractor, IngestionCursor, StreamType

        ext = ScreenpipeExtractor(quarantine=quarantine, db_path=screenpipe_db)
        events = ext.fetch_new_events(IngestionCursor.fresh(StreamType.SCREENPIPE))
        # Only ids 2 and 3 pass the 40-char floor
        assert {e["id"] for e in events} == {2, 3}

    def test_extracts_one_claim_per_event(self, quarantine, screenpipe_db):
        from atlas_core.ingestion import ScreenpipeExtractor

        ext = ScreenpipeExtractor(quarantine=quarantine, db_path=screenpipe_db)
        claims = ext.extract_claims_from_event({
            "id": 2,
            "timestamp": "2026-04-25 12:00:30",
            "transcription": "Hello world",
            "device": "MacBook Mic",
            "speaker_id": 7,
        })
        assert len(claims) == 1
        c = claims[0]
        assert c.predicate == "said"
        assert c.lane == "atlas_observational"
        assert "Speakers/7.speaker" in c.subject_kref

    def test_subject_falls_back_to_device_when_no_speaker(self, quarantine, screenpipe_db):
        from atlas_core.ingestion import ScreenpipeExtractor

        ext = ScreenpipeExtractor(quarantine=quarantine, db_path=screenpipe_db)
        claims = ext.extract_claims_from_event({
            "id": 1,
            "timestamp": "2026-04-25 12:00:00",
            "transcription": "Hello world",
            "device": "MacBook Mic",
            "speaker_id": None,
        })
        assert "Devices/MacBook_Mic.device" in claims[0].subject_kref

    def test_cursor_records_id_and_timestamp(self, quarantine, screenpipe_db):
        from atlas_core.ingestion import ScreenpipeExtractor

        ext = ScreenpipeExtractor(quarantine=quarantine, db_path=screenpipe_db)
        cursor = ext.cursor_for_event({"id": 99, "timestamp": "2026-04-25 12:00:30"})
        assert cursor.last_processed_id == "99"
        assert cursor.last_processed_at.startswith("2026-04-25T12:00:30")

    def test_missing_db_returns_empty(self, quarantine, tmp_path):
        from atlas_core.ingestion import ScreenpipeExtractor, IngestionCursor, StreamType

        ext = ScreenpipeExtractor(
            quarantine=quarantine,
            db_path=tmp_path / "nonexistent.db",
        )
        assert ext.fetch_new_events(
            IngestionCursor.fresh(StreamType.SCREENPIPE)
        ) == []


# ─── Claude sessions ─────────────────────────────────────────────────────────


@pytest.fixture
def claude_projects_root(tmp_path):
    """Fixture: a directory with two JSONL session files."""
    root = tmp_path / "projects" / "-Users-rich"
    root.mkdir(parents=True)

    rows_a = [
        {"type": "file-history-snapshot"},  # ignored
        {
            "type": "user",
            "uuid": "u1",
            "timestamp": "2026-04-25T10:00:00.000Z",
            "sessionId": "sess_a",
            "cwd": "/Users/rich",
            "message": {"role": "user", "content": "Build the auth module please"},
        },
        {
            "type": "user",
            "uuid": "u2",
            "timestamp": "2026-04-25T10:05:00.000Z",
            "sessionId": "sess_a",
            "cwd": "/Users/rich",
            "message": {"role": "user", "content": "<local-command-caveat>noise"},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "timestamp": "2026-04-25T10:01:00.000Z",
        },  # ignored
    ]
    (root / "sess_a.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows_a) + "\n"
    )
    return root


class TestClaudeSessionExtractor:
    def test_extracts_only_real_user_prompts(self, quarantine, claude_projects_root):
        from atlas_core.ingestion import (
            ClaudeSessionExtractor,
            IngestionCursor,
            StreamType,
        )

        ext = ClaudeSessionExtractor(
            quarantine=quarantine,
            projects_root=claude_projects_root,
        )
        events = ext.fetch_new_events(
            IngestionCursor.fresh(StreamType.CLAUDE_SESSIONS)
        )
        # snapshot, assistant, and noise-prefix user are all dropped at extract.
        all_claims = []
        for ev in events:
            all_claims.extend(ext.extract_claims_from_event(ev))
        assert len(all_claims) == 1
        assert all_claims[0].object_value == "Build the auth module please"
        assert all_claims[0].lane == "atlas_chat_history"

    def test_cursor_uses_event_uuid(self, quarantine, claude_projects_root):
        from atlas_core.ingestion import ClaudeSessionExtractor

        ext = ClaudeSessionExtractor(
            quarantine=quarantine,
            projects_root=claude_projects_root,
        )
        cursor = ext.cursor_for_event({
            "uuid": "u1",
            "timestamp": "2026-04-25T10:00:00.000Z",
        })
        assert cursor.last_processed_id == "u1"

    def test_handles_list_content_format(self, quarantine, claude_projects_root):
        from atlas_core.ingestion import ClaudeSessionExtractor

        ext = ClaudeSessionExtractor(
            quarantine=quarantine,
            projects_root=claude_projects_root,
        )
        claims = ext.extract_claims_from_event({
            "type": "user",
            "uuid": "u3",
            "sessionId": "sess_b",
            "timestamp": "2026-04-25T11:00:00Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Two-block prompt"},
                    {"type": "text", "text": "second block"},
                ],
            },
        })
        assert len(claims) == 1
        assert "Two-block prompt" in claims[0].object_value


# ─── Fireflies (stub) ────────────────────────────────────────────────────────


class TestFirefliesExtractor:
    def test_raises_when_api_key_missing(self, quarantine, monkeypatch):
        from atlas_core.ingestion import (
            FirefliesExtractor,
            FirefliesNotConfiguredError,
            IngestionCursor,
            StreamType,
        )

        monkeypatch.delenv("FIREFLIES_API_KEY", raising=False)
        ext = FirefliesExtractor(quarantine=quarantine)
        with pytest.raises(FirefliesNotConfiguredError):
            ext.fetch_new_events(IngestionCursor.fresh(StreamType.FIREFLIES))

    def test_returns_empty_when_key_present(self, quarantine, monkeypatch):
        from atlas_core.ingestion import (
            FirefliesExtractor,
            IngestionCursor,
            StreamType,
        )

        monkeypatch.setenv("FIREFLIES_API_KEY", "test-key")
        ext = FirefliesExtractor(quarantine=quarantine)
        # Phase 3 wires the real call; Phase 2 returns [] with key set.
        assert ext.fetch_new_events(
            IngestionCursor.fresh(StreamType.FIREFLIES)
        ) == []


# ─── iMessage ────────────────────────────────────────────────────────────────


@pytest.fixture
def imessage_fake_db(tmp_path):
    """Fixture: a chat.db replica with handle + message tables."""
    db_path = tmp_path / "chat_fake.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE message(
            ROWID INTEGER PRIMARY KEY,
            text TEXT,
            date INTEGER,
            is_from_me INTEGER,
            handle_id INTEGER
        );
        INSERT INTO handle(ROWID, id) VALUES (1, '+15555550100');
        INSERT INTO message(ROWID, text, date, is_from_me, handle_id) VALUES
            (10, 'Hello there', 700000000000000000, 0, 1),
            (11, 'Reply',       700000000600000000, 1, 1);
    """)
    conn.commit()
    conn.close()
    return db_path


class TestImessageExtractor:
    def test_metadata_only_when_thread_not_opted_in(
        self, quarantine, imessage_fake_db, monkeypatch,
    ):
        from atlas_core.ingestion import ImessageExtractor

        monkeypatch.delenv("ATLAS_IMESSAGE_OPT_IN", raising=False)
        ext = ImessageExtractor(
            quarantine=quarantine, db_path=imessage_fake_db,
        )
        claims = ext.extract_claims_from_event({
            "rowid": 10,
            "text": "Hello there",
            "date_apple_epoch": 700000000000000000,
            "is_from_me": 0,
            "chat_identifier": "+15555550100",
        })
        assert claims[0].object_value == "<metadata-only>"
        assert claims[0].predicate == "messaged"

    def test_full_text_when_thread_opted_in(
        self, quarantine, imessage_fake_db, monkeypatch,
    ):
        from atlas_core.ingestion import ImessageExtractor

        monkeypatch.setenv("ATLAS_IMESSAGE_OPT_IN", "+15555550100")
        ext = ImessageExtractor(
            quarantine=quarantine, db_path=imessage_fake_db,
        )
        claims = ext.extract_claims_from_event({
            "rowid": 10,
            "text": "Hello there",
            "date_apple_epoch": 700000000000000000,
            "is_from_me": 0,
            "chat_identifier": "+15555550100",
        })
        assert claims[0].object_value == "Hello there"
        assert claims[0].predicate == "said"

    def test_outgoing_message_subject_is_rich(
        self, quarantine, imessage_fake_db, monkeypatch,
    ):
        from atlas_core.ingestion import ImessageExtractor

        monkeypatch.setenv("ATLAS_IMESSAGE_OPT_IN", "+15555550100")
        ext = ImessageExtractor(
            quarantine=quarantine, db_path=imessage_fake_db,
        )
        claims = ext.extract_claims_from_event({
            "rowid": 11,
            "text": "Reply",
            "date_apple_epoch": 700000000600000000,
            "is_from_me": 1,
            "chat_identifier": "+15555550100",
        })
        assert "People/rich.person" in claims[0].subject_kref

    def test_apple_epoch_conversion(self, quarantine, imessage_fake_db):
        from atlas_core.ingestion import ImessageExtractor

        ext = ImessageExtractor(
            quarantine=quarantine, db_path=imessage_fake_db,
        )
        # 700000000 seconds since 2001-01-01 == 2023-03-09 04:46:40 UTC
        iso = ext._apple_epoch_to_iso(700_000_000)
        assert iso.startswith("2023-")

    def test_missing_db_returns_empty(self, quarantine, tmp_path):
        from atlas_core.ingestion import (
            ImessageExtractor,
            IngestionCursor,
            StreamType,
        )

        ext = ImessageExtractor(
            quarantine=quarantine,
            db_path=tmp_path / "nope.db",
        )
        assert ext.fetch_new_events(
            IngestionCursor.fresh(StreamType.IMESSAGE)
        ) == []
