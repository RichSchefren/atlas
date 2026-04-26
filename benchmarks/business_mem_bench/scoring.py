"""Scoring functions for BusinessMemBench answers.

Each category uses a different scorer:

  binary_in_band       — confidence falls in [min, max]?
  f1_on_pair_recall    — set F1 on (pair, pair) recall
  ordered_chain_recall_f1 — F1 on ordered chain match
  cross_stream_overlap — does the answer flag the disagreement source?
  historical_exact     — string match against gold answer
  provenance_chain     — every claim has a verifiable evidence_kref?
  forgetfulness        — was the deprecated belief NOT returned?

Scorers return a float in [0.0, 1.0]; harness aggregates per category.

Spec: 08 - BusinessMemBench Design.md § 3 (each category has scoring rules)
"""

from __future__ import annotations

from typing import Any, Callable


Scorer = Callable[[Any, dict[str, Any]], float]


def binary_in_band(answer: Any, gold: dict[str, Any]) -> float:
    """Atlas returns a confidence float; check it falls in [min, max]."""
    band = gold.get("correct_answer_band", {})
    lo, hi = float(band.get("min", 0.0)), float(band.get("max", 1.0))
    try:
        value = float(answer)
    except (TypeError, ValueError):
        return 0.0
    return 1.0 if lo <= value <= hi else 0.0


def f1_on_pair_recall(answer: Any, gold: dict[str, Any]) -> float:
    """Set-F1 on contradicting pair recall.

    Gold has `expected_pair: [a, b]`. Answer is a list of [a, b] pairs.
    Order within pair doesn't matter; pair set membership does.
    """
    if not isinstance(answer, list):
        return 0.0
    expected = gold.get("expected_pair", [])
    if not expected:
        return 0.0
    expected_pair = frozenset(expected)
    answer_pairs = [
        frozenset(p) for p in answer
        if isinstance(p, (list, tuple)) and len(p) == 2
    ]
    if not answer_pairs:
        return 0.0
    tp = sum(1 for p in answer_pairs if p == expected_pair)
    precision = tp / len(answer_pairs)
    recall = tp / 1  # one expected pair per question
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def ordered_chain_recall_f1(answer: Any, gold: dict[str, Any]) -> float:
    """F1 on ordered chain match.

    Order matters: the chain is a causal trace, so 'A then B' is not the
    same answer as 'B then A'. We compute precision = LCS / |answer| and
    recall = LCS / |gold|.
    """
    gold_chain = gold.get("correct_chain", [])
    if not isinstance(answer, list) or not gold_chain:
        return 0.0
    lcs = _lcs_length(answer, gold_chain)
    if lcs == 0:
        return 0.0
    precision = lcs / len(answer)
    recall = lcs / len(gold_chain)
    return 2 * precision * recall / (precision + recall)


def cross_stream_overlap(answer: Any, gold: dict[str, Any]) -> float:
    """Did the system flag the disagreement source(s)?

    Gold has `expected_sources: [stream_a, stream_b]`. Answer should
    include both. Score is the overlap fraction.
    """
    expected = set(gold.get("expected_sources", []))
    if not expected:
        return 0.0
    if not isinstance(answer, (list, set)):
        return 0.0
    overlap = expected & set(answer)
    return len(overlap) / len(expected)


def historical_exact(answer: Any, gold: dict[str, Any]) -> float:
    """Trim+lowercase exact match against gold.correct_answer."""
    expected = str(gold.get("correct_answer", "")).strip().lower()
    if not expected:
        return 0.0
    return 1.0 if str(answer).strip().lower() == expected else 0.0


def provenance_chain(answer: Any, gold: dict[str, Any]) -> float:
    """Every returned claim must have a non-empty evidence_kref string."""
    if not isinstance(answer, list) or not answer:
        return 0.0
    valid = sum(
        1 for c in answer
        if isinstance(c, dict) and isinstance(c.get("evidence_kref"), str)
        and c["evidence_kref"].startswith("kref://")
    )
    return valid / len(answer)


def forgetfulness(answer: Any, gold: dict[str, Any]) -> float:
    """Pass when the deprecated belief is NOT in the answer set."""
    forbidden = set(gold.get("deprecated_krefs", []))
    if not isinstance(answer, list):
        return 0.0
    returned = {c.get("kref") if isinstance(c, dict) else c for c in answer}
    return 0.0 if (returned & forbidden) else 1.0


SCORERS: dict[str, Scorer] = {
    "binary_in_band": binary_in_band,
    "f1_on_pair_recall": f1_on_pair_recall,
    "ordered_chain_recall_f1": ordered_chain_recall_f1,
    "cross_stream_overlap": cross_stream_overlap,
    "historical_exact": historical_exact,
    "provenance_chain": provenance_chain,
    "forgetfulness": forgetfulness,
}


def score_answer(
    answer: Any, scoring_method: str, gold: dict[str, Any],
) -> float:
    """Pick the scorer by name and run it. Unknown method → 0.0 + log."""
    scorer = SCORERS.get(scoring_method)
    if scorer is None:
        return 0.0
    return scorer(answer, gold)


def _lcs_length(a: list[Any], b: list[Any]) -> int:
    """Length of longest common subsequence."""
    if not a or not b:
        return 0
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            dp[i][j] = (
                dp[i - 1][j - 1] + 1 if x == y
                else max(dp[i - 1][j], dp[i][j - 1])
            )
    return dp[len(a)][len(b)]
