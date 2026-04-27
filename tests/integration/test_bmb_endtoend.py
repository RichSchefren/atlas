"""End-to-end BusinessMemBench harness regression test.

Runs the full corpus + harness against the three adapters that don't need
external credentials (Vanilla, Graphiti, Atlas) and asserts the structural
truth that defines the benchmark's value claim:

  - Vanilla scores 0 (no graph at all).
  - Atlas scores 1.0 on every category (it was designed against this corpus).
  - Graphiti ties Atlas on the three "typed-graph-suffices" categories
    (lineage, historical, provenance) and *loses* on the four categories
    that need Ripple / AGM (propagation, contradiction, cross_stream,
    forgetfulness).

If this test ever fails, either the corpus drifted, an adapter regressed,
or the README's headline numbers no longer match reality. All three are
worth catching loudly.

Spec: 08 - BusinessMemBench Design.md § 4 (Eval Protocol).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]


_RIPPLE_CATEGORIES = ("propagation", "contradiction", "cross_stream", "forgetfulness")
"""Categories where Atlas's Ripple + AGM extension over Graphiti should win.

Mirrors the headline claim in the project README."""


_TYPED_GRAPH_CATEGORIES = ("lineage", "historical", "provenance")
"""Categories Graphiti can answer with the typed graph alone — no Ripple.

These should be ties, not wins."""


@pytest.fixture(scope="module")
def bmb_corpus(tmp_path_factory) -> Path:
    """Generate a fresh BMB corpus in a tmpdir that lives for the module."""
    from benchmarks.business_mem_bench.corpus_generator import (
        generate_corpus,
        generate_questions,
    )

    corpus_dir = tmp_path_factory.mktemp("bmb_e2e")
    generate_corpus(corpus_dir, seed=42)
    generate_questions(corpus_dir, seed=42)
    yield corpus_dir
    shutil.rmtree(corpus_dir, ignore_errors=True)


def _run_adapter(adapter_cls, corpus_dir: Path):
    from benchmarks.business_mem_bench import BenchmarkRunner

    sys_inst = adapter_cls()
    try:
        return BenchmarkRunner(
            system=sys_inst,
            corpus_dir=corpus_dir,
            gold_dir=corpus_dir / "gold",
        ).run()
    finally:
        if hasattr(sys_inst, "close"):
            try:
                sys_inst.close()
            except Exception:
                pass


def test_vanilla_scores_zero_across_the_board(bmb_corpus):
    """No-memory baseline cannot answer any BMB category."""
    from benchmarks.business_mem_bench.adapters import VanillaSystem

    report = _run_adapter(VanillaSystem, bmb_corpus)
    assert report.overall_mean_score == 0.0
    for cat, c in report.per_category.items():
        assert c.mean_score == 0.0, f"vanilla scored on {cat.value}: {c.mean_score}"


def test_atlas_perfect_score_on_every_category(bmb_corpus):
    """Atlas was designed for this corpus — should clear it perfectly.

    A regression here means either the adapter, Ripple, or AGM revision
    silently broke. Treat it as a P0 alarm."""
    from benchmarks.business_mem_bench.adapters import AtlasSystem

    report = _run_adapter(AtlasSystem, bmb_corpus)
    assert report.overall_mean_score == pytest.approx(1.0)
    for cat, c in report.per_category.items():
        assert c.mean_score == pytest.approx(1.0), (
            f"atlas regressed on {cat.value}: {c.mean_score:.3f}"
        )
        assert c.n_perfect == c.n_questions


def test_graphiti_loses_only_on_ripple_categories(bmb_corpus):
    """Graphiti's typed graph can answer the easy three; Ripple is the gap."""
    from benchmarks.business_mem_bench.adapters import GraphitiSystem

    report = _run_adapter(GraphitiSystem, bmb_corpus)

    for cat_name in _TYPED_GRAPH_CATEGORIES:
        cat_score = next(
            c.mean_score for cat, c in report.per_category.items()
            if cat.value == cat_name
        )
        assert cat_score == pytest.approx(1.0), (
            f"graphiti unexpectedly weak on {cat_name}: {cat_score:.3f} — "
            f"the typed-graph categories should be a tie, not a win"
        )

    for cat_name in _RIPPLE_CATEGORIES:
        cat_score = next(
            c.mean_score for cat, c in report.per_category.items()
            if cat.value == cat_name
        )
        assert cat_score < 1.0, (
            f"graphiti unexpectedly perfect on {cat_name}: {cat_score:.3f} — "
            f"this category is supposed to require Ripple/AGM"
        )
