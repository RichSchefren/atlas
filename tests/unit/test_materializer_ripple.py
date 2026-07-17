"""The supported trust materializer owns the post-promotion Ripple hook."""

from types import SimpleNamespace


class _FakeResult:
    def __init__(self, record=None):
        self.record = record

    async def single(self):
        return self.record


class _FakeDriver:
    def __init__(self):
        self.revisions = {}
        self.current_revision = None
        self.current_content_json = None
        self.ripple_ledger_event_id = None
        self.schema_statements = []

    def session(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def run(self, query, **params):
        if query.startswith("CREATE CONSTRAINT "):
            self.schema_statements.append(query)
            return _FakeResult()

        if "SET belief.ripple_ledger_event_id" in query:
            self.ripple_ledger_event_id = params["ledger_event_id"]
            return _FakeResult()

        if "existing_revision_kref" in query:
            existing = self.revisions.get(params["ledger_event_id"])
            return _FakeResult({
                "existing_revision_kref": existing["revision_kref"] if existing else None,
                "existing_previous_confidence": (
                    existing["previous_confidence"] if existing else None
                ),
                "prior_content_json": None,
                "current_revision_kref": self.current_revision,
                "current_content_json": self.current_content_json,
                "ripple_ledger_event_id": self.ripple_ledger_event_id,
            })

        if "RETURN belief.kref AS belief_kref" in query:
            import json

            self.revisions[params["ledger_event_id"]] = {
                "revision_kref": params["revision_kref"],
                "previous_confidence": params["previous_confidence"],
            }
            self.current_revision = params["revision_kref"]
            self.current_content_json = json.dumps({
                "confidence": params["confidence"],
            })
            return _FakeResult({"belief_kref": params["belief_kref"]})

        raise AssertionError(f"unexpected Cypher: {query}")


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


async def test_materialization_triggers_ripple_once_with_current_signature(monkeypatch):
    from atlas_core.ingestion import (
        belief_kref_for_candidate,
        materialize_approved_candidates,
    )

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

    async def fake_revise(_driver, target_kref, _content, **_kwargs):
        return SimpleNamespace(
            new_revision_kref=target_kref.with_revision("revision-1")
        )

    monkeypatch.setattr(
        "atlas_core.ingestion.materializer.revise",
        fake_revise,
    )

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
    assert len(driver.schema_statements) == 6
    assert ripple.calls == [{
        "upstream_kref": belief_kref_for_candidate(candidate),
        "old_confidence": 0.0,
        "new_confidence": 0.95,
        "belief_text": "pref.theme: dark",
    }]


def test_belief_identity_is_stable_across_value_revisions():
    from atlas_core.ingestion import belief_kref_for_candidate

    base = {
        "subject_kref": "kref://test/People/rich.person",
        "predicate": "pref.theme",
        "scope": "global",
        "object_value": "dark",
    }
    changed_value = {**base, "object_value": "light"}
    changed_predicate = {**base, "predicate": "pref.font"}

    assert belief_kref_for_candidate(base) == belief_kref_for_candidate(changed_value)
    assert belief_kref_for_candidate(base) != belief_kref_for_candidate(changed_predicate)
