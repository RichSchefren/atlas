"""Kref URI parser/validator — kref://project/space[/sub]/item.kind?r=N&a=artifact

Atlas adopts Kumiho's kref:// URI scheme (arxiv:2603.17244, Section 6.3) for
universal addressability. Every revision in Atlas's graph has a dereferenceable
URI; tag pointers (e.g., ?r=current) resolve at query time to the active revision.

Spec lock: Atlas uses Kumiho's URI format verbatim for SDK drop-in compatibility.
The only Atlas extension is the canonical project="Atlas" namespace; users
override via configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


KREF_PATTERN = re.compile(
    r"^kref://"
    r"(?P<project>[A-Za-z0-9_-]+)"
    r"/(?P<space>[A-Za-z0-9_/-]+?)"
    r"/(?P<item>[A-Za-z0-9_-]+)"
    r"\.(?P<kind>[A-Za-z0-9_]+)"
    r"(?:\?(?P<query>[^#]*))?"
    r"$"
)


class KrefParseError(ValueError):
    """Raised when a string cannot be parsed as a valid kref:// URI."""


@dataclass(frozen=True)
class Kref:
    """Parsed kref:// URI.

    Examples:
        kref://Atlas/People/ashley_shaw.person
        kref://Atlas/StrategicBeliefs/zenith_pricing_floor.belief?r=3
        kref://Atlas/Decisions/q3_repricing.decision?r=current&a=meeting_transcript
    """

    project: str
    space: str
    item: str
    kind: str
    revision: Optional[str] = None  # 'current', 'initial', 'latest', or numeric '3'
    artifact: Optional[str] = None

    @classmethod
    def parse(cls, uri: str) -> Kref:
        """Parse a kref:// URI string. Raises KrefParseError on malformed input."""
        if not isinstance(uri, str):
            raise KrefParseError(f"Expected str, got {type(uri).__name__}")

        match = KREF_PATTERN.match(uri.strip())
        if not match:
            raise KrefParseError(f"Malformed kref URI: {uri!r}")

        groups = match.groupdict()
        revision = None
        artifact = None

        if groups.get("query"):
            for pair in groups["query"].split("&"):
                if "=" not in pair:
                    raise KrefParseError(f"Malformed query parameter in {uri!r}: {pair!r}")
                key, value = pair.split("=", 1)
                if key == "r":
                    revision = value
                elif key == "a":
                    artifact = value
                else:
                    raise KrefParseError(
                        f"Unknown query parameter {key!r} in {uri!r}. "
                        f"Allowed: 'r' (revision), 'a' (artifact)"
                    )

        return cls(
            project=groups["project"],
            space=groups["space"],
            item=groups["item"],
            kind=groups["kind"],
            revision=revision,
            artifact=artifact,
        )

    def to_string(self) -> str:
        """Reconstruct the canonical kref:// URI string."""
        base = f"kref://{self.project}/{self.space}/{self.item}.{self.kind}"
        params = []
        if self.revision is not None:
            params.append(f"r={self.revision}")
        if self.artifact is not None:
            params.append(f"a={self.artifact}")
        if params:
            base += "?" + "&".join(params)
        return base

    def __str__(self) -> str:
        return self.to_string()

    def root_kref(self) -> Kref:
        """Return the kref of the root item (no revision/artifact qualifiers).

        Used to identify the immutable lineage anchor — the item across all its
        revisions.
        """
        if self.revision is None and self.artifact is None:
            return self
        return Kref(
            project=self.project,
            space=self.space,
            item=self.item,
            kind=self.kind,
        )

    def with_revision(self, revision: str) -> Kref:
        """Return a new Kref pointing at the given revision tag/number."""
        return Kref(
            project=self.project,
            space=self.space,
            item=self.item,
            kind=self.kind,
            revision=revision,
            artifact=self.artifact,
        )
