"""Smoke tests for `docs/WHY_VECTOR_IS_NOT_ENOUGH.md`.

The doc is launch-critical (linked from the README's "What Atlas is not"
section). These tests guard against:

  - the file getting deleted in a doc rewrite
  - the worked example losing its key concrete details (the price
    numbers and the propagation outcome)
  - the mermaid diagram getting truncated or syntactically broken

If a contributor wants to rewrite the doc, the tests should still pass
as long as the substance survives — they don't pin specific paragraphs.

Spec: docs/LAUNCH_BACKLOG.md → P2 "Why vector memory is not enough" page.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "docs" / "WHY_VECTOR_IS_NOT_ENOUGH.md"


def test_doc_exists() -> None:
    assert _DOC.exists(), "docs/WHY_VECTOR_IS_NOT_ENOUGH.md is missing"


def test_doc_keeps_concrete_worked_example() -> None:
    """The example is what makes the doc not generic. If a rewrite drops
    the specific price + propagation outcome, it loses its punch."""
    text = _DOC.read_text(encoding="utf-8")
    assert "$2,995" in text and "$3,495" in text, (
        "Worked example lost the concrete price numbers"
    )
    assert "DEPENDS_ON" in text, (
        "Worked example lost the typed-edge mention"
    )
    # The propagation outcome — confidence drops or proposal queued —
    # is the punchline.
    assert (
        "0.88" in text and "0.77" in text
    ), "Worked example lost the confidence drop numbers"


def test_doc_has_balanced_mermaid_block() -> None:
    """The diagram must be inside a ``` ```mermaid fence with both ends
    present and the subgraph keyword paired with `end`."""
    text = _DOC.read_text(encoding="utf-8")
    assert "```mermaid" in text, "mermaid fenced block missing"
    # Extract the mermaid block
    m = re.search(r"```mermaid\n(.*?)```", text, flags=re.DOTALL)
    assert m, "mermaid block found but not properly fenced"
    block = m.group(1)
    # Each `subgraph` opens with the keyword and closes with `end` on
    # its own line. Count both — they must match.
    n_open = len(re.findall(r"^\s*subgraph\b", block, re.MULTILINE))
    n_end = len(re.findall(r"^\s*end\s*$", block, re.MULTILINE))
    assert n_open == n_end, (
        f"mermaid `subgraph` blocks unbalanced: "
        f"{n_open} opens vs {n_end} ends"
    )


def test_readme_links_to_the_doc() -> None:
    """The README's "What Atlas is not" section should point readers
    at the worked example. If the link drops, the doc is orphaned."""
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/WHY_VECTOR_IS_NOT_ENOUGH.md" in readme, (
        "README no longer links to docs/WHY_VECTOR_IS_NOT_ENOUGH.md"
    )
