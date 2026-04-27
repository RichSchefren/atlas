"""BusinessMemBench evaluation harness.

Run order:
  1. Pick a `BenchmarkSystem` (Atlas, Mem0, Letta, Memori, Graphiti,
     Kumiho, vanilla GPT).
  2. system.reset()
  3. system.ingest(corpus_dir)
  4. for question in questions: answer = system.query(question.payload)
                                score = score_answer(answer, ..., gold)
  5. Aggregate scores → CategoryReport → EvalReport

Spec: 08 - BusinessMemBench Design.md § 4 (Eval Protocol)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from benchmarks.business_mem_bench.questions import (
    Category,
    Question,
    load_questions,
)
from benchmarks.business_mem_bench.scoring import score_answer

log = logging.getLogger(__name__)


# ─── BenchmarkSystem protocol ────────────────────────────────────────────────


class BenchmarkSystem(Protocol):
    """Contract every system-under-test implements.

    Adapters live in benchmarks/adapters/<system>.py and translate the
    universal protocol into each system's native API.
    """

    name: str

    def reset(self) -> None:
        """Drop all state. Next ingest starts from scratch."""

    def ingest(self, corpus_dir: Path) -> None:
        """Load the BusinessMemBench corpus into the system's memory."""

    def query(self, payload: dict[str, Any]) -> Any:
        """Return the system's answer for the question payload.

        Payload shape varies by category; adapters dispatch internally.
        """


# ─── Reports ─────────────────────────────────────────────────────────────────


@dataclass
class QuestionResult:
    """Per-question outcome — stored for error analysis."""

    question_id: str
    category: Category
    score: float
    answer: Any
    elapsed_ms: float
    error: str | None = None


@dataclass
class CategoryReport:
    """Aggregate over all questions in one category."""

    category: Category
    n_questions: int
    n_scored: int
    mean_score: float
    median_score: float
    n_perfect: int
    n_zero: int
    mean_elapsed_ms: float

    @classmethod
    def from_results(
        cls, category: Category, results: list[QuestionResult],
    ) -> CategoryReport:
        scored = [r for r in results if r.error is None]
        scores = [r.score for r in scored]
        n = len(scores)
        if n == 0:
            return cls(
                category=category, n_questions=len(results), n_scored=0,
                mean_score=0.0, median_score=0.0, n_perfect=0, n_zero=0,
                mean_elapsed_ms=0.0,
            )
        scores_sorted = sorted(scores)
        median = scores_sorted[n // 2] if n % 2 else (
            (scores_sorted[n // 2 - 1] + scores_sorted[n // 2]) / 2
        )
        return cls(
            category=category,
            n_questions=len(results),
            n_scored=n,
            mean_score=sum(scores) / n,
            median_score=median,
            n_perfect=sum(1 for s in scores if s == 1.0),
            n_zero=sum(1 for s in scores if s == 0.0),
            mean_elapsed_ms=sum(r.elapsed_ms for r in scored) / n,
        )


@dataclass
class EvalReport:
    """Top-level summary across all categories for one system."""

    system_name: str
    started_at: str
    finished_at: str = ""
    per_category: dict[Category, CategoryReport] = field(default_factory=dict)
    raw_results: list[QuestionResult] = field(default_factory=list)

    @property
    def overall_mean_score(self) -> float:
        if not self.per_category:
            return 0.0
        weighted = sum(
            r.mean_score * r.n_scored for r in self.per_category.values()
        )
        n = sum(r.n_scored for r in self.per_category.values())
        return weighted / n if n else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_name": self.system_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "overall_mean_score": self.overall_mean_score,
            "per_category": {
                cat.value: {
                    "n_questions": r.n_questions,
                    "n_scored": r.n_scored,
                    "mean_score": r.mean_score,
                    "median_score": r.median_score,
                    "n_perfect": r.n_perfect,
                    "n_zero": r.n_zero,
                    "mean_elapsed_ms": r.mean_elapsed_ms,
                }
                for cat, r in self.per_category.items()
            },
        }


# ─── Runner ──────────────────────────────────────────────────────────────────


@dataclass
class BenchmarkRunner:
    """Drives one full eval pass: reset → ingest → query loop → report."""

    system: BenchmarkSystem
    corpus_dir: Path
    gold_dir: Path
    only_categories: list[Category] | None = None

    def run(self) -> EvalReport:
        from datetime import datetime, timezone

        log.info("BusinessMemBench: %s starting", self.system.name)
        report = EvalReport(
            system_name=self.system.name,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        log.info("Resetting %s", self.system.name)
        self.system.reset()

        log.info("Ingesting corpus from %s", self.corpus_dir)
        self.system.ingest(self.corpus_dir)

        per_cat_results: dict[Category, list[QuestionResult]] = {}
        for question in load_questions(
            self.gold_dir, only=self.only_categories,
        ):
            result = self._run_one(question)
            per_cat_results.setdefault(question.category, []).append(result)
            report.raw_results.append(result)

        for cat, results in per_cat_results.items():
            report.per_category[cat] = CategoryReport.from_results(cat, results)

        report.finished_at = datetime.now(timezone.utc).isoformat()
        log.info(
            "BusinessMemBench: %s done overall=%.3f",
            self.system.name, report.overall_mean_score,
        )
        return report

    def _run_one(self, question: Question) -> QuestionResult:
        start = time.perf_counter()
        try:
            answer = self.system.query(question.payload)
            score = score_answer(
                answer, question.scoring_method, question.payload,
            )
            return QuestionResult(
                question_id=question.id,
                category=question.category,
                score=score,
                answer=answer,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            log.exception("question %s crashed", question.id)
            return QuestionResult(
                question_id=question.id,
                category=question.category,
                score=0.0,
                answer=None,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
