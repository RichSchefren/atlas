"""Unit tests for the entity resolution cascade.

Spec: PHASE-5-AND-BEYOND.md § 1.3
"""

import pytest


# ─── AliasDictionary ────────────────────────────────────────────────────────


class TestAliasDictionary:
    def test_empty_dictionary_lookup_returns_none(self, tmp_path):
        from atlas_core.resolution import AliasDictionary
        d = AliasDictionary(path=tmp_path / "aliases.yaml")
        assert d.lookup("Sarah") is None

    def test_load_from_yaml(self, tmp_path):
        from atlas_core.resolution import AliasDictionary
        path = tmp_path / "aliases.yaml"
        path.write_text(
            "aliases:\n"
            "  kref://test/People/sarah_chen.person:\n"
            "    - Sarah\n"
            "    - Sarah Chen\n"
            "    - '@sarah'\n"
        )
        d = AliasDictionary(path=path)
        match = d.lookup("Sarah")
        assert match is not None
        assert match.kref == "kref://test/People/sarah_chen.person"
        assert match.confidence == 1.0
        assert match.source == "alias_dictionary"

    def test_lookup_is_case_insensitive(self, tmp_path):
        from atlas_core.resolution import AliasDictionary
        path = tmp_path / "aliases.yaml"
        path.write_text(
            "aliases:\n"
            "  kref://test/x:\n"
            "    - Sarah\n"
        )
        d = AliasDictionary(path=path)
        assert d.lookup("sarah") is not None
        assert d.lookup("SARAH") is not None
        assert d.lookup("  Sarah  ") is not None  # whitespace trimmed

    def test_add_and_save_round_trip(self, tmp_path):
        from atlas_core.resolution import AliasDictionary
        path = tmp_path / "aliases.yaml"
        d = AliasDictionary(path=path)
        d.add("kref://test/x", "Foo")
        d.add("kref://test/x", "F.X.")
        d.save()

        # Re-load
        d2 = AliasDictionary(path=path)
        assert d2.lookup("Foo").kref == "kref://test/x"
        assert d2.lookup("F.X.").kref == "kref://test/x"
        assert sorted(d2.all_surfaces_for("kref://test/x")) == ["F.X.", "Foo"]

    def test_add_is_idempotent(self, tmp_path):
        from atlas_core.resolution import AliasDictionary
        d = AliasDictionary(path=tmp_path / "aliases.yaml")
        d.add("kref://x", "Foo")
        d.add("kref://x", "Foo")
        d.add("kref://x", "Foo")
        assert d.all_surfaces_for("kref://x") == ["Foo"]

    def test_known_krefs(self, tmp_path):
        from atlas_core.resolution import AliasDictionary
        d = AliasDictionary(path=tmp_path / "aliases.yaml")
        d.add("kref://a", "A")
        d.add("kref://b", "B")
        assert sorted(d.known_krefs()) == ["kref://a", "kref://b"]


# ─── FuzzyEntityMatcher ─────────────────────────────────────────────────────


class TestFuzzyEntityMatcher:
    @pytest.fixture
    def aliases(self, tmp_path):
        from atlas_core.resolution import AliasDictionary
        d = AliasDictionary(path=tmp_path / "aliases.yaml")
        d.add("kref://test/People/sarah_chen.person", "Sarah Chen")
        d.add("kref://test/People/sarah_chen.person", "Sarah")
        d.add("kref://test/People/marcus_rivera.person", "Marcus Rivera")
        d.add("kref://test/Programs/origins.program", "Origins")
        return d

    def test_typo_resolves(self, aliases):
        from atlas_core.resolution import FuzzyEntityMatcher
        m = FuzzyEntityMatcher(aliases)
        # "Sarah Cen" missing 'h' — should fuzz-hit Sarah Chen
        match = m.lookup("Sarah Cen")
        assert match is not None
        assert match.kref == "kref://test/People/sarah_chen.person"
        assert match.confidence > 0.85

    def test_completely_different_returns_none(self, aliases):
        from atlas_core.resolution import FuzzyEntityMatcher
        m = FuzzyEntityMatcher(aliases)
        assert m.lookup("Quetzalcoatl") is None

    def test_empty_input_returns_none(self, aliases):
        from atlas_core.resolution import FuzzyEntityMatcher
        m = FuzzyEntityMatcher(aliases)
        assert m.lookup("") is None
        assert m.lookup("   ") is None

    def test_empty_alias_pool_returns_none(self, tmp_path):
        from atlas_core.resolution import AliasDictionary, FuzzyEntityMatcher
        d = AliasDictionary(path=tmp_path / "empty.yaml")
        m = FuzzyEntityMatcher(d)
        assert m.lookup("Sarah") is None


# ─── EntityResolver cascade ─────────────────────────────────────────────────


class TestEntityResolverCascade:
    @pytest.fixture
    def resolver(self, tmp_path):
        from atlas_core.resolution import AliasDictionary, EntityResolver
        d = AliasDictionary(path=tmp_path / "aliases.yaml")
        d.add("kref://test/People/sarah_chen.person", "Sarah Chen")
        d.add("kref://test/People/sarah_chen.person", "Sarah")
        d.add("kref://test/People/marcus_rivera.person", "Marcus Rivera")
        # LLM fallback disabled — we don't want network calls in unit tests.
        return EntityResolver(aliases=d, enable_llm_fallback=False)

    async def test_exact_alias_returns_immediate(self, resolver):
        from atlas_core.resolution import ResolvedEntity
        result = await resolver.resolve("Sarah", kind="Person")
        assert isinstance(result, ResolvedEntity)
        assert result.source == "alias_dictionary"
        assert result.kref == "kref://test/People/sarah_chen.person"
        assert result.confidence == 1.0

    async def test_fuzzy_promotes_alias(self, resolver):
        from atlas_core.resolution import ResolvedEntity
        result = await resolver.resolve("Sarah Cen", kind="Person")
        assert isinstance(result, ResolvedEntity)
        assert result.source == "fuzzy"
        # Subsequent exact lookup of the typo'd surface should now hit alias
        result2 = await resolver.resolve("Sarah Cen", kind="Person")
        assert isinstance(result2, ResolvedEntity)
        assert result2.source == "alias_dictionary"

    async def test_no_match_returns_nomatch(self, resolver):
        from atlas_core.resolution import NoMatch
        result = await resolver.resolve("Quetzalcoatl", kind="Person")
        assert isinstance(result, NoMatch)
        assert result.should_create_new is True

    async def test_empty_surface_returns_nomatch(self, resolver):
        from atlas_core.resolution import NoMatch
        result = await resolver.resolve("", kind="Person")
        assert isinstance(result, NoMatch)
        assert result.should_create_new is False

    async def test_resolver_uses_kind_filter_in_llm_path(self, tmp_path):
        # Without LLM enabled, we just verify the API accepts kind
        from atlas_core.resolution import (
            AliasDictionary, EntityResolver, NoMatch,
        )
        d = AliasDictionary(path=tmp_path / "aliases.yaml")
        d.add("kref://x/People/foo.person", "Foo")
        r = EntityResolver(aliases=d, enable_llm_fallback=False)
        result = await r.resolve("Bar", kind="Program")
        assert isinstance(result, NoMatch)


# ─── ResolutionCache ────────────────────────────────────────────────────────


class TestResolutionCache:
    def test_get_miss_returns_none(self, tmp_path):
        from atlas_core.resolution import ResolutionCache
        c = ResolutionCache(path=tmp_path / "cache.sqlite")
        assert c.get("nonexistent_key") is None

    def test_put_then_get(self, tmp_path):
        from atlas_core.resolution import ResolutionCache
        c = ResolutionCache(path=tmp_path / "cache.sqlite")
        c.put("k1", "Sarah", {"kref": "kref://test/x", "confidence": 0.9})
        cached = c.get("k1")
        assert cached["kref"] == "kref://test/x"
        assert cached["confidence"] == 0.9

    def test_put_overrides(self, tmp_path):
        from atlas_core.resolution import ResolutionCache
        c = ResolutionCache(path=tmp_path / "cache.sqlite")
        c.put("k1", "Sarah", {"kref": "kref://a"})
        c.put("k1", "Sarah", {"kref": "kref://b"})
        assert c.get("k1")["kref"] == "kref://b"
