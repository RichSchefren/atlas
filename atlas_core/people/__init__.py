"""Atlas People Registry — name canonicalization + tier classification.

Public API:
    from atlas_core.people import resolve, registry

    name, info = resolve("nicole")
    # → ("Nicole Mickevicius", PersonInfo(type="employee", tier=1, ...))

    name, info = resolve("Cloud")
    # → ("Claude", PersonInfo(type="non_human", tier=99, ...))

Callers (the meetings extractor in particular) check `info.type` and
drop the entry if it's `non_human` — Claude, Cloud, "Team", "Someone"
should never enter the belief graph as person entities.
"""

from atlas_core.people.registry import (
    PersonInfo,
    PeopleRegistry,
    registry,
    resolve,
)

__all__ = ["PersonInfo", "PeopleRegistry", "registry", "resolve"]
