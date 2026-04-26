"""Atlas MCP server — 8 Atlas-original tools for Claude Code / Cursor / any MCP client.

Phase 2 W6 ships the differentiating tools. The 51 Kumiho-compat tools come
in Phase 2 W7 when we wire the gRPC compatibility layer.

Tool inventory (Atlas-original):
  ripple.analyze_impact     — preview Depends_On cascade for a kref
  ripple.reassess           — produce reassessment proposals (no graph mutation)
  ripple.detect_contradictions — type-aware contradiction scan
  adjudication.queue        — list pending adjudication entries
  adjudication.resolve      — apply Rich's decision via AGM operator
  quarantine.upsert         — push a candidate claim into quarantine
  quarantine.list_pending   — show pending candidates by lane
  ledger.verify_chain       — tamper-detection audit run

Spec: 05 - Atlas Architecture & Schema § 2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from atlas_core.trust import HashChainedLedger, QuarantineStore


log = logging.getLogger(__name__)


# ─── Tool model ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MCPTool:
    """An MCP-compatible tool definition.

    Atlas's tool shape mirrors the official MCP spec (modelcontextprotocol.io):
    name + description + JSON-schema parameters + handler.
    """

    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[..., Awaitable[Any]]


@dataclass
class MCPToolResult:
    """Standardized tool result shape.

    Tools return MCPToolResult so the server can wrap any return value into
    the JSON-RPC envelope MCP clients expect.
    """

    ok: bool
    result: Any = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── Tool inventory (Atlas-original 8) ───────────────────────────────────────


ATLAS_MCP_TOOLS: tuple[str, ...] = (
    "ripple.analyze_impact",
    "ripple.reassess",
    "ripple.detect_contradictions",
    "adjudication.queue",
    "adjudication.resolve",
    "quarantine.upsert",
    "quarantine.list_pending",
    "ledger.verify_chain",
)


# ─── Server ──────────────────────────────────────────────────────────────────


class AtlasMCPServer:
    """Atlas MCP server. Wires the 8 Atlas-original tools to their backends.

    The server is transport-agnostic — `dispatch(tool_name, params)` is the
    single entry point. Production wiring (stdio for Claude Code plugin, HTTP
    for remote clients) is added in W7 adapters; this class is the shared
    business logic.
    """

    def __init__(
        self,
        *,
        driver: AsyncDriver,
        quarantine: QuarantineStore,
        ledger: HashChainedLedger,
    ):
        self.driver = driver
        self.quarantine = quarantine
        self.ledger = ledger
        self._tools: dict[str, MCPTool] = {}
        self._register_atlas_tools()

    def _register_atlas_tools(self) -> None:
        self.register(MCPTool(
            name="ripple.analyze_impact",
            description=(
                "Preview the downstream Depends_On cascade for a revised kref. "
                "Returns ImpactNode list + cycles + nodes_visited. "
                "Read-only — does not mutate the graph."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "kref": {
                        "type": "string",
                        "description": "kref:// of the revised origin",
                    },
                    "max_depth": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 20,
                    },
                    "max_nodes": {
                        "type": "integer",
                        "default": 5000,
                    },
                },
                "required": ["kref"],
            },
            handler=self._tool_analyze_impact,
        ))

        self.register(MCPTool(
            name="ripple.reassess",
            description=(
                "Produce reassessment proposals for downstream dependents "
                "after a confidence shift. Returns proposals (does NOT mutate "
                "graph — caller routes via adjudication.resolve)."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "upstream_kref": {"type": "string"},
                    "old_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "new_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "belief_text": {"type": "string", "default": ""},
                },
                "required": ["upstream_kref", "old_confidence", "new_confidence"],
            },
            handler=self._tool_reassess,
        ))

        self.register(MCPTool(
            name="ripple.detect_contradictions",
            description=(
                "Run type-aware contradiction detection over a list of "
                "reassessment proposals. Returns ContradictionPair list "
                "with category + severity + rationale per pair."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "proposals": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "ReassessmentProposal dicts",
                    },
                },
                "required": ["proposals"],
            },
            handler=self._tool_detect_contradictions,
        ))

        self.register(MCPTool(
            name="adjudication.queue",
            description=(
                "List pending adjudication entries (strategic + core_protected) "
                "by reading the Obsidian markdown queue directory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                },
            },
            handler=self._tool_adjudication_queue,
        ))

        self.register(MCPTool(
            name="adjudication.resolve",
            description=(
                "Apply Rich's decision on a pending adjudication entry. "
                "Routes to AGM revise() for Accept/Adjust, no-op for Reject."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "decision": {
                        "type": "string",
                        "enum": ["accept", "reject", "adjust", "demote_core"],
                    },
                    "adjusted_confidence": {
                        "type": "number",
                        "description": "Required when decision='adjust'",
                    },
                    "actor": {"type": "string", "default": "rich"},
                },
                "required": ["proposal_id", "decision"],
            },
            handler=self._tool_adjudication_resolve,
        ))

        self.register(MCPTool(
            name="quarantine.upsert",
            description=(
                "Push a CandidateClaim into the trust quarantine. Returns "
                "UpsertResult — is_new / is_corroborated / is_auto_promoted "
                "/ trust_score."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "lane": {"type": "string"},
                    "assertion_type": {
                        "type": "string",
                        "enum": [
                            "decision", "preference", "factual_assertion",
                            "episode", "procedure",
                        ],
                    },
                    "subject_kref": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object_value": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_source": {"type": "string"},
                    "evidence_source_family": {"type": "string"},
                    "evidence_kref": {"type": "string"},
                    "evidence_timestamp": {"type": "string"},
                },
                "required": [
                    "lane", "assertion_type", "subject_kref", "predicate",
                    "object_value", "confidence", "evidence_source",
                    "evidence_source_family", "evidence_kref",
                    "evidence_timestamp",
                ],
            },
            handler=self._tool_quarantine_upsert,
        ))

        self.register(MCPTool(
            name="quarantine.list_pending",
            description=(
                "List pending candidates in the trust quarantine, optionally "
                "filtered by lane. Returns up to `limit` rows ordered by age."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "lane": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
            handler=self._tool_quarantine_list_pending,
        ))

        self.register(MCPTool(
            name="ledger.verify_chain",
            description=(
                "Walk the hash-chained ledger from genesis and verify every "
                "event_id matches SHA-256(previous_hash + canonical_payload). "
                "Returns intact: bool + last_verified_sequence + breakage_reason."
            ),
            parameters_schema={"type": "object", "properties": {}},
            handler=self._tool_ledger_verify_chain,
        ))

    # ── Registration + dispatch ─────────────────────────────────────────────

    def register(self, tool: MCPTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"MCP tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def list_tools(self) -> list[dict[str, Any]]:
        """Returns the list of tool definitions in MCP-spec shape."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.parameters_schema,
            }
            for tool in self._tools.values()
        ]

    async def dispatch(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> MCPToolResult:
        """Single entry point. Look up the handler, validate, invoke, wrap."""
        if tool_name not in self._tools:
            return MCPToolResult(
                ok=False, error=f"unknown tool: {tool_name!r}",
            )
        tool = self._tools[tool_name]
        try:
            result = await tool.handler(**params)
            return MCPToolResult(ok=True, result=result)
        except TypeError as exc:
            # Wrong / missing params
            return MCPToolResult(
                ok=False, error=f"invalid params for {tool_name}: {exc}",
            )
        except Exception as exc:
            log.exception("MCP tool %s failed", tool_name)
            return MCPToolResult(
                ok=False, error=f"{type(exc).__name__}: {exc}",
            )

    # ── Tool handlers ───────────────────────────────────────────────────────

    async def _tool_analyze_impact(
        self,
        kref: str,
        max_depth: int = 10,
        max_nodes: int = 5000,
    ) -> dict[str, Any]:
        from atlas_core.ripple import analyze_impact

        result = await analyze_impact(
            self.driver, kref,
            max_depth=max_depth, max_nodes=max_nodes,
        )
        return {
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
        }

    async def _tool_reassess(
        self,
        upstream_kref: str,
        old_confidence: float,
        new_confidence: float,
        belief_text: str = "",
    ) -> dict[str, Any]:
        from atlas_core.ripple import (
            UpstreamChange,
            analyze_impact,
            reassess_cascade,
        )

        impact = await analyze_impact(self.driver, upstream_kref)
        change = UpstreamChange(
            upstream_kref=upstream_kref,
            belief_text=belief_text,
            old_confidence=old_confidence,
            new_confidence=new_confidence,
        )
        proposals = await reassess_cascade(self.driver, impact.impacted, change)
        return {
            "proposals": [
                {
                    "target_kref": p.target_kref,
                    "old_confidence": p.old_confidence,
                    "new_confidence": p.new_confidence,
                    "components": p.components,
                    "llm_rationale": p.llm_rationale,
                    "depth": p.depth,
                }
                for p in proposals
            ],
            "cascade_size": len(proposals),
        }

    async def _tool_detect_contradictions(
        self,
        proposals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from atlas_core.ripple import (
            ReassessmentProposal,
            detect_contradictions,
        )

        # Hydrate proposal dicts
        rebuilt = [
            ReassessmentProposal(
                target_kref=p["target_kref"],
                old_confidence=p.get("old_confidence", 0.5),
                new_confidence=p["new_confidence"],
                components=p.get("components", {}),
                llm_rationale=p.get("llm_rationale", ""),
                upstream_kref=p.get("upstream_kref", ""),
                depth=p.get("depth", 1),
            )
            for p in proposals
        ]
        contras = await detect_contradictions(self.driver, rebuilt)
        return {
            "contradictions": [
                {
                    "proposal_kref": c.proposal_kref,
                    "opposed_kref": c.opposed_kref,
                    "category": c.category.value,
                    "severity": c.severity.value,
                    "rationale": c.rationale,
                }
                for c in contras
            ],
        }

    async def _tool_adjudication_queue(
        self,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List pending markdown files in the adjudication queue directory.

        Phase 2 W6: filesystem listing only. Phase 2 W7 wires fswatch to
        actually parse Rich's resolutions.
        """
        from atlas_core.ripple import DEFAULT_ADJUDICATION_DIR

        if not DEFAULT_ADJUDICATION_DIR.exists():
            return {"entries": [], "directory": str(DEFAULT_ADJUDICATION_DIR)}

        files = sorted(DEFAULT_ADJUDICATION_DIR.glob("*.md"))[:limit]
        return {
            "entries": [
                {"filename": f.name, "path": str(f), "size_bytes": f.stat().st_size}
                for f in files
            ],
            "directory": str(DEFAULT_ADJUDICATION_DIR),
        }

    async def _tool_adjudication_resolve(
        self,
        proposal_id: str,
        decision: str,
        adjusted_confidence: Optional[float] = None,
        actor: str = "rich",
    ) -> dict[str, Any]:
        """Phase 2 W6 stub — full resolver wiring (read markdown frontmatter,
        invoke AGM revise, archive file) lands in Phase 2 W7.

        For now: validates the inputs and returns a recorded-decision shape
        so MCP clients have a stable interface.
        """
        valid_decisions = {"accept", "reject", "adjust", "demote_core"}
        if decision not in valid_decisions:
            raise ValueError(f"decision must be one of {valid_decisions}")
        if decision == "adjust" and adjusted_confidence is None:
            raise ValueError("adjusted_confidence required when decision='adjust'")
        return {
            "proposal_id": proposal_id,
            "decision": decision,
            "actor": actor,
            "adjusted_confidence": adjusted_confidence,
            "applied": False,  # W7 wires the actual AGM operator call
            "note": "Phase 2 W6 stub; AGM operator wiring lands W7",
        }

    async def _tool_quarantine_upsert(
        self,
        lane: str,
        assertion_type: str,
        subject_kref: str,
        predicate: str,
        object_value: str,
        confidence: float,
        evidence_source: str,
        evidence_source_family: str,
        evidence_kref: str,
        evidence_timestamp: str,
    ) -> dict[str, Any]:
        from atlas_core.trust import CandidateClaim, EvidenceRef

        upsert = self.quarantine.upsert_candidate(
            CandidateClaim(
                lane=lane,
                assertion_type=assertion_type,
                subject_kref=subject_kref,
                predicate=predicate,
                object_value=object_value,
                confidence=confidence,
                evidence_ref=EvidenceRef(
                    source=evidence_source,
                    source_family=evidence_source_family,
                    kref=evidence_kref,
                    timestamp=evidence_timestamp,
                ),
            )
        )
        return {
            "candidate_id": upsert.candidate_id,
            "is_new": upsert.is_new,
            "is_corroborated": upsert.is_corroborated,
            "is_auto_promoted": upsert.is_auto_promoted,
            "trust_score": upsert.trust_score,
            "status": upsert.status.value,
        }

    async def _tool_quarantine_list_pending(
        self,
        lane: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        rows = self.quarantine.list_pending(lane=lane)[:limit]
        return {
            "candidates": [
                {
                    "candidate_id": r["candidate_id"],
                    "lane": r["lane"],
                    "subject_kref": r["subject_kref"],
                    "predicate": r["predicate"],
                    "object_value": r["object_value"],
                    "confidence": r["confidence"],
                    "trust_score": r["trust_score"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
            "count": len(rows),
        }

    async def _tool_ledger_verify_chain(self) -> dict[str, Any]:
        result = self.ledger.verify_chain()
        return {
            "intact": result.intact,
            "last_verified_sequence": result.last_verified_sequence,
            "last_verified_event_id": result.last_verified_event_id,
            "broken_at_sequence": result.broken_at_sequence,
            "breakage_reason": result.breakage_reason,
        }
