"""Regression test enforcing the proposal-vs-mutation invariant.

The safety guarantee documented in `docs/PROPOSAL_VS_MUTATION.md` is:

    No graph-typed state mutation happens automatically as part of
    Ripple propagation. The cascade modules (`analyze_impact`,
    `reassess`, `contradiction`, `adjudication`, `engine`) are
    read-only with respect to Neo4j — the strings they pass to
    `session.run()` never contain MERGE, CREATE, SET-property,
    or DELETE Cypher statements. Mutation happens only through the
    AGM operators (`atlas_core/revision/agm.py`) or through
    `resolve_adjudication` (which itself calls those operators).

This test enforces the invariant by parsing each cascade module's AST,
finding every `session.run("...")` call, and asserting the query
string contains only read keywords. If a future commit adds a write
without updating the audit, this test fails — at which point either:

  (a) the new write is intentional and `docs/PROPOSAL_VS_MUTATION.md`
      needs to document the new mutation surface, or
  (b) the new write is a bug, and Ripple's safety story is broken.

Either way, CI catches it before merge.

Spec: docs/PROPOSAL_VS_MUTATION.md
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


_READ_ONLY_FILES = [
    "atlas_core/ripple/analyze_impact.py",
    "atlas_core/ripple/reassess.py",
    "atlas_core/ripple/contradiction.py",
    "atlas_core/ripple/adjudication.py",
    "atlas_core/ripple/engine.py",
]
"""These five files are the heart of the cascade. None of the strings
they pass to `session.run()` may issue Cypher writes. If you need to
write to the graph, do it through `atlas_core/revision/agm.py`
(revise / contract / expand) or `atlas_core/ripple/resolver.py`
(which loads queued markdown then delegates to AGM)."""


# Cypher write keywords as whole words (case-insensitive). Matches the
# clause-introducing keywords used in mutation queries.
_WRITE_KEYWORDS_RE = re.compile(
    r"\b(?:MERGE|CREATE|DETACH\s+DELETE|DELETE)\b|\bSET\s+\w+\s*[.=]",
    re.IGNORECASE,
)


def _collect_session_run_strings(source: str) -> list[tuple[int, str]]:
    """Return every string literal passed positionally to `*.run(...)`.

    Picks up `session.run("…")`, `s.run("…")`, `await session.run("…", ...)`,
    plus the multi-line raw form. Returns (line_number, query_text) so
    failure messages can point at the offending line.
    """
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # match `something.run(...)` — Attribute access whose attr is "run"
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "run"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append((node.lineno, first.value))
    return found


@pytest.mark.parametrize("rel_path", _READ_ONLY_FILES)
def test_no_cypher_writes_in_read_only_module(rel_path: str) -> None:
    """Strings passed to `session.run()` in cascade modules must be read-only.

    Parses the file's AST, locates every `session.run("…")` call, and
    flags any query containing MERGE / CREATE / DELETE / SET-property.
    """
    path = _REPO_ROOT / rel_path
    source = path.read_text(encoding="utf-8")
    queries = _collect_session_run_strings(source)
    offenders: list[tuple[int, str]] = []
    for lineno, q in queries:
        if _WRITE_KEYWORDS_RE.search(q):
            # Trim for the failure message
            snippet = q.strip().replace("\n", " ")
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            offenders.append((lineno, snippet))

    assert not offenders, (
        f"{rel_path} passes Cypher write statements to session.run() — "
        f"this breaks the proposal-vs-mutation invariant.\n"
        f"Offending queries:\n"
        + "\n".join(f"  line {ln}: {q}" for ln, q in offenders)
        + "\n\nIf the write is intentional, update "
        "`docs/PROPOSAL_VS_MUTATION.md` to document the new mutation "
        "surface and remove this file from `_READ_ONLY_FILES` in this test."
    )


def test_audit_doc_exists_and_names_invariant() -> None:
    """The audit doc must exist and contain the invariant statement.

    If someone deletes the doc, this test fails — keeping the safety
    guarantee in lock-step with the docs that explain it.
    """
    doc = _REPO_ROOT / "docs" / "PROPOSAL_VS_MUTATION.md"
    assert doc.exists(), "docs/PROPOSAL_VS_MUTATION.md is missing"
    text = doc.read_text(encoding="utf-8")
    assert "No graph-typed state mutation happens automatically" in text, (
        "docs/PROPOSAL_VS_MUTATION.md no longer states the invariant. "
        "If the invariant has changed, update both the doc and the "
        "code that enforces it."
    )
