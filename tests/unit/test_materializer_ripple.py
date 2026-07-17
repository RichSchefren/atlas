"""The supported trust materializer owns the post-promotion Ripple hook."""

from types import SimpleNamespace


class _FakeResult:
    def __init__(self, record=None):
        self.record = record

    async def single(self):
        return self.record


class _FakeDriver:
    def __init__(self):
        self.confidence = None
        self.ripple_ledger_event_id = None

    def session(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def run(self, query, **params):
        if "SET belief.ripple_ledger_event_id" in query:
            self.ripple_ledger_event_id = params["ledger_event_id"]
            return _FakeResult()

        previous_confidence = self.confidence
        self.confidence = params["confidence"]
        return _FakeResult({
            "belief_kref": params["belief_kref"],
            "previous_confidence": previous_confidence,
            "ripple_ledger_event_id": self.ripple_ledger_event_id,
        })


class _FakeQuarantine:
    def __init__(self, candidate):
        self.candidate = candidate

    def list_approved(self):
        return [self.candidate]


class _StrictRippleEngine:
    def __init__(self):
        self.calls = []

    async def propagate(
        self,
        upstream_kref,
        *,
        old_confidence,
        new_confidence,
        belief_text="",
    ):
        self.calls.append({
            "upstream_kref": upstream_kref,
            "old_confidence": old_confidence,
            "new_confidence": new_confidence,
            "belief_text": belief_text,
        })
        return SimpleNamespace(succeeded=True)


async def test_materialization_triggers_ripple_once_with_current_signature():
    from atlas_core.ingestion import materialize_approved_candidates

    candidate = {
        "candidate_id": "candidate-1",
        "status": "approved",
        "ledger_event_id": "ledger-event-1",
        "subject_kref": "kref://test/People/rich.person",
        "predicate": "pref.theme",
        "object_value": "dark",
        "assertion_type": "preference",
        "confidence": 0.95,
        "trust_score": 1.0,
        "scope": "global",
        "lane": "atlas_vault",
        "evidence_refs_json": "[]",
    }
    driver = _FakeDriver()
    quarantine = _FakeQuarantine(candidate)
    ripple = _StrictRippleEngine()

    first = await materialize_approved_candidates(
        driver, quarantine, ripple_engine=ripple
    )
    second = await materialize_approved_candidates(
        driver, quarantine, ripple_engine=ripple
    )

    assert first.materialized == 1
    assert first.ripple_completed == 1
    assert second.materialized == 1
    assert second.ripple_completed == 0
    assert ripple.calls == [{
        "upstream_kref": (
            "kref://test/IngestedBeliefs/candidate_candidate-1.belief"
        ),
        "old_confidence": 0.0,
        "new_confidence": 0.95,
        "belief_text": "pref.theme: dark",
    }]
