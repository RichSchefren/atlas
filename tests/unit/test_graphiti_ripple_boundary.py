"""Raw Graphiti extraction must not bypass the trust materialization boundary."""

from types import SimpleNamespace


async def test_raw_graphiti_ingestion_does_not_call_ripple(monkeypatch):
    from graphiti_core import Graphiti

    from atlas_core.graphiti import AtlasGraphiti

    results = SimpleNamespace(
        edges=[SimpleNamespace(uuid="edge-1", expired_at=None)],
        episode=SimpleNamespace(uuid="episode-1"),
    )

    async def fake_add_episode(_self, *_args, **_kwargs):
        return results

    class Ledger:
        @staticmethod
        def is_promoted(_edge_uuid):
            return True

    class StrictRippleEngine:
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
            self.calls.append(upstream_kref)

    monkeypatch.setattr(Graphiti, "add_episode", fake_add_episode)
    atlas = object.__new__(AtlasGraphiti)
    atlas.ripple_engine = StrictRippleEngine()
    atlas.ledger = Ledger()

    returned = await atlas.add_episode()

    assert returned is results
    assert atlas.ripple_engine.calls == []
