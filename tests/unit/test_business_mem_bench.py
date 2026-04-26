"""Unit tests for the BusinessMemBench harness, scoring, and question
schema. Uses a synthetic memory system stub — no real Atlas/baseline
required for these tests."""

import json
from pathlib import Path

import pytest


# ─── Scoring ─────────────────────────────────────────────────────────────────


class TestScoring:
    def test_binary_in_band_pass(self):
        from benchmarks.business_mem_bench import score_answer
        assert score_answer(
            0.3, "binary_in_band",
            {"correct_answer_band": {"min": 0.0, "max": 0.5}},
        ) == 1.0

    def test_binary_in_band_fail(self):
        from benchmarks.business_mem_bench import score_answer
        assert score_answer(
            0.9, "binary_in_band",
            {"correct_answer_band": {"min": 0.0, "max": 0.5}},
        ) == 0.0

    def test_binary_in_band_non_numeric(self):
        from benchmarks.business_mem_bench import score_answer
        assert score_answer(
            "not a number", "binary_in_band",
            {"correct_answer_band": {"min": 0.0, "max": 1.0}},
        ) == 0.0

    def test_pair_recall_perfect(self):
        from benchmarks.business_mem_bench import score_answer
        s = score_answer(
            [["a", "b"]],
            "f1_on_pair_recall",
            {"expected_pair": ["a", "b"]},
        )
        assert s == 1.0

    def test_pair_recall_order_invariant(self):
        from benchmarks.business_mem_bench import score_answer
        s = score_answer(
            [["b", "a"]],
            "f1_on_pair_recall",
            {"expected_pair": ["a", "b"]},
        )
        assert s == 1.0

    def test_pair_recall_with_distractors(self):
        from benchmarks.business_mem_bench import score_answer
        # 1 correct, 1 distractor → precision 0.5, recall 1.0 → F1 ~0.667
        s = score_answer(
            [["a", "b"], ["c", "d"]],
            "f1_on_pair_recall",
            {"expected_pair": ["a", "b"]},
        )
        assert 0.6 < s < 0.7

    def test_chain_perfect_match(self):
        from benchmarks.business_mem_bench import score_answer
        s = score_answer(
            ["x", "y", "z"],
            "ordered_chain_recall_f1",
            {"correct_chain": ["x", "y", "z"]},
        )
        assert s == 1.0

    def test_chain_partial_match(self):
        from benchmarks.business_mem_bench import score_answer
        # Gold: x,y,z. Answer: x,z. LCS=2. P=1.0, R=2/3. F1 = 0.8
        s = score_answer(
            ["x", "z"],
            "ordered_chain_recall_f1",
            {"correct_chain": ["x", "y", "z"]},
        )
        assert 0.79 < s < 0.81

    def test_cross_stream_overlap(self):
        from benchmarks.business_mem_bench import score_answer
        s = score_answer(
            ["meeting_a", "screen_b"],
            "cross_stream_overlap",
            {"expected_sources": ["meeting_a", "screen_b"]},
        )
        assert s == 1.0

    def test_cross_stream_partial(self):
        from benchmarks.business_mem_bench import score_answer
        s = score_answer(
            ["meeting_a"],
            "cross_stream_overlap",
            {"expected_sources": ["meeting_a", "screen_b"]},
        )
        assert s == 0.5

    def test_historical_exact_case_insensitive(self):
        from benchmarks.business_mem_bench import score_answer
        assert score_answer(
            "  Q1 2026  ",
            "historical_exact",
            {"correct_answer": "q1 2026"},
        ) == 1.0

    def test_provenance_chain_all_valid(self):
        from benchmarks.business_mem_bench import score_answer
        assert score_answer(
            [
                {"evidence_kref": "kref://Atlas/Sessions/a"},
                {"evidence_kref": "kref://Atlas/Sessions/b"},
            ],
            "provenance_chain",
            {},
        ) == 1.0

    def test_provenance_chain_partial(self):
        from benchmarks.business_mem_bench import score_answer
        s = score_answer(
            [
                {"evidence_kref": "kref://Atlas/Sessions/a"},
                {"evidence_kref": "no kref"},
            ],
            "provenance_chain",
            {},
        )
        assert s == 0.5

    def test_forgetfulness_pass(self):
        from benchmarks.business_mem_bench import score_answer
        s = score_answer(
            [{"kref": "kref://Atlas/Beliefs/active"}],
            "forgetfulness",
            {"deprecated_krefs": ["kref://Atlas/Beliefs/old"]},
        )
        assert s == 1.0

    def test_forgetfulness_fail_when_deprecated_returned(self):
        from benchmarks.business_mem_bench import score_answer
        s = score_answer(
            [{"kref": "kref://Atlas/Beliefs/old"}],
            "forgetfulness",
            {"deprecated_krefs": ["kref://Atlas/Beliefs/old"]},
        )
        assert s == 0.0

    def test_unknown_scoring_method_returns_zero(self):
        from benchmarks.business_mem_bench import score_answer
        assert score_answer("anything", "made_up_method", {}) == 0.0


# ─── Question loader ─────────────────────────────────────────────────────────


@pytest.fixture
def gold_dir(tmp_path):
    """Fixture: tiny JSONL gold files for two categories."""
    d = tmp_path / "gold"
    d.mkdir()
    (d / "propagation.jsonl").write_text("\n".join([
        json.dumps({
            "id": "prop_001",
            "question": "What is the new confidence?",
            "scoring": "binary_in_band",
            "correct_answer_band": {"min": 0.0, "max": 0.5},
            "is_human_authored": True,
        }),
        json.dumps({
            "id": "prop_002",
            "question": "And what about this one?",
            "scoring": "binary_in_band",
            "correct_answer_band": {"min": 0.5, "max": 1.0},
        }),
    ]) + "\n")
    (d / "contradiction.jsonl").write_text(json.dumps({
        "id": "contra_001",
        "question": "Are there contradictions?",
        "scoring": "f1_on_pair_recall",
        "expected_pair": ["a", "b"],
    }) + "\n")
    return d


class TestQuestionLoader:
    def test_loads_all_categories(self, gold_dir):
        from benchmarks.business_mem_bench import Category, load_questions
        questions = list(load_questions(gold_dir))
        assert len(questions) == 3
        cats = {q.category for q in questions}
        assert cats == {Category.PROPAGATION, Category.CONTRADICTION}

    def test_only_filter(self, gold_dir):
        from benchmarks.business_mem_bench import Category, load_questions
        only_prop = list(load_questions(gold_dir, only=[Category.PROPAGATION]))
        assert len(only_prop) == 2
        assert all(q.category == Category.PROPAGATION for q in only_prop)

    def test_human_authored_flag(self, gold_dir):
        from benchmarks.business_mem_bench import Category, load_questions
        qs = list(load_questions(gold_dir, only=[Category.PROPAGATION]))
        assert any(q.is_human_authored for q in qs)
        assert not all(q.is_human_authored for q in qs)

    def test_missing_categories_skipped(self, gold_dir):
        # Only propagation + contradiction exist; loader silently skips others
        from benchmarks.business_mem_bench import Category, load_questions
        qs = list(load_questions(gold_dir, only=[Category.LINEAGE]))
        assert qs == []


# ─── Harness end-to-end with stub system ────────────────────────────────────


class StubMemorySystem:
    """A stub that always returns 0.3 confidence (in propagation band) and
    the correct pair for contradiction questions. Lets us validate the
    harness pipeline end-to-end without a real backend."""

    name = "stub"

    def __init__(self):
        self.reset_count = 0
        self.ingest_called_with = None

    def reset(self):
        self.reset_count += 1

    def ingest(self, corpus_dir):
        self.ingest_called_with = corpus_dir

    def query(self, payload):
        if "correct_answer_band" in payload:
            return 0.3
        if "expected_pair" in payload:
            return [payload["expected_pair"]]
        return None


class TestHarness:
    def test_end_to_end_run(self, gold_dir, tmp_path):
        from benchmarks.business_mem_bench import BenchmarkRunner

        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        system = StubMemorySystem()
        runner = BenchmarkRunner(
            system=system,
            corpus_dir=corpus_dir,
            gold_dir=gold_dir,
        )
        report = runner.run()

        assert system.reset_count == 1
        assert system.ingest_called_with == corpus_dir
        assert report.system_name == "stub"
        assert len(report.raw_results) == 3

    def test_per_category_aggregation(self, gold_dir, tmp_path):
        from benchmarks.business_mem_bench import BenchmarkRunner, Category

        runner = BenchmarkRunner(
            system=StubMemorySystem(),
            corpus_dir=tmp_path,
            gold_dir=gold_dir,
        )
        report = runner.run()

        prop_report = report.per_category[Category.PROPAGATION]
        # Stub returns 0.3 — in band for prop_001 (0..0.5), out for prop_002 (0.5..1.0)
        assert prop_report.n_perfect == 1
        assert prop_report.n_zero == 1
        assert prop_report.mean_score == 0.5

        contra_report = report.per_category[Category.CONTRADICTION]
        assert contra_report.n_perfect == 1
        assert contra_report.mean_score == 1.0

    def test_overall_score_is_weighted(self, gold_dir, tmp_path):
        from benchmarks.business_mem_bench import BenchmarkRunner

        report = BenchmarkRunner(
            system=StubMemorySystem(),
            corpus_dir=tmp_path,
            gold_dir=gold_dir,
        ).run()
        # 1 perfect + 1 zero + 1 perfect → (1+0+1)/3 ≈ 0.667
        assert 0.66 < report.overall_mean_score < 0.67

    def test_serializes_to_dict(self, gold_dir, tmp_path):
        from benchmarks.business_mem_bench import BenchmarkRunner

        report = BenchmarkRunner(
            system=StubMemorySystem(),
            corpus_dir=tmp_path,
            gold_dir=gold_dir,
        ).run()
        data = report.to_dict()
        assert data["system_name"] == "stub"
        assert "propagation" in data["per_category"]

    def test_only_filter_propagates(self, gold_dir, tmp_path):
        from benchmarks.business_mem_bench import (
            BenchmarkRunner,
            Category,
        )
        report = BenchmarkRunner(
            system=StubMemorySystem(),
            corpus_dir=tmp_path,
            gold_dir=gold_dir,
            only_categories=[Category.PROPAGATION],
        ).run()
        assert set(report.per_category.keys()) == {Category.PROPAGATION}

    def test_question_crash_recorded_as_error_not_raise(self, gold_dir, tmp_path):
        from benchmarks.business_mem_bench import BenchmarkRunner

        class BoomSystem(StubMemorySystem):
            def query(self, payload):
                raise RuntimeError("boom")

        report = BenchmarkRunner(
            system=BoomSystem(),
            corpus_dir=tmp_path,
            gold_dir=gold_dir,
        ).run()
        # All three questions errored — none scored
        for r in report.raw_results:
            assert r.error is not None
            assert "boom" in r.error
