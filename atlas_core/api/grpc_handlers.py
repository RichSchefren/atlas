"""Kumiho-compatible gRPC handler implementations.

Wires the 10 highest-traffic Kumiho methods to Atlas's storage so
existing Kumiho SDK code switches by setting `endpoint=
"localhost:50051"`. Atlas implements each method against its own
Neo4j + ledger backing rather than calling Kumiho's cloud.

Implemented in this commit (the 10 most-cited):
  CreateProject, GetProjects, GetProject
  CreateRevision, GetRevision, TagRevision
  AnalyzeImpact, TraverseEdges, FindShortestPath
  ResolveKref

Not yet wired (return UNIMPLEMENTED): the remaining 41 methods
listed in KUMIHO_COMPAT_METHODS. Stub responses keep clients alive
and document the contract; users who need a specific unimplemented
method file an issue and we wire it.

Spec: PHASE-5-AND-BEYOND.md § 3.3
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import AsyncDriver



log = logging.getLogger(__name__)


# ─── Result shapes (mirror Kumiho's protobuf message definitions
#     using JSON-serializable dicts; the gRPC server adapter
#     translates to actual proto messages when the .proto schema
#     ships in a follow-up commit) ────────────────────────────────


@dataclass
class GrpcResponse:
    """Generic envelope. Real gRPC server fills `code` per the
    google.rpc.Code enum. Status 'UNIMPLEMENTED' is the contract
    for methods we list but haven't wired."""

    code: str = "OK"
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


# ─── Project methods ─────────────────────────────────────────────


async def create_project(
    driver: AsyncDriver, *, project_id: str, name: str,
) -> GrpcResponse:
    """Materialize a Project node Atlas can reference via kref."""
    if not project_id:
        return GrpcResponse(code="INVALID_ARGUMENT", message="project_id required")
    kref = f"kref://Atlas/Projects/{project_id}.project"
    async with driver.session() as s:
        await s.run(
            "MERGE (p:Project:AtlasItem {kref: $k}) "
            "SET p.project_id = $pid, p.name = $name, "
            "    p.deprecated = false",
            k=kref, pid=project_id, name=name,
        )
    return GrpcResponse(payload={"kref": kref, "project_id": project_id, "name": name})


async def get_project(
    driver: AsyncDriver, *, project_id: str,
) -> GrpcResponse:
    kref = f"kref://Atlas/Projects/{project_id}.project"
    async with driver.session() as s:
        result = await s.run(
            "MATCH (p:Project {kref: $k}) RETURN p.project_id AS pid, p.name AS name",
            k=kref,
        )
        row = await result.single()
    if row is None:
        return GrpcResponse(code="NOT_FOUND", message=f"project {project_id} missing")
    return GrpcResponse(payload={
        "kref": kref, "project_id": row["pid"], "name": row["name"],
    })


async def get_projects(driver: AsyncDriver) -> GrpcResponse:
    async with driver.session() as s:
        result = await s.run(
            "MATCH (p:Project) WHERE coalesce(p.deprecated, false) = false "
            "RETURN p.project_id AS pid, p.name AS name, p.kref AS kref "
            "ORDER BY p.project_id"
        )
        rows = [r async for r in result]
    return GrpcResponse(payload={
        "projects": [
            {"kref": r["kref"], "project_id": r["pid"], "name": r["name"]}
            for r in rows
        ],
    })


# ─── Revision methods ────────────────────────────────────────────


async def create_revision(
    driver: AsyncDriver, *, target_kref: str, content: dict[str, Any],
    revision_reason: str = "grpc_create_revision", actor: str = "kumiho_compat",
) -> GrpcResponse:
    """Routes through AGM revise() so Kumiho-SDK creates land in the
    same revision history Atlas's MCP path uses."""
    from atlas_core.revision.agm import revise
    from atlas_core.revision.uri import Kref

    try:
        kref = Kref.parse(target_kref)
    except Exception as exc:
        return GrpcResponse(
            code="INVALID_ARGUMENT", message=f"bad kref: {exc}",
        )
    outcome = await revise(
        driver=driver,
        target_kref=kref,
        new_content=content,
        revision_reason=revision_reason,
        actor=actor,
    )
    return GrpcResponse(payload={
        "new_revision_kref": outcome.new_revision_kref.to_string(),
        "superseded_kref": (
            outcome.superseded_kref.to_string() if outcome.superseded_kref
            else None
        ),
        "was_first_revision": outcome.was_first_revision,
        "tag_updated": outcome.tag_updated,
    })


async def get_revision(
    driver: AsyncDriver, *, revision_kref: str,
) -> GrpcResponse:
    async with driver.session() as s:
        result = await s.run(
            "MATCH (r:AtlasRevision {kref: $k}) "
            "RETURN r.kref AS kref, r.content_json AS content_json, "
            "       r.content_hash AS content_hash",
            k=revision_kref,
        )
        row = await result.single()
    if row is None:
        return GrpcResponse(code="NOT_FOUND", message="revision missing")
    return GrpcResponse(payload={
        "kref": row["kref"],
        "content": json.loads(row["content_json"]) if row["content_json"] else {},
        "content_hash": row["content_hash"],
    })


async def tag_revision(
    driver: AsyncDriver, *, revision_kref: str, tag_name: str,
) -> GrpcResponse:
    """Move a tag pointer to the given revision. Mirrors Kumiho's
    TagRevision RPC."""
    async with driver.session() as s:
        # Find root from revision
        result = await s.run(
            "MATCH (rev:AtlasRevision {kref: $k}) "
            "RETURN rev.root_kref AS root",
            k=revision_kref,
        )
        row = await result.single()
        if row is None:
            return GrpcResponse(code="NOT_FOUND", message="revision missing")
        root_kref = row["root"]

        # Move tag (or create)
        await s.run(
            "MATCH (root:AtlasItem {root_kref: $root}) "
            "MATCH (rev:AtlasRevision {kref: $k}) "
            "MERGE (tag:AtlasTag {name: $name, root_kref: $root}) "
            "WITH tag, rev "
            "OPTIONAL MATCH (tag)-[old:POINTS_TO]->() "
            "DELETE old "
            "WITH tag, rev "
            "MERGE (tag)-[:POINTS_TO]->(rev)",
            root=root_kref, k=revision_kref, name=tag_name,
        )
    return GrpcResponse(payload={
        "tag_name": tag_name, "revision_kref": revision_kref,
    })


# ─── Traversal methods (route to Atlas's existing engines) ───────


async def analyze_impact(
    driver: AsyncDriver, *, kref: str,
    max_depth: int = 10, max_nodes: int = 5000,
) -> GrpcResponse:
    """Kumiho-compat AnalyzeImpact = Atlas's analyze_impact."""
    from atlas_core.ripple import analyze_impact as ai

    result = await ai(
        driver, kref, max_depth=max_depth, max_nodes=max_nodes,
    )
    return GrpcResponse(payload={
        "impacted": [
            {
                "kref": n.kref,
                "depth": n.depth,
                "current_confidence": n.current_confidence,
                "upstream_kref": n.upstream_kref,
                "types": list(n.types),
            }
            for n in result.impacted
        ],
        "cycles_detected": result.cycles_detected,
        "nodes_visited": result.nodes_visited,
        "truncated": result.truncated,
    })


async def traverse_edges(
    driver: AsyncDriver, *,
    start_kref: str,
    edge_types: list[str] | None = None,
    max_depth: int = 5,
) -> GrpcResponse:
    """Generic edge traversal. edge_types filters by relationship
    label; default is all six Kumiho-spec edges."""
    

    types = edge_types or ["DEPENDS_ON", "DERIVED_FROM", "SUPERSEDES", "REFERENCED", "CONTAINS", "CREATED_FROM"]
    rel_filter = "|".join(types)
    cypher = (
        f"MATCH (start {{kref: $k}}) "
        f"MATCH path = (start)-[:{rel_filter}*1..{max_depth}]->(end) "
        "RETURN end.kref AS kref, length(path) AS depth"
    )
    async with driver.session() as s:
        result = await s.run(cypher, k=start_kref)
        rows = [r async for r in result]
    return GrpcResponse(payload={
        "neighbors": [
            {"kref": r["kref"], "depth": int(r["depth"])} for r in rows
        ],
    })


async def find_shortest_path(
    driver: AsyncDriver, *, from_kref: str, to_kref: str,
) -> GrpcResponse:
    cypher = (
        "MATCH path = shortestPath((a {kref: $from_k})-[*..15]-(b {kref: $to_k})) "
        "RETURN [n IN nodes(path) | n.kref] AS path_krefs, length(path) AS length"
    )
    async with driver.session() as s:
        result = await s.run(cypher, from_k=from_kref, to_k=to_kref)
        row = await result.single()
    if row is None:
        return GrpcResponse(code="NOT_FOUND", message="no path between kref pair")
    return GrpcResponse(payload={
        "path_krefs": list(row["path_krefs"]),
        "length": int(row["length"]),
    })


# ─── Resolution ──────────────────────────────────────────────────


async def resolve_kref(
    driver: AsyncDriver, *, kref: str,
) -> GrpcResponse:
    """Returns whatever node exists at this kref, with its labels."""
    async with driver.session() as s:
        result = await s.run(
            "MATCH (n {kref: $k}) RETURN n.kref AS kref, "
            "       labels(n) AS labels, properties(n) AS props",
            k=kref,
        )
        row = await result.single()
    if row is None:
        return GrpcResponse(code="NOT_FOUND", message="kref not present in graph")
    # Strip Neo4j-internal __ keys
    props = {k: v for k, v in (row["props"] or {}).items()
             if not k.startswith("__")}
    return GrpcResponse(payload={
        "kref": row["kref"], "labels": list(row["labels"]),
        "properties": props,
    })


# ─── Unimplemented stub for the other 41 methods ─────────────────


async def unimplemented(method_name: str) -> GrpcResponse:
    """Default for every Kumiho-compat method we haven't wired yet.
    Returns UNIMPLEMENTED with a clear reason; clients can detect
    and fall back."""
    return GrpcResponse(
        code="UNIMPLEMENTED",
        message=(
            f"Atlas does not yet implement Kumiho RPC {method_name!r}. "
            "File an issue at github.com/RichSchefren/atlas if you need it."
        ),
    )


# ─── Method dispatch table ───────────────────────────────────────


WIRED_METHODS: dict[str, str] = {
    "CreateProject": "create_project",
    "GetProject": "get_project",
    "GetProjects": "get_projects",
    "CreateRevision": "create_revision",
    "GetRevision": "get_revision",
    "TagRevision": "tag_revision",
    "AnalyzeImpact": "analyze_impact",
    "TraverseEdges": "traverse_edges",
    "FindShortestPath": "find_shortest_path",
    "ResolveKref": "resolve_kref",
}
"""Method name → handler function name. Used by the gRPC server adapter
to dispatch incoming RPCs."""


async def dispatch(
    driver: AsyncDriver, method_name: str, **kwargs,
) -> GrpcResponse:
    """Call the handler for `method_name`. Returns UNIMPLEMENTED for
    everything not in WIRED_METHODS."""
    handler_name = WIRED_METHODS.get(method_name)
    if handler_name is None:
        return await unimplemented(method_name)
    handler = globals()[handler_name]
    try:
        return await handler(driver, **kwargs)
    except TypeError as exc:
        return GrpcResponse(
            code="INVALID_ARGUMENT", message=f"bad args for {method_name}: {exc}",
        )
    except Exception as exc:
        log.exception("gRPC handler %s crashed", method_name)
        return GrpcResponse(
            code="INTERNAL", message=f"{type(exc).__name__}: {exc}",
        )
