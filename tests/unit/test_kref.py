"""Unit tests for Atlas's kref:// URI parser. Spec lock from Kumiho paper Section 6.3."""

import pytest

from atlas_core.revision.uri import Kref, KrefParseError


class TestKrefParse:
    def test_minimal_kref(self):
        k = Kref.parse("kref://Atlas/People/ashley_shaw.person")
        assert k.project == "Atlas"
        assert k.space == "People"
        assert k.item == "ashley_shaw"
        assert k.kind == "person"
        assert k.revision is None
        assert k.artifact is None

    def test_kref_with_revision_number(self):
        k = Kref.parse("kref://Atlas/StrategicBeliefs/zenith_pricing.belief?r=3")
        assert k.revision == "3"
        assert k.artifact is None

    def test_kref_with_named_revision(self):
        k = Kref.parse("kref://Atlas/Decisions/q3_repricing.decision?r=current")
        assert k.revision == "current"

    def test_kref_with_initial_tag(self):
        k = Kref.parse("kref://Atlas/Decisions/q3_repricing.decision?r=initial")
        assert k.revision == "initial"

    def test_kref_with_artifact(self):
        k = Kref.parse(
            "kref://Atlas/Meetings/2026-04-24.meeting?a=transcript"
        )
        assert k.artifact == "transcript"

    def test_kref_with_revision_and_artifact(self):
        k = Kref.parse(
            "kref://Atlas/Decisions/q3_repricing.decision?r=current&a=meeting_transcript"
        )
        assert k.revision == "current"
        assert k.artifact == "meeting_transcript"

    def test_kref_with_nested_space(self):
        k = Kref.parse("kref://Atlas/People/team/ashley.person")
        assert k.space == "People/team"
        assert k.item == "ashley"

    def test_kref_strips_whitespace(self):
        k = Kref.parse("  kref://Atlas/People/ashley.person  ")
        assert k.project == "Atlas"


class TestKrefParseErrors:
    def test_non_string_raises(self):
        with pytest.raises(KrefParseError, match="Expected str"):
            Kref.parse(123)

    def test_missing_scheme(self):
        with pytest.raises(KrefParseError, match="Malformed kref URI"):
            Kref.parse("Atlas/People/ashley.person")

    def test_wrong_scheme(self):
        with pytest.raises(KrefParseError, match="Malformed kref URI"):
            Kref.parse("https://Atlas/People/ashley.person")

    def test_missing_kind(self):
        with pytest.raises(KrefParseError, match="Malformed kref URI"):
            Kref.parse("kref://Atlas/People/ashley")

    def test_unknown_query_param(self):
        with pytest.raises(KrefParseError, match="Unknown query parameter"):
            Kref.parse("kref://Atlas/People/ashley.person?x=42")

    def test_malformed_query_param(self):
        with pytest.raises(KrefParseError, match="Malformed query parameter"):
            Kref.parse("kref://Atlas/People/ashley.person?r")


class TestKrefRoundtrip:
    """Parse → to_string roundtrip should be identity for canonical URIs."""

    @pytest.mark.parametrize("uri", [
        "kref://Atlas/People/ashley_shaw.person",
        "kref://Atlas/StrategicBeliefs/zenith_pricing.belief?r=3",
        "kref://Atlas/Decisions/q3_repricing.decision?r=current",
        "kref://Atlas/Meetings/2026-04-24.meeting?a=transcript",
        "kref://Atlas/Decisions/q3_repricing.decision?r=current&a=transcript",
        "kref://Atlas/People/team/ashley.person",
    ])
    def test_roundtrip(self, uri):
        assert Kref.parse(uri).to_string() == uri

    def test_str_returns_canonical(self):
        k = Kref.parse("kref://Atlas/People/ashley_shaw.person?r=5")
        assert str(k) == "kref://Atlas/People/ashley_shaw.person?r=5"


class TestKrefHelpers:
    def test_root_kref_strips_qualifiers(self):
        k = Kref.parse("kref://Atlas/Decisions/q3.decision?r=3&a=transcript")
        root = k.root_kref()
        assert root.revision is None
        assert root.artifact is None
        assert root.to_string() == "kref://Atlas/Decisions/q3.decision"

    def test_root_kref_idempotent(self):
        k = Kref.parse("kref://Atlas/People/ashley.person")
        assert k.root_kref() is k or k.root_kref() == k

    def test_with_revision_replaces(self):
        k = Kref.parse("kref://Atlas/Decisions/q3.decision?r=initial")
        k2 = k.with_revision("current")
        assert k2.revision == "current"
        assert k2.to_string() == "kref://Atlas/Decisions/q3.decision?r=current"

    def test_with_revision_preserves_artifact(self):
        k = Kref.parse("kref://Atlas/Meetings/m1.meeting?r=initial&a=audio")
        k2 = k.with_revision("3")
        assert k2.revision == "3"
        assert k2.artifact == "audio"


class TestKrefImmutability:
    def test_kref_is_frozen(self):
        k = Kref.parse("kref://Atlas/People/ashley.person")
        with pytest.raises(Exception):
            k.project = "Other"

    def test_kref_hashable(self):
        k1 = Kref.parse("kref://Atlas/People/ashley.person")
        k2 = Kref.parse("kref://Atlas/People/ashley.person")
        assert hash(k1) == hash(k2)
        # Test set membership
        assert k1 in {k2}
