"""Tests for the BusinessMemBench corpus + question generator.

Verifies determinism, expected category counts, and round-trip through
the harness's question loader."""

import json
from pathlib import Path

import pytest


# ─── World + events ─────────────────────────────────────────────────────────


class TestAtlasCoffeeWorld:
    def test_constants_match_spec(self):
        from benchmarks.business_mem_bench.corpus_generator import (
            AtlasCoffeeWorld,
        )

        w = AtlasCoffeeWorld()
        assert len(w.employees) == 12
        assert len(w.product_lines) == 4
        assert len(w.wholesale_clients) == 6
        assert len(w.competitors) == 3

    def test_lookup_helpers(self):
        from benchmarks.business_mem_bench.corpus_generator import (
            AtlasCoffeeWorld,
        )

        w = AtlasCoffeeWorld()
        assert w.employee_by_id("e01").name == "Sarah Chen"
        assert w.product_by_id("p04").name == "Festive Blend"
        assert w.client_by_id("w03").name == "The Daily Grind"
        assert w.employee_by_id("nope") is None


class TestEventGenerator:
    def test_generates_events(self):
        from benchmarks.business_mem_bench.corpus_generator import (
            AtlasCoffeeWorld,
            generate_events,
        )

        log = generate_events(AtlasCoffeeWorld(), seed=42)
        assert log.seed == 42
        # ~120 events expected (pricing 12 + decisions 18 + beliefs 14 +
        # contradictions 8 + deprecations 5 + hires 7 + 72 wholesale orders)
        assert 100 < len(log.events) < 200

    def test_deterministic_from_seed(self):
        from benchmarks.business_mem_bench.corpus_generator import (
            AtlasCoffeeWorld,
            generate_events,
        )

        a = generate_events(AtlasCoffeeWorld(), seed=42)
        b = generate_events(AtlasCoffeeWorld(), seed=42)
        assert [e.event_id for e in a.events] == [e.event_id for e in b.events]
        assert [e.occurred_at for e in a.events] == [e.occurred_at for e in b.events]

    def test_different_seeds_diverge(self):
        from benchmarks.business_mem_bench.corpus_generator import (
            AtlasCoffeeWorld,
            generate_events,
        )

        a = generate_events(AtlasCoffeeWorld(), seed=1)
        b = generate_events(AtlasCoffeeWorld(), seed=2)
        assert (
            [e.occurred_at for e in a.events]
            != [e.occurred_at for e in b.events]
        )

    def test_events_sorted_chronologically(self):
        from benchmarks.business_mem_bench.corpus_generator import (
            AtlasCoffeeWorld,
            generate_events,
        )

        log = generate_events(AtlasCoffeeWorld(), seed=42)
        timestamps = [e.occurred_at for e in log.events]
        assert timestamps == sorted(timestamps)


# ─── Corpus writer ──────────────────────────────────────────────────────────


class TestCorpusWriter:
    def test_writes_all_streams(self, tmp_path):
        from benchmarks.business_mem_bench.corpus_generator import (
            generate_corpus,
        )

        log, gt_path = generate_corpus(tmp_path, seed=42)
        assert (tmp_path / "meetings").is_dir()
        assert (tmp_path / "vault").is_dir()
        assert (tmp_path / "screen_events" / "log.csv").is_file()
        assert (tmp_path / "messages" / "messages.jsonl").is_file()
        assert (tmp_path / "events.jsonl").is_file()
        assert gt_path.is_file()
        assert len(list((tmp_path / "meetings").glob("*.md"))) > 5
        assert len(list((tmp_path / "vault").glob("*.md"))) > 5

    def test_ground_truth_shape(self, tmp_path):
        from benchmarks.business_mem_bench.corpus_generator import (
            generate_corpus,
        )

        _, gt_path = generate_corpus(tmp_path, seed=42)
        gt = json.loads(gt_path.read_text())
        assert gt["as_of"] == "2026-03-31"
        assert "final_prices_by_product" in gt
        assert set(gt["final_prices_by_product"].keys()) == {"p01", "p02", "p03", "p04"}
        assert isinstance(gt["deprecated_beliefs"], list)
        assert gt["n_decisions"] >= 15


# ─── Question writer ────────────────────────────────────────────────────────


class TestQuestionWriter:
    def test_emits_all_seven_categories(self, tmp_path):
        from benchmarks.business_mem_bench.corpus_generator import (
            generate_questions,
        )

        counts = generate_questions(tmp_path, seed=42)
        assert set(counts.keys()) == {
            "propagation", "contradiction", "lineage",
            "cross_stream", "historical", "provenance", "forgetfulness",
        }
        for cat, n in counts.items():
            assert n > 0, f"{cat} produced 0 questions"
        # Ensure files exist
        gold = tmp_path / "gold"
        for cat in counts:
            assert (gold / f"{cat}.jsonl").is_file()

    def test_total_question_count_in_range(self, tmp_path):
        from benchmarks.business_mem_bench.corpus_generator import (
            generate_questions,
        )

        counts = generate_questions(tmp_path, seed=42)
        total = sum(counts.values())
        # The synthetic generator targets ~150-300 deterministic questions
        # in addition to the eventual 200 human-authored ones.
        assert total >= 140, f"only generated {total} questions"

    def test_questions_validate_via_harness_loader(self, tmp_path):
        from benchmarks.business_mem_bench import load_questions
        from benchmarks.business_mem_bench.corpus_generator import (
            generate_questions,
        )

        generate_questions(tmp_path, seed=42)
        questions = list(load_questions(tmp_path / "gold"))
        assert len(questions) >= 140
        # Every question has a non-empty id, scoring method, and category
        for q in questions:
            assert q.id
            assert q.scoring_method
            assert q.category is not None

    def test_propagation_payload_shape(self, tmp_path):
        from benchmarks.business_mem_bench.corpus_generator import (
            generate_questions,
        )

        generate_questions(tmp_path, seed=42)
        with (tmp_path / "gold" / "propagation.jsonl").open() as f:
            first = json.loads(f.readline())
        assert "correct_answer_band" in first
        assert "min" in first["correct_answer_band"]
        assert "max" in first["correct_answer_band"]
        assert first["scoring"] == "binary_in_band"

    def test_contradiction_payload_has_pair(self, tmp_path):
        from benchmarks.business_mem_bench.corpus_generator import (
            generate_questions,
        )

        generate_questions(tmp_path, seed=42)
        with (tmp_path / "gold" / "contradiction.jsonl").open() as f:
            first = json.loads(f.readline())
        assert isinstance(first["expected_pair"], list)
        assert len(first["expected_pair"]) == 2
        assert all(s.startswith("kref://") for s in first["expected_pair"])

    def test_forgetfulness_marks_deprecated_krefs(self, tmp_path):
        from benchmarks.business_mem_bench.corpus_generator import (
            generate_questions,
        )

        generate_questions(tmp_path, seed=42)
        with (tmp_path / "gold" / "forgetfulness.jsonl").open() as f:
            first = json.loads(f.readline())
        assert isinstance(first["deprecated_krefs"], list)
        assert len(first["deprecated_krefs"]) >= 1


# ─── Round-trip through harness ─────────────────────────────────────────────


class TestEndToEndStubRun:
    """Smoke-test: generate corpus + questions, then run harness with the
    Vanilla baseline (which returns None for everything). Should produce a
    valid EvalReport with 0% scores — the floor."""

    def test_full_pipeline_with_vanilla_baseline(self, tmp_path):
        from benchmarks.business_mem_bench import BenchmarkRunner
        from benchmarks.business_mem_bench.adapters import VanillaSystem
        from benchmarks.business_mem_bench.corpus_generator import (
            generate_corpus,
            generate_questions,
        )

        generate_corpus(tmp_path, seed=42)
        generate_questions(tmp_path, seed=42)

        report = BenchmarkRunner(
            system=VanillaSystem(),
            corpus_dir=tmp_path,
            gold_dir=tmp_path / "gold",
        ).run()

        assert report.system_name == "vanilla_no_memory"
        assert len(report.raw_results) >= 140
        # Vanilla returns None → every scorer returns 0.0
        assert report.overall_mean_score == 0.0
