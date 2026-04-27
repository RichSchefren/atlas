"""LoCoMo runner — token-level F1 over four conversational categories.

LoCoMo's four categories are: factual recall, multi-hop reasoning,
preference inference, and temporal grounding. Atlas's adapter ingests
the conversation history then answers each question; the runner
scores answers via token-level F1 against the gold reference.

The dataset is published research-only; users download separately.

Spec: PHASE-5-AND-BEYOND.md § 2.3
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)


LOCOMO_CATEGORIES: tuple[str, ...] = (
    "factual_recall",
    "multi_hop_reasoning",
    "preference_inference",
    "temporal_grounding",
)


_TOKEN_SPLITTER = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLITTER.split(text.lower()) if t]


def token_f1(answer: str, expected: str) -> float:
    """Token-level F1 — same scoring rule LoCoMo's published harness uses."""
    a_tokens = _tokenize(answer)
    e_tokens = _tokenize(expected)
    if not a_tokens or not e_tokens:
        return 0.0
    a_set = set(a_tokens)
    e_set = set(e_tokens)
    overlap = a_set & e_set
    if not overlap:
        return 0.0
    precision = len(overlap) / len(a_set)
    recall = len(overlap) / len(e_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


class BenchmarkSystem(Protocol):
    name: str
    def reset(self) -> None: ...
    def ingest(self, corpus_dir: Path) -> None: ...
    def query(self, payload: dict[str, Any]) -> Any: ...


@dataclass
class LoCoMoScore:
    system_name: str
    n_questions: int = 0
    f1_sum: float = 0.0
    by_category: dict[str, dict[str, float]] = field(default_factory=dict)
    raw_outcomes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def overall_f1(self) -> float:
        if self.n_questions == 0:
            return 0.0
        return self.f1_sum / self.n_questions

    def per_category_f1(self) -> dict[str, float]:
        return {
            cat: stats["f1_sum"] / stats["count"] if stats["count"] else 0.0
            for cat, stats in self.by_category.items()
        }


def iter_questions(jsonl_path: Path) -> Iterator[dict[str, Any]]:
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


class LoCoMoRunner:
    def __init__(
        self,
        system: BenchmarkSystem,
        questions_jsonl: Path,
        *,
        conversations_corpus_dir: Path | None = None,
    ):
        self.system = system
        self.questions_jsonl = Path(questions_jsonl)
        self.conversations_corpus_dir = conversations_corpus_dir

    def run(self) -> LoCoMoScore:
        score = LoCoMoScore(system_name=self.system.name)

        if not self.questions_jsonl.exists():
            log.warning(
                "LoCoMo JSONL missing at %s — returning zero score",
                self.questions_jsonl,
            )
            return score

        self.system.reset()
        if self.conversations_corpus_dir is not None:
            self.system.ingest(self.conversations_corpus_dir)

        for question in iter_questions(self.questions_jsonl):
            category = question.get("category", "unknown")
            stats = score.by_category.setdefault(
                category, {"count": 0.0, "f1_sum": 0.0},
            )
            stats["count"] += 1
            score.n_questions += 1

            try:
                answer = self.system.query({
                    "question": question.get("question", ""),
                    "scoring": "token_f1",
                    "correct_answer": question.get("answer", ""),
                    "category": category,
                    "conversation_id": question.get("conversation_id", ""),
                })
            except Exception as exc:
                log.warning("System errored on q: %s", exc)
                answer = ""

            f1 = token_f1(str(answer or ""), str(question.get("answer", "")))
            stats["f1_sum"] += f1
            score.f1_sum += f1
            score.raw_outcomes.append({
                "category": category,
                "answer_given": str(answer or ""),
                "answer_expected": question.get("answer", ""),
                "f1": f1,
            })

        return score


def run_locomo_against(
    system: BenchmarkSystem,
    questions_jsonl: Path,
    *,
    conversations_corpus_dir: Path | None = None,
) -> LoCoMoScore:
    return LoCoMoRunner(
        system, questions_jsonl,
        conversations_corpus_dir=conversations_corpus_dir,
    ).run()
