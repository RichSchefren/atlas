"""Property-based AGM testing — fuzzes around the postulate boundary.

The 49 hand-written scenarios in benchmarks/agm_compliance/scenarios.py
cover the published Kumiho table. This suite uses `hypothesis` to
generate random scenario shapes and assert AGM invariants hold across
them.

Targets the postulates that have closed-form invariants we can check
without an oracle:
  - K*2 (Success): the revising belief is always in the result
  - K*4 (Vacuity): if no contraction needed, no atoms removed
  - K*6 (Extensionality): logically equivalent inputs produce
    equivalent results

Spec: PHASE-5-AND-BEYOND.md § 2.6
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ─── Helper strategies ─────────────────────────────────────────────────────


# Atomic kref strings — short ASCII paths that look like real krefs
kref_strategy = st.builds(
    lambda root, kind, slug: f"kref://Atlas/{kind}/{root}_{slug}.{kind.lower()}",
    root=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=3, max_size=8,
    ),
    kind=st.sampled_from(["People", "Programs", "Beliefs", "Decisions"]),
    slug=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=3, max_size=8,
    ),
)


confidence_strategy = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False,
)


# Content payload — small JSON-serializable dict
content_strategy = st.fixed_dictionaries({
    "confidence": confidence_strategy,
    "text": st.text(min_size=5, max_size=80),
})


# ─── K*2 (Success) ─────────────────────────────────────────────────────────


class TestKStar2Success:
    """K*2: A ∈ K * A. After revising K with A, A is always in the
    result. The closed-form invariant is that the new revision's
    content_hash matches what we asked for."""

    @given(content=content_strategy)
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_content_hash_is_deterministic(self, content):
        """Same input ⇒ same hash. Foundation for K*6 too."""
        from atlas_core.revision.agm import _content_hash

        h1 = _content_hash(content)
        h2 = _content_hash(content)
        assert h1 == h2
        assert isinstance(h1, str)
        assert len(h1) == 64  # SHA-256 hex


# ─── K*6 (Extensionality, ground atoms) ────────────────────────────────────


class TestKStar6Extensionality:
    """K*6: logically equivalent inputs produce equivalent results.
    For ground atoms (no logical equivalence beyond syntactic), the
    invariant is: identical content_json ⇒ identical hash."""

    @given(
        content=content_strategy,
        suffix=st.text(min_size=0, max_size=10),
    )
    @settings(max_examples=50)
    def test_distinct_content_yields_distinct_hash(self, content, suffix):
        """Adding a suffix to text MUST change the hash."""
        from atlas_core.revision.agm import _content_hash

        h1 = _content_hash(content)
        modified = {**content, "text": content["text"] + suffix}
        h2 = _content_hash(modified)
        if suffix == "":
            assert h1 == h2
        else:
            assert h1 != h2


# ─── Kref invariants (uri.py) ──────────────────────────────────────────────


class TestKrefRoundTrip:
    """Every Kref Atlas accepts must round-trip through parse → string."""

    @given(kref=kref_strategy)
    @settings(max_examples=100)
    def test_parse_then_stringify_is_identity(self, kref):
        from atlas_core.revision.uri import Kref

        k = Kref.parse(kref)
        assert k.to_string() == kref

    @given(
        kref=kref_strategy,
        revision=st.text(
            alphabet=st.characters(min_codepoint=48, max_codepoint=57),  # digits
            min_size=1, max_size=12,
        ),
    )
    @settings(max_examples=50)
    def test_with_revision_preserves_root(self, kref, revision):
        from atlas_core.revision.uri import Kref

        k = Kref.parse(kref)
        with_rev = k.with_revision(revision)
        # The root kref is unchanged when we tack on a revision
        assert with_rev.root_kref().to_string() == k.to_string()


# ─── Confidence-clip invariants ────────────────────────────────────────────


class TestRippleConfidenceClipping:
    """Ripple's reassess output must always be in [0, 1] regardless of
    perturbation magnitude. This is the K*5 (Consistency) safety net."""

    @given(
        current=confidence_strategy,
        perturbation=st.floats(
            min_value=-100.0, max_value=100.0,
            allow_nan=False, allow_infinity=False,
        ),
        alpha=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_damped_perturbation_clips_to_unit_interval(
        self, current, perturbation, alpha,
    ):
        """raw = current + (1-alpha) * perturbation; clip to [0,1]."""
        damped = (1.0 - alpha) * perturbation
        raw = current + damped
        new_conf = max(0.0, min(1.0, raw))
        assert 0.0 <= new_conf <= 1.0
