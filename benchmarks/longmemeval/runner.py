"""LongMemEval-S runner — 500 questions over multi-session chat history.

The published LongMemEval-S benchmark ships as a JSONL of question
records. Atlas's runner ingests the chat history into the system
under test, then asks each question and scores the answer using the
published exact-match scoring rule (case-insensitive trim).

The runner does not bundle the LongMemEval dataset (license is
research-use; users download via `download_longmemeval.sh`).

Spec: PHASE-5-AND-BEYOND.md § 2.2
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol


log = logging.getLogger(__name__)


# Per the LongMemEval paper, the public release ships with five
# question types: single-session-user, single-session-assistant,
# single-session-preference, temporal-reasoning, knowledge-update.
DEFAULT_QUESTION_TYPES: tuple[str, ...] = (
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "temporal-reasoning",
    "knowledge-update",
)


class BenchmarkSystem(Protocol):
    """Minimum protocol the runner needs from any system under test.

    Identical to the BMB protocol, so the same adapter implementations
    work for both benchmarks.
    """

    name: str
    def reset(self) -> None: ...
    def ingest(self, corpus_dir: Path) -> None: ...
    def query(self, payload: dict[str, Any]) -> Any: ...


@dataclass
class LongMemEvalScore:
    """Aggregated score across all answered questions."""

    system_name: str
    n_questions: int = 0
    n_correct: int = 0
    by_question_type: dict[str, dict[str, int]] = field(default_factory=dict)
    raw_outcomes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        if self.n_questions == 0:
            return 0.0
        return self.n_correct / self.n_questions

    def per_type_accuracy(self) -> dict[str, float]:
        return {
            qt: stats["correct"] / stats["total"] if stats["total"] else 0.0
            for qt, stats in self.by_question_type.items()
        }


def iter_questions(jsonl_path: Path) -> Iterator[dict[str, Any]]:
    """Yield question dicts from the LongMemEval JSONL release.

    Each row is expected to have at minimum:
      {"question": str, "answer": str, "question_type": str,
       "history": list[{"role": "user|assistant", "content": str}]}
    """
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


class LongMemEvalRunner:
    """Drives one LongMemEval-S evaluation against any BenchmarkSystem."""

    def __init__(
        self,
        system: BenchmarkSystem,
        questions_jsonl: Path,
        *,
        history_corpus_dir: Path | None = None,
    ):
        self.system = system
        self.questions_jsonl = Path(questions_jsonl)
        self.history_corpus_dir = history_corpus_dir

    def run(self) -> LongMemEvalScore:
        """Reset, ingest, iterate questions, score."""
        score = LongMemEvalScore(system_name=self.system.name)

        if not self.questions_jsonl.exists():
            log.warning(
                "LongMemEval JSONL missing at %s — returning zero score",
                self.questions_jsonl,
            )
            return score

        self.system.reset()
        if self.history_corpus_dir is not None:
            self.system.ingest(self.history_corpus_dir)

        for question in iter_questions(self.questions_jsonl):
            qtype = question.get("question_type", "unknown")
            stats = score.by_question_type.setdefault(
                qtype, {"total": 0, "correct": 0},
            )
            stats["total"] += 1
            score.n_questions += 1

            try:
                answer = self.system.query({
                    "question": question.get("question", ""),
                    "scoring": "exact_match",
                    "correct_answer": question.get("answer", ""),
                    "question_type": qtype,
                    "history": question.get("history", []),
                })
            except Exception as exc:
                log.warning("System errored on q: %s", exc)
                answer = None

            is_correct = _exact_match(
                str(answer or ""), str(question.get("answer", "")),
            )
            if is_correct:
                stats["correct"] += 1
                score.n_correct += 1
            score.raw_outcomes.append({
                "question_type": qtype,
                "answer_given": str(answer or ""),
                "answer_expected": question.get("answer", ""),
                "correct": is_correct,
            })

        return score


def _exact_match(answer: str, expected: str) -> bool:
    return answer.strip().lower() == expected.strip().lower()


def run_longmemeval_against(
    system: BenchmarkSystem,
    questions_jsonl: Path,
    *,
    history_corpus_dir: Path | None = None,
) -> LongMemEvalScore:
    return LongMemEvalRunner(
        system, questions_jsonl,
        history_corpus_dir=history_corpus_dir,
    ).run()
