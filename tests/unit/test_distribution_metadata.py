"""Public distribution metadata must preserve Atlas's import and CLI surfaces."""

from importlib import metadata


def test_public_distribution_name_maps_to_atlas_core() -> None:
    distribution = metadata.distribution("atlas-cognitive-memory")

    assert distribution.metadata["Name"] == "atlas-cognitive-memory"
    assert distribution.version == "0.1.0a1"

    import atlas_core

    assert atlas_core.__version__ == distribution.version


def test_public_distribution_installs_atlas_cli() -> None:
    distribution = metadata.distribution("atlas-cognitive-memory")
    scripts = {
        entry.name: entry.value
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }

    assert scripts["atlas"] == "atlas_core.cli:main"
