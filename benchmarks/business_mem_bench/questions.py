"""BusinessMemBench question schema + loader.

Each category writes JSONL files with the shapes spec'd in 08 §3. This
module is the canonical reader — load_questions() yields validated
Question instances regardless of category-specific extra fields.

Spec: 08 - BusinessMemBench Design.md § 3
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator


class Category(str, Enum):
    """The 7 BusinessMemBench categories."""

    PROPAGATION = "propagation"
    CONTRADICTION = "contradiction"
    LINEAGE = "lineage"
    CROSS_STREAM = "cross_stream"
    HISTORICAL = "historical"
    PROVENANCE = "provenance"
    FORGETFULNESS = "forgetfulness"


# Per-category question count target (sums to 1,000).
CATEGORIES: dict[Category, int] = {
    Category.PROPAGATION: 200,
    Category.CONTRADICTION: 150,
    Category.LINEAGE: 150,
    Category.CROSS_STREAM: 150,
    Category.HISTORICAL: 150,
    Category.PROVENANCE: 100,
    Category.FORGETFULNESS: 100,
}


@dataclass
class Question:
    """One BusinessMemBench question.

    Category-specific fields land in `payload`. The harness picks the
    right scorer based on `scoring_method`.
    """

    id: str
    category: Category
    question: str
    scoring_method: str
    payload: dict[str, Any] = field(default_factory=dict)
    setup_events: list[dict[str, Any]] = field(default_factory=list)
    is_human_authored: bool = False  # True for the 200-question gold subset

    @classmethod
    def from_dict(cls, data: dict[str, Any], category: Category) -> Question:
        # `question` text is also kept inside payload so handlers that need
        # to regex out parameters (e.g., historical date extraction) can
        # without the harness having to pass the Question object separately.
        payload = {
            k: v for k, v in data.items()
            if k not in {"id", "scoring", "setup_events"}
        }
        return cls(
            id=data["id"],
            category=category,
            question=data["question"],
            scoring_method=data.get("scoring", "exact_match"),
            setup_events=data.get("setup_events", []),
            payload=payload,
            is_human_authored=data.get("is_human_authored", False),
        )


def load_questions(
    gold_dir: Path,
    *,
    only: list[Category] | None = None,
) -> Iterator[Question]:
    """Yield questions from gold/<category>.jsonl files.

    `only` filters by category; default is all 7. Missing JSONL files
    are skipped silently (categories may be authored at different rates).
    """
    target_categories = only or list(CATEGORIES.keys())
    for cat in target_categories:
        path = gold_dir / f"{cat.value}.jsonl"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                # Skip placeholder rows in human-authored gold files
                # (the headers carry _template_only=true so authors see
                # the schema without those rows scoring as actual q's)
                if data.get("_template_only"):
                    continue
                yield Question.from_dict(data, cat)
