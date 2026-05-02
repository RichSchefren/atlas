"""Integration tests for the People Registry."""

from __future__ import annotations

import textwrap
from pathlib import Path

from atlas_core.people.registry import PeopleRegistry


def _write_registry(tmp_path: Path, yaml_content: str) -> Path:
    path = tmp_path / "people.yaml"
    path.write_text(textwrap.dedent(yaml_content), encoding="utf-8")
    return path


def _basic_fixture(tmp_path) -> PeopleRegistry:
    path = _write_registry(tmp_path, """\
        people:
        - canonical_name: Nicole Mickevicius
          aliases: [nicole, "nicole m", "[[nicole]]"]
          type: employee
          tier: 1
        - canonical_name: Tom Hammaker
          aliases: [tom, "tom hammaker", tomhammaker]
          type: employee
          tier: 2
        - canonical_name: Claude
          aliases: [claude, cloud]
          type: non_human
          tier: 99
        - canonical_name: Jay Abraham
          aliases: ["jay abraham"]
          type: external
          tier: 2
        """)
    return PeopleRegistry(registry_path=path)


def test_resolve_alias_to_canonical(tmp_path):
    reg = _basic_fixture(tmp_path)
    name, info = reg.resolve("nicole")
    assert name == "Nicole Mickevicius"
    assert info.type == "employee"
    assert info.tier == 1


def test_resolve_canonical_to_canonical(tmp_path):
    reg = _basic_fixture(tmp_path)
    name, info = reg.resolve("Nicole Mickevicius")
    assert name == "Nicole Mickevicius"


def test_resolve_case_insensitive(tmp_path):
    reg = _basic_fixture(tmp_path)
    assert reg.resolve("NICOLE")[0] == "Nicole Mickevicius"
    assert reg.resolve("Tom")[0] == "Tom Hammaker"
    assert reg.resolve("TOM HAMMAKER")[0] == "Tom Hammaker"


def test_resolve_strips_wikilink_brackets(tmp_path):
    reg = _basic_fixture(tmp_path)
    name, info = reg.resolve("[[nicole]]")
    assert name == "Nicole Mickevicius"


def test_resolve_strips_parenthetical_handle(tmp_path):
    reg = _basic_fixture(tmp_path)
    name, info = reg.resolve("Tom (tomhammaker)")
    assert name == "Tom Hammaker"


def test_resolve_unknown_returns_none(tmp_path):
    reg = _basic_fixture(tmp_path)
    assert reg.resolve("Some Stranger") is None
    assert reg.resolve("") is None
    assert reg.resolve(None) is None


def test_non_human_classification(tmp_path):
    reg = _basic_fixture(tmp_path)
    name, info = reg.resolve("cloud")
    assert name == "Claude"
    assert info.type == "non_human"
    assert info.is_human is False
    assert reg.is_non_human("claude") is True
    assert reg.is_non_human("nicole") is False


def test_external_tier(tmp_path):
    reg = _basic_fixture(tmp_path)
    name, info = reg.resolve("Jay Abraham")
    assert info.type == "external"
    assert info.tier == 2


def test_packaged_registry_loads_without_errors():
    """The shipped people.yaml is valid YAML and parseable."""
    reg = PeopleRegistry()  # uses packaged default
    canonical = reg.all_canonical()
    assert "Rich Schefren" in canonical
    assert "Nicole Mickevicius" in canonical
    # Non-human entries must be flagged correctly
    name, info = reg.resolve("cloud")
    assert info.type == "non_human"


def test_packaged_registry_inner_circle_tiers():
    """Sanity-check that Rich's stated inner circle landed at tier 1."""
    reg = PeopleRegistry()
    inner = ["Nicole Mickevicius", "Ashley Shaw", "Jessica", "Harry Lockwood"]
    for name in inner:
        result = reg.resolve(name)
        assert result is not None, f"missing canonical: {name}"
        assert result[1].tier == 1, f"expected tier 1 for {name}"


def test_packaged_registry_second_circle():
    reg = PeopleRegistry()
    for name in ["Ben Thole", "Tom Hammaker"]:
        assert reg.resolve(name)[1].tier == 2
