"""Unit tests for Ripple Reassess — pure-logic tests of the confidence formula
and the heuristic LLM stub. No Neo4j required.

Spec: 06 - Ripple Algorithm Spec § 4
"""

import pytest


class TestReassessWeights:
    def test_default_weights_match_spec(self):
        from atlas_core.ripple import DEFAULT_WEIGHTS

        # Locked from Ripple Spec § 4.1 — empirically calibrated in Phase 3
        assert DEFAULT_WEIGHTS.alpha == 0.50
        assert DEFAULT_WEIGHTS.beta == 0.30
        assert DEFAULT_WEIGHTS.gamma == 0.15
        assert DEFAULT_WEIGHTS.delta == 0.05

    def test_weights_are_immutable(self):
        from atlas_core.ripple import DEFAULT_WEIGHTS

        with pytest.raises(Exception):
            DEFAULT_WEIGHTS.alpha = 0.99


class TestUpstreamChange:
    def test_confidence_delta_positive(self):
        from atlas_core.ripple import UpstreamChange

        u = UpstreamChange(
            upstream_kref="kref://test/x.belief",
            belief_text="X is true",
            old_confidence=0.5,
            new_confidence=0.9,
        )
        assert u.confidence_delta == pytest.approx(0.4)

    def test_confidence_delta_negative(self):
        from atlas_core.ripple import UpstreamChange

        u = UpstreamChange(
            upstream_kref="kref://test/x.belief",
            belief_text="X is no longer true",
            old_confidence=0.9,
            new_confidence=0.3,
        )
        assert u.confidence_delta == pytest.approx(-0.6)


class TestHeuristicReassessor:
    async def test_proportional_to_upstream_delta(self):
        from atlas_core.ripple import HeuristicReassessor, UpstreamChange

        r = HeuristicReassessor()
        u = UpstreamChange(
            upstream_kref="kref://test/x.belief",
            belief_text="X",
            old_confidence=0.4,
            new_confidence=0.7,
        )
        result = await r.evaluate(u, dependent_belief_text="Y", dependent_confidence=0.6)

        # delta=+0.3 upstream → bounded heuristic delta = +0.3
        assert result.delta == pytest.approx(0.3)
        assert "heuristic" in result.rationale

    async def test_bounded_at_plus_half(self):
        """Heuristic caps at ±0.5 so it never dominates the gamma term."""
        from atlas_core.ripple import HeuristicReassessor, UpstreamChange

        r = HeuristicReassessor()
        u = UpstreamChange(
            upstream_kref="kref://test/x.belief",
            belief_text="X",
            old_confidence=0.0,
            new_confidence=1.0,  # +1.0 raw, must clip to +0.5
        )
        result = await r.evaluate(u, dependent_belief_text="Y", dependent_confidence=0.5)
        assert result.delta == 0.5

    async def test_bounded_at_minus_half(self):
        from atlas_core.ripple import HeuristicReassessor, UpstreamChange

        r = HeuristicReassessor()
        u = UpstreamChange(
            upstream_kref="kref://test/x.belief",
            belief_text="X",
            old_confidence=1.0,
            new_confidence=0.0,  # -1.0 raw, must clip to -0.5
        )
        result = await r.evaluate(u, dependent_belief_text="Y", dependent_confidence=0.5)
        assert result.delta == -0.5


class TestTemporalDecay:
    def test_decay_at_zero_days_is_full_strength(self):
        from atlas_core.ripple.reassess import _temporal_decay_factor

        assert _temporal_decay_factor(0) == pytest.approx(1.0)

    def test_decay_at_90_days_is_half(self):
        from atlas_core.ripple.reassess import HALF_LIFE_DAYS, _temporal_decay_factor

        assert HALF_LIFE_DAYS == 90.0
        assert _temporal_decay_factor(90) == pytest.approx(0.5)

    def test_decay_at_180_days_is_quarter(self):
        from atlas_core.ripple.reassess import _temporal_decay_factor

        assert _temporal_decay_factor(180) == pytest.approx(0.25)

    def test_decay_unknown_age_is_neutral(self):
        from atlas_core.ripple.reassess import _temporal_decay_factor

        # No age info → return neutral 0.5 so δ-term contributes 0
        assert _temporal_decay_factor(None) == 0.5
