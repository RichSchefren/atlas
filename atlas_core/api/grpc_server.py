"""gRPC server scaffold — Kumiho-compatible at localhost:50051.

Phase 2 W6 ships the scaffold + endpoint table. Phase 2 W7 wires the 51
Kumiho-compatible RPC methods against Atlas's storage so existing Kumiho
SDK code works by setting `endpoint="localhost:50051"`.

The full method list mirrors Kumiho's SDK (kumiho-SDKs/python/python/kumiho/
client.py) — Atlas implements each against its own Neo4j + ledger backing.

Spec: 05 - Atlas Architecture & Schema § 2
      Kumiho SDK audit: ~/Projects/atlas/notes/kumiho-audit.md § 1.3
"""

from __future__ import annotations

DEFAULT_GRPC_PORT: int = 50051
"""Atlas gRPC port — matches Kumiho's default for drop-in compatibility."""


KUMIHO_COMPAT_METHODS: tuple[str, ...] = (
    # Project
    "CreateProject", "GetProjects", "GetProject", "DeleteProject",
    # Spaces / Items / Revisions
    "CreateSpace", "GetSpace", "CreateItem", "GetItem", "GetItems",
    "CreateRevision", "GetRevision", "GetRevisions", "BatchGetRevisions",
    "DeleteRevision", "PeekNextRevision",
    # Tags
    "TagRevision", "UnTagRevision", "HasTag", "WasTagged",
    # Artifacts
    "CreateArtifact", "GetArtifact", "GetArtifacts",
    "GetArtifactsByLocation", "DeleteArtifact",
    "SetDefaultArtifact", "SetDeprecated",
    # Edges
    "CreateEdge", "GetEdges", "DeleteEdge",
    # Traversal — these route to Atlas's Cypher engine
    "TraverseEdges", "FindShortestPath", "AnalyzeImpact",
    # Bundles
    "CreateBundle", "AddBundleMember", "RemoveBundleMember",
    "GetBundleMembers", "GetBundleHistory",
    # Search
    "ItemSearch", "Search", "ScoreRevisions",
    # Resolution
    "ResolveKref", "ResolveLocation",
    # Attributes
    "SetAttribute", "GetAttribute", "DeleteAttribute",
    # Events / tenant
    "EventStream", "GetEventCapabilities", "GetTenantUsage",
)
"""51 Kumiho RPC methods Atlas implements for SDK drop-in compatibility.
Phase 2 W7 ships the actual handlers; this constant documents the contract."""


def grpc_compat_method_count() -> int:
    """Sanity check — Kumiho's SDK exposes 51 RPC endpoints."""
    return len(KUMIHO_COMPAT_METHODS)
