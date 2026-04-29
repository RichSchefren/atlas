"""Integration tests for the filesystem-based Meetings extractor."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from atlas_core.ingestion.meetings import (
    MeetingsExtractor,
    parse_action_item,
    parse_frontmatter,
    parse_standup_action_items,
)
from atlas_core.trust.quarantine import QuarantineStore

# ─── Pure-function tests ────────────────────────────────────────────────────


def test_parse_frontmatter_extracts_yaml_dict_and_body():
    text = textwrap.dedent("""\
        ---
        meeting: ZenithPro Copy Clinic
        date: 2026-03-19
        action_items:
          - Sam: Run mimetic research
          - Tom: Connect Notebook LM via MCP
        ---
        # Body content here
        Stuff.
        """)
    fm, body = parse_frontmatter(text)
    assert fm["meeting"] == "ZenithPro Copy Clinic"
    assert len(fm["action_items"]) == 2
    assert "Body content here" in body


def test_parse_frontmatter_no_frontmatter_returns_empty():
    fm, body = parse_frontmatter("# Just a heading\nNo frontmatter.")
    assert fm == {}
    assert "Just a heading" in body


def test_parse_frontmatter_malformed_yaml_warns_returns_empty(caplog):
    bad = "---\n[unclosed bracket\n---\n# body\n"
    fm, body = parse_frontmatter(bad)
    assert fm == {}
    assert "body" in body


def test_parse_action_item_with_person_prefix():
    person, what = parse_action_item("Sam: Run mimetic research")
    assert person == "Sam"
    assert what == "Run mimetic research"


def test_parse_action_item_no_colon_returns_none_person():
    person, what = parse_action_item("Schedule the team off-site")
    assert person is None
    assert what == "Schedule the team off-site"


def test_parse_action_item_long_prefix_treated_as_no_person():
    """Heuristic: a prefix that's a full sentence isn't a person name."""
    person, what = parse_action_item(
        "This is a very long sentence with a colon: that should not be parsed"
    )
    assert person is None


def test_parse_standup_action_items_pulls_per_person_bullets():
    body = textwrap.dedent("""\
        ## Open Action Items

        ### Rich
        - Review E3 doc and decide on tier structure *(P003)*
        - Define next concrete step for SOW *(P001)*

        ### Nicole
        - No open ClickUp tasks surfaced — confirm next priorities

        ### Ben / Tom / Others
        - **Ben** — confirm receipt and next action

        ## Today's Schedule
        Stuff after.
        """)
    items = parse_standup_action_items(body)
    persons = [p for p, _ in items]
    actions = [a for _, a in items]
    assert "Rich" in persons
    assert any("E3" in a for a in actions)
    # Footnote *(P003)* must be stripped
    assert all("*(" not in a for a in actions)
    # The "no open" line must be filtered
    assert not any("No open" in a or "no open" in a for a in actions)
    # The catch-all "Ben / Tom / Others" header must NOT be treated as a person
    assert "Ben / Tom / Others" not in persons


def test_parse_standup_action_items_no_section_returns_empty():
    assert parse_standup_action_items("# Just a doc with no Open Action Items") == []


# ─── End-to-end extractor tests ─────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path) -> QuarantineStore:
    return QuarantineStore(db_path=tmp_path / "candidates.db")


@pytest.fixture()
def meetings_root(tmp_path) -> Path:
    root = tmp_path / "Meetings"
    root.mkdir()
    return root


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_extractor_emits_lcl_processed_claims(store, meetings_root):
    _write(meetings_root / "ZenithPro-2026-03-19.md", """\
        ---
        meeting: ZenithPro Copy Clinic
        date: 2026-03-19
        host: tomhammaker
        rich_present: false
        lcl_processed: true
        action_items:
          - Sam: Run mimetic research
          - Tom: Connect Notebook LM via MCP
        decisions:
          - Use Open Brain over Pinecone for knowledge retrieval
          - Keep pre-onboarding video page simple
        people:
          - Tom (tomhammaker)
          - Sam
          - Rich Schefren
        ---
        Body content.
        """)

    extractor = MeetingsExtractor(quarantine=store, meetings_root=meetings_root)
    events = extractor.fetch_new_events(extractor.load_cursor())
    assert len(events) == 1

    claims = extractor.extract_claims_from_event(events[0])
    # 2 action items + 2 decisions + 3 people = 7 claims
    assert len(claims) == 7

    by_predicate = {}
    for c in claims:
        by_predicate.setdefault(c.predicate, []).append(c)

    assert len(by_predicate["commitment.action_item"]) == 2
    assert len(by_predicate["decision.outcome"]) == 2
    assert len(by_predicate["episode.attended_meeting"]) == 3

    # Confidence should be the LCL tier
    assert all(c.confidence == 0.85 for c in claims)
    # Lane is the meetings lane (NOT atlas_observational)
    assert all(c.lane == "atlas_meeting" for c in claims)
    # Person names with parenthetical handles are stripped
    person_subjects = [c.subject_kref for c in by_predicate["episode.attended_meeting"]]
    assert any("/tom.person" in s for s in person_subjects)
    assert not any("(tomhammaker)" in s for s in person_subjects)


def test_extractor_emits_standup_action_items(store, meetings_root):
    _write(meetings_root / "Standup-Brief-2026-04-22.md", """\
        # Morning Standup Pre-Brief
        ## Wednesday, April 22, 2026

        ## Open Action Items

        ### Rich
        - Review E3 doc and decide on theme calendar *(P003)*

        ### Ashley
        - Confirm next priorities, particularly ZMOS post-close follow-up

        ## Today's Schedule
        """)
    extractor = MeetingsExtractor(quarantine=store, meetings_root=meetings_root)
    events = extractor.fetch_new_events(extractor.load_cursor())
    claims = extractor.extract_claims_from_event(events[0])

    assert len(claims) == 2
    assert all(c.confidence == 0.70 for c in claims)
    assert all(c.predicate == "commitment.action_item" for c in claims)
    assert all(c.lane == "atlas_meeting" for c in claims)
    values = [c.object_value for c in claims]
    assert any("Rich:" in v and "E3" in v for v in values)
    assert any("Ashley:" in v for v in values)


def test_extractor_skips_files_without_recognized_structure(store, meetings_root):
    _write(meetings_root / "random.md", "# Just a heading\nNot a meeting brief.")
    extractor = MeetingsExtractor(quarantine=store, meetings_root=meetings_root)
    events = extractor.fetch_new_events(extractor.load_cursor())
    claims = extractor.extract_claims_from_event(events[0])
    assert claims == []


def test_extractor_cursor_filters_old_files(store, meetings_root):
    """Files with mtime older than the cursor should be skipped."""
    _write(meetings_root / "newer.md", """\
        ---
        lcl_processed: true
        action_items:
          - Tom: Do thing
        ---
        """)
    old = _write(meetings_root / "older.md", """\
        ---
        lcl_processed: true
        action_items:
          - Tom: Old thing
        ---
        """)
    # Backdate the "older" file to 1990
    import os
    os.utime(old, (631152000, 631152000))  # 1990-01-01

    extractor = MeetingsExtractor(quarantine=store, meetings_root=meetings_root)
    # Cursor pointing at 2000-01-01 — should skip the 1990 file but include 2026
    cursor = extractor.load_cursor()
    cursor.last_processed_at = "2000-01-01T00:00:00+00:00"

    events = extractor.fetch_new_events(cursor)
    paths = [e["path"].name for e in events]
    assert "newer.md" in paths
    assert "older.md" not in paths


def test_extractor_run_once_writes_to_quarantine(store, meetings_root, tmp_path):
    """End-to-end: run_once() must persist claims into the candidate store."""
    _write(meetings_root / "test-meeting.md", """\
        ---
        lcl_processed: true
        action_items:
          - Tom: Connect MCP
        decisions:
          - Use Open Brain
        people:
          - Tom
        ---
        """)
    from atlas_core.ingestion.base import StreamConfig
    config = StreamConfig(cursor_dir=tmp_path / "state")
    extractor = MeetingsExtractor(
        quarantine=store, meetings_root=meetings_root, config=config,
    )
    result = extractor.run_once()
    assert result.events_processed == 1
    assert result.claims_extracted == 3
    assert result.succeeded

    # Cursor advanced
    cursor = extractor.load_cursor()
    assert cursor.last_processed_at != "1970-01-01T00:00:00+00:00"

    # Re-run — should be a no-op
    result2 = extractor.run_once()
    assert result2.events_processed == 0


def test_extractor_handles_missing_root_gracefully(store, tmp_path):
    extractor = MeetingsExtractor(
        quarantine=store, meetings_root=tmp_path / "does-not-exist",
    )
    events = extractor.fetch_new_events(extractor.load_cursor())
    assert events == []
