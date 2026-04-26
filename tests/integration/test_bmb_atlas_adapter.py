"""Integration tests for the Atlas BusinessMemBench adapter.

Smoke-test that AtlasSystem implements the BenchmarkSystem protocol and
the propagation pathway round-trips through real Neo4j + a real ledger.
"""

import os
import pytest


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def neo4j_connection():
    pytest.importorskip("neo4j")
    return {
        "neo4j_uri": os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        "neo4j_user": os.environ.get("NEO4J_USER", "neo4j"),
        "neo4j_password": os.environ.get("NEO4J_PASSWORD", "atlasdev"),
    }


@pytest.fixture
def atlas_system(neo4j_connection):
    from benchmarks.business_mem_bench.adapters import AtlasSystem
    sys = AtlasSystem(**neo4j_connection, ns="BMBTest")
    sys.reset()
    yield sys
    sys.close()


class TestAtlasAdapter:
    def test_reset_creates_data_dir(self, atlas_system):
        assert atlas_system._data_dir is not None
        assert atlas_system._data_dir.exists()

    def test_query_propagation_with_no_graph_returns_default(self, atlas_system):
        # No graph state → adapter returns 0.5 mid-band sentinel
        result = atlas_system.query({
            "correct_answer_band": {"min": 0.0, "max": 1.0},
            "upstream_kref": "kref://BMBTest/Beliefs/missing.belief",
            "old_confidence": 0.9,
            "new_confidence": 0.2,
        })
        assert isinstance(result, float)

    def test_query_contradiction_with_empty_proposals(self, atlas_system):
        result = atlas_system.query({
            "expected_pair": ["a", "b"],
            "proposals": [],
        })
        assert result == []

    def test_cross_stream_returns_lane_set(self, atlas_system):
        result = atlas_system.query({
            "expected_sources": ["a"],
            "subject_kref": "kref://BMBTest/Beliefs/anything",
        })
        assert isinstance(result, list)


class TestExternalStubs:
    def test_mem0_stub_raises_on_reset(self):
        from benchmarks.business_mem_bench.adapters import (
            Mem0System,
            MissingClientError,
        )
        sys = Mem0System()
        with pytest.raises(MissingClientError, match="mem0ai"):
            sys.reset()

    def test_kumiho_stub_raises(self):
        from benchmarks.business_mem_bench.adapters import (
            KumihoSystem,
            MissingClientError,
        )
        with pytest.raises(MissingClientError, match="kumiho-sdk"):
            KumihoSystem().reset()
