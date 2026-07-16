"""Authoritative Atlas cognitive service core.

All AGM, traversal, Ripple, contradiction, routing, and idempotency semantics
live in this Python module. SQLite statements are persistence operations only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
from collections import defaultdict, deque
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERVICE_VERSION = "0.1.0"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
ALLOWED_KINDS = frozenset({"fact", "belief"})


class ServiceError(RuntimeError):
    code = "service_error"
    status = 400


class NotFoundError(ServiceError):
    code = "not_found"
    status = 404


class ConflictError(ServiceError):
    code = "conflict"
    status = 409


class IdempotencyConflict(ConflictError):
    code = "idempotency_conflict"


class StaleWriteConflict(ConflictError):
    code = "stale_write_conflict"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def decay_ppm(days: int | None) -> int:
    if days is None:
        return 500_000
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise ServiceError("last_evidence_days must be a nonnegative integer or null")
    return math.floor(1_000_000 * (0.5 ** (days / 90)) + 0.5)


def trunc_div(numerator: int, denominator: int) -> int:
    sign = -1 if numerator < 0 else 1
    return sign * (abs(numerator) // denominator)


def validate_ppm(value: int, *, signed: bool = False, name: str = "value") -> int:
    floor = -1_000_000 if signed else 0
    if isinstance(value, bool) or not isinstance(value, int) or not floor <= value <= 1_000_000:
        raise ServiceError(f"{name} must be an integer between {floor} and 1000000")
    return value


def validate_kind(kind: str) -> str:
    if kind not in ALLOWED_KINDS:
        allowed = ", ".join(sorted(ALLOWED_KINDS))
        raise ServiceError(f"kind must be one of: {allowed}")
    return kind


def validate_cascade_bounds(max_depth: int, max_nodes: int) -> None:
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 0 <= max_depth <= 100:
        raise ServiceError("max_depth must be an integer between 0 and 100")
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or not 1 <= max_nodes <= 100_000:
        raise ServiceError("max_nodes must be an integer between 1 and 100000")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CognitiveServiceCore:
    """Single-scope, thread-safe cognitive service implementation."""

    def __init__(self, database: str | Path, *, scope_id: str):
        if not scope_id:
            raise ValueError("scope_id is required")
        self.scope_id = scope_id
        self.database_path = str(database)
        if self.database_path != ":memory:":
            database_file = Path(self.database_path)
            database_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(database_file.parent, 0o700)
        self.db = sqlite3.connect(
            self.database_path, check_same_thread=False, isolation_level=None,
        )
        if self.database_path != ":memory:":
            os.chmod(self.database_path, 0o600)
        self.db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self.db.rollback()
                raise
            else:
                self.db.commit()

    def health(self) -> dict[str, Any]:
        with self._lock:
            self.db.execute("SELECT 1").fetchone()
        return {
            "status": "ok",
            "service_version": SERVICE_VERSION,
            "api_version": "v1",
            "scope_id": self.scope_id,
            "sqlite_version": sqlite3.sqlite_version,
            "cognitive_owner": "python-service",
        }

    def _item(self, root_kref: str, *, include_deprecated: bool = True) -> sqlite3.Row:
        sql = "SELECT * FROM items WHERE scope_id = ? AND root_kref = ?"
        params: list[Any] = [self.scope_id, root_kref]
        if not include_deprecated:
            sql += " AND deprecated = 0"
        row = self.db.execute(sql, params).fetchone()
        if row is None:
            raise NotFoundError(f"unknown item: {root_kref}")
        return row

    def _request_hash(self, operation: str, request: Mapping[str, Any]) -> str:
        return sha256_text(canonical_json({"operation": operation, "request": request}))

    def _claim_operation(
        self,
        key: str,
        operation: str,
        request_hash: str,
        created_at: str,
    ) -> dict[str, Any] | None:
        if not key:
            raise ServiceError("idempotency_key is required")
        row = self.db.execute(
            "SELECT * FROM operations WHERE scope_id = ? AND idempotency_key = ?",
            (self.scope_id, key),
        ).fetchone()
        if row is not None:
            if row["operation"] != operation or row["request_hash"] != request_hash:
                raise IdempotencyConflict(
                    f"idempotency key {key!r} was already used for different input"
                )
            if row["result_json"] is None:
                raise ConflictError(f"operation {key!r} is incomplete")
            return json.loads(row["result_json"])
        self.db.execute(
            """
            INSERT INTO operations(
              scope_id,idempotency_key,operation,request_hash,result_json,created_at
            ) VALUES(?,?,?,?,NULL,?)
            """,
            (self.scope_id, key, operation, request_hash, created_at),
        )
        return None

    def _finish_operation(self, key: str, result: Mapping[str, Any]) -> None:
        self.db.execute(
            "UPDATE operations SET result_json = ? WHERE scope_id = ? AND idempotency_key = ?",
            (canonical_json(result), self.scope_id, key),
        )

    def _audit(
        self,
        event_type: str,
        root_kref: str,
        *,
        actor: str,
        details: Mapping[str, Any],
        created_at: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO audit_events(
              scope_id,event_type,root_kref,actor,details_json,created_at
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                self.scope_id, event_type, root_kref, actor,
                canonical_json(details), created_at,
            ),
        )

    def _append_revision(
        self,
        item: sqlite3.Row,
        content: Any,
        *,
        kind: str,
        reason: str,
        evidence: Mapping[str, Any],
        actor: str,
        tag: str,
        last_evidence_days: int | None,
        contradicts_prior: bool,
        contradiction_reason: str,
        created_at: str,
    ) -> dict[str, Any]:
        content_json = canonical_json(content)
        content_hash = sha256_text(content_json)
        logical_kref = f"{item['root_kref']}?r={content_hash[:12]}"
        prior = self.db.execute(
            "SELECT revision_id FROM tags WHERE item_id = ? AND name = ?",
            (item["item_id"], tag),
        ).fetchone()
        prior_id = int(prior["revision_id"]) if prior else None
        cursor = self.db.execute(
            """
            INSERT INTO revisions(
              item_id,logical_kref,kind,content_json,content_hash,evidence_json,
              actor,revision_reason,last_evidence_days,contradicts_prior,
              contradiction_reason,supersedes_revision_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item["item_id"], logical_kref, kind, content_json, content_hash,
                canonical_json(evidence), actor, reason, last_evidence_days,
                int(contradicts_prior), contradiction_reason, prior_id, created_at,
            ),
        )
        revision_id = int(cursor.lastrowid)
        self.db.execute(
            """
            INSERT INTO tags(item_id,name,revision_id,moved_at) VALUES(?,?,?,?)
            ON CONFLICT(item_id,name) DO UPDATE SET
              revision_id=excluded.revision_id,moved_at=excluded.moved_at
            """,
            (item["item_id"], tag, revision_id, created_at),
        )
        return self._revision_result(revision_id)

    def _revision_result(self, revision_id: int) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM revisions WHERE revision_id = ?", (revision_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"unknown revision: {revision_id}")
        sequence = self.db.execute(
            "SELECT count(*) FROM revisions WHERE item_id = ? AND revision_id <= ?",
            (row["item_id"], revision_id),
        ).fetchone()[0]
        return {
            "revision_id": revision_id,
            "revision_seq": sequence,
            "logical_kref": row["logical_kref"],
            "kind": row["kind"],
            "content": json.loads(row["content_json"]),
            "content_json": row["content_json"],
            "content_hash": row["content_hash"],
            "evidence": json.loads(row["evidence_json"]),
            "actor": row["actor"],
            "revision_reason": row["revision_reason"],
            "last_evidence_days": row["last_evidence_days"],
            "contradicts_prior": bool(row["contradicts_prior"]),
            "contradiction_reason": row["contradiction_reason"],
            "supersedes_revision_id": row["supersedes_revision_id"],
            "created_at": row["created_at"],
        }

    def create_item(
        self,
        *,
        idempotency_key: str,
        root_kref: str,
        kind: str,
        content: Any,
        confidence_ppm: int,
        hypothesis: str = "",
        stakes: str = "medium",
        is_core_conviction: bool = False,
        last_evidence_days: int | None = None,
        evidence: Mapping[str, Any] | None = None,
        actor: str = "atlas",
        tag: str = "current",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        validate_ppm(confidence_ppm, name="confidence_ppm")
        validate_kind(kind)
        decay_ppm(last_evidence_days)
        timestamp = created_at or utc_now()
        request = {
            "root_kref": root_kref, "kind": kind, "content": content,
            "confidence_ppm": confidence_ppm, "hypothesis": hypothesis,
            "stakes": stakes, "is_core_conviction": is_core_conviction,
            "last_evidence_days": last_evidence_days, "evidence": evidence or {},
            "actor": actor, "tag": tag, "created_at": created_at,
        }
        request_hash = self._request_hash("create", request)
        with self._transaction():
            existing = self._claim_operation(
                idempotency_key, "create", request_hash, timestamp
            )
            if existing is not None:
                return existing
            try:
                cursor = self.db.execute(
                    """
                    INSERT INTO items(
                      scope_id,root_kref,kind,hypothesis,confidence_ppm,stakes,
                      is_core_conviction,last_evidence_days,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        self.scope_id, root_kref, kind, hypothesis, confidence_ppm,
                        stakes, int(is_core_conviction), last_evidence_days, timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"item already exists: {root_kref}") from exc
            item = self.db.execute(
                "SELECT * FROM items WHERE item_id = ?", (cursor.lastrowid,)
            ).fetchone()
            revision = self._append_revision(
                item, content, kind=kind, reason="initial", evidence=evidence or {},
                actor=actor, tag=tag, last_evidence_days=last_evidence_days,
                contradicts_prior=False, contradiction_reason="", created_at=timestamp,
            )
            result = {"item": self._item_summary(item), "revision": revision}
            self._audit(
                "item_created", root_kref, actor=actor,
                details={
                    "revision_id": revision["revision_id"],
                    "confidence_ppm": confidence_ppm,
                },
                created_at=timestamp,
            )
            self._finish_operation(idempotency_key, result)
            return result

    @staticmethod
    def _item_summary(item: sqlite3.Row) -> dict[str, Any]:
        return {
            "root_kref": item["root_kref"], "kind": item["kind"],
            "hypothesis": item["hypothesis"],
            "confidence_ppm": item["confidence_ppm"], "stakes": item["stakes"],
            "is_core_conviction": bool(item["is_core_conviction"]),
            "last_evidence_days": item["last_evidence_days"],
            "deprecated": bool(item["deprecated"]),
        }

    def declare_dependency(
        self,
        dependent_kref: str,
        support_kref: str,
        *,
        strength_ppm: int,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        validate_ppm(strength_ppm, name="strength_ppm")
        timestamp = created_at or utc_now()
        with self._transaction():
            dependent = self._item(dependent_kref, include_deprecated=False)
            support = self._item(support_kref, include_deprecated=False)
            existing = self.db.execute(
                """
                SELECT strength_ppm FROM dependencies
                WHERE dependent_item_id=? AND support_item_id=?
                """,
                (dependent["item_id"], support["item_id"]),
            ).fetchone()
            if existing is not None and int(existing["strength_ppm"]) == strength_ppm:
                return {
                    "dependent_kref": dependent_kref,
                    "support_kref": support_kref,
                    "strength_ppm": strength_ppm,
                }
            self.db.execute(
                """
                INSERT INTO dependencies(
                  dependent_item_id,support_item_id,strength_ppm,created_at
                ) VALUES(?,?,?,?)
                ON CONFLICT(dependent_item_id,support_item_id) DO UPDATE SET
                  strength_ppm=excluded.strength_ppm
                """,
                (dependent["item_id"], support["item_id"], strength_ppm, timestamp),
            )
            self._audit(
                "dependency_declared", dependent_kref, actor="atlas",
                details={
                    "support_kref": support_kref,
                    "strength_ppm": strength_ppm,
                },
                created_at=timestamp,
            )
        return {
            "dependent_kref": dependent_kref, "support_kref": support_kref,
            "strength_ppm": strength_ppm,
        }

    def _cascade_in_transaction(
        self,
        *,
        idempotency_key: str,
        origin: sqlite3.Row,
        old_confidence_ppm: int,
        new_confidence_ppm: int,
        trigger_revision_id: int | None,
        llm_inputs: Sequence[Mapping[str, Any]],
        max_depth: int,
        max_nodes: int,
        created_at: str,
    ) -> dict[str, Any]:
        validate_cascade_bounds(max_depth, max_nodes)
        item_rows = self.db.execute(
            "SELECT * FROM items WHERE scope_id = ? AND deprecated = 0",
            (self.scope_id,),
        ).fetchall()
        items = {int(row["item_id"]): row for row in item_rows}
        edges = self.db.execute(
            """
            SELECT d.* FROM dependencies d
            JOIN items dependent ON dependent.item_id = d.dependent_item_id
            JOIN items support ON support.item_id = d.support_item_id
            WHERE dependent.scope_id = ? AND support.scope_id = ?
              AND dependent.deprecated = 0 AND support.deprecated = 0
            ORDER BY d.support_item_id, d.dependent_item_id
            """,
            (self.scope_id, self.scope_id),
        ).fetchall()
        incoming: dict[int, list[tuple[int, int]]] = defaultdict(list)
        strengths: dict[tuple[int, int], int] = {}
        for edge in edges:
            child = int(edge["dependent_item_id"])
            parent = int(edge["support_item_id"])
            incoming[parent].append((child, int(edge["strength_ppm"])))
            strengths[(child, parent)] = int(edge["strength_ppm"])
        for children in incoming.values():
            children.sort(key=lambda pair: items[pair[0]]["root_kref"])

        origin_id = int(origin["item_id"])
        visited = {origin_id}
        queue: deque[tuple[int, int]] = deque([(origin_id, 0)])
        impacted: list[tuple[int, int, int]] = []
        truncated = False
        while queue:
            parent, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for child, _ in incoming.get(parent, []):
                if child in visited:
                    continue
                if len(impacted) >= max_nodes:
                    truncated = True
                    queue.clear()
                    break
                visited.add(child)
                impacted.append((child, parent, depth + 1))
                queue.append((child, depth + 1))

        # Detect actual directed cycles independently from BFS de-duplication.
        # A repeated node in a diamond is convergence, not a cycle. A DFS edge
        # to an active ancestor is the precise back-edge signal.
        colors: dict[int, int] = {origin_id: 1}
        cycles: list[dict[str, str]] = []
        stack: list[tuple[int, int]] = [(origin_id, 0)]
        while stack:
            node, child_index = stack[-1]
            children = incoming.get(node, [])
            if child_index >= len(children):
                colors[node] = 2
                stack.pop()
                continue
            stack[-1] = (node, child_index + 1)
            child = children[child_index][0]
            if child not in visited:
                continue
            state = colors.get(child, 0)
            if state == 0:
                colors[child] = 1
                stack.append((child, 0))
            elif state == 1:
                cycles.append({
                    "from": items[node]["root_kref"],
                    "to": items[child]["root_kref"],
                })

        llm_by_kref = {str(row["target_kref"]): row for row in llm_inputs}
        deltas = {origin_id: new_confidence_ppm - old_confidence_ppm}
        proposal_rows: list[tuple[Any, ...]] = []
        proposals: list[dict[str, Any]] = []
        trigger_contradiction = False
        if trigger_revision_id is not None:
            revision = self.db.execute(
                "SELECT contradicts_prior FROM revisions WHERE revision_id = ?",
                (trigger_revision_id,),
            ).fetchone()
            trigger_contradiction = bool(revision and revision["contradicts_prior"])

        cursor = self.db.execute(
            """
            INSERT INTO cascades(
              scope_id,idempotency_key,origin_item_id,trigger_revision_id,
              old_confidence_ppm,new_confidence_ppm,nodes_visited,truncated,
              cycles_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                self.scope_id, idempotency_key, origin_id, trigger_revision_id,
                old_confidence_ppm, new_confidence_ppm, len(visited), int(truncated),
                canonical_json(cycles), created_at,
            ),
        )
        cascade_id = int(cursor.lastrowid)
        for sequence, (target_id, upstream_id, depth) in enumerate(impacted, start=1):
            target = items[target_id]
            parent_delta = deltas[upstream_id]
            llm_input = llm_by_kref.get(target["root_kref"])
            if llm_input is None:
                llm_delta = max(-500_000, min(500_000, parent_delta))
                rationale = "service heuristic"
            else:
                llm_delta = validate_ppm(
                    int(llm_input["llm_delta_ppm"]), signed=True,
                    name="llm_delta_ppm",
                )
                rationale = str(llm_input.get("llm_rationale", "external input"))
            strength = strengths[(target_id, upstream_id)]
            beta = trunc_div(300_000 * strength * parent_delta, 1_000_000_000_000)
            gamma = trunc_div(150_000 * llm_delta, 1_000_000)
            delta = trunc_div(
                50_000 * (decay_ppm(target["last_evidence_days"]) - 500_000),
                1_000_000,
            )
            perturbation = beta + gamma + delta
            damped = trunc_div(500_000 * perturbation, 1_000_000)
            old = int(target["confidence_ppm"])
            new = max(0, min(1_000_000, old + damped))
            deltas[target_id] = new - old
            confidence_delta = abs(new - old)
            if target["is_core_conviction"]:
                route = "core_protected"
            elif trigger_contradiction:
                route = "strategic_review"
            elif target["stakes"] in {"high", "critical"}:
                route = "strategic_review"
            elif confidence_delta >= 150_000:
                route = "strategic_review"
            else:
                route = "auto_apply"
            logical = canonical_json({
                "service_version": SERVICE_VERSION,
                "cascade_key": idempotency_key,
                "sequence": sequence,
                "target_kref": target["root_kref"],
                "upstream_kref": items[upstream_id]["root_kref"],
                "depth": depth,
                "old_confidence_ppm": old,
                "new_confidence_ppm": new,
                "components_ppm": {
                    "beta": beta, "gamma": gamma, "delta": delta,
                    "perturbation": perturbation, "damped": damped,
                },
                "llm_delta_ppm": llm_delta,
                "contradiction_detected": trigger_contradiction,
                "route": route,
            })
            proposal_id = sha256_text(logical)
            proposal = {
                "proposal_id": proposal_id, "sequence": sequence,
                "target_kref": target["root_kref"],
                "upstream_kref": items[upstream_id]["root_kref"], "depth": depth,
                "old_confidence_ppm": old, "new_confidence_ppm": new,
                "components_ppm": {
                    "beta": beta, "gamma": gamma, "delta": delta,
                    "perturbation": perturbation, "damped": damped,
                },
                "llm_delta_ppm": llm_delta, "llm_rationale": rationale,
                "contradiction_detected": trigger_contradiction,
                "route": route, "status": "pending",
                "canonical_output": logical,
            }
            proposals.append(proposal)
            proposal_rows.append((
                proposal_id, cascade_id, sequence, target_id, upstream_id, depth,
                old, new, beta, gamma, delta, perturbation, damped, llm_delta,
                rationale, int(trigger_contradiction), route, "pending", logical,
                created_at,
            ))
        self.db.executemany(
            """
            INSERT INTO proposals(
              proposal_id,cascade_id,sequence,target_item_id,upstream_item_id,depth,
              old_confidence_ppm,new_confidence_ppm,beta_ppm,gamma_ppm,delta_ppm,
              perturbation_ppm,damped_ppm,llm_delta_ppm,llm_rationale,
              contradiction_detected,route,status,canonical_output,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            proposal_rows,
        )
        self._audit(
            "cascade_created", origin["root_kref"], actor="atlas",
            details={
                "cascade_id": cascade_id,
                "idempotency_key": idempotency_key,
                "old_confidence_ppm": old_confidence_ppm,
                "new_confidence_ppm": new_confidence_ppm,
                "impacted_count": len(impacted),
                "truncated": truncated,
            },
            created_at=created_at,
        )
        return {
            "cascade_id": cascade_id, "idempotency_key": idempotency_key,
            "origin_kref": origin["root_kref"], "nodes_visited": len(visited),
            "impacted_count": len(impacted), "truncated": truncated,
            "cycles": cycles, "proposals": proposals,
        }

    def revise_item(
        self,
        *,
        idempotency_key: str,
        root_kref: str,
        content: Any,
        revision_reason: str,
        old_confidence_ppm: int,
        new_confidence_ppm: int,
        contradicts_prior: bool = False,
        contradiction_reason: str = "",
        kind: str | None = None,
        last_evidence_days: int | None = None,
        evidence: Mapping[str, Any] | None = None,
        actor: str = "atlas",
        tag: str = "current",
        run_cascade: bool = True,
        llm_inputs: Sequence[Mapping[str, Any]] = (),
        max_depth: int = 10,
        max_nodes: int = 5000,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        validate_ppm(old_confidence_ppm, name="old_confidence_ppm")
        validate_ppm(new_confidence_ppm, name="new_confidence_ppm")
        validate_cascade_bounds(max_depth, max_nodes)
        if not isinstance(revision_reason, str) or not revision_reason.strip():
            raise ServiceError("revision_reason is required")
        if kind is not None:
            validate_kind(kind)
        if last_evidence_days is not None:
            decay_ppm(last_evidence_days)
        timestamp = created_at or utc_now()
        request = {
            "root_kref": root_kref, "content": content,
            "revision_reason": revision_reason,
            "new_confidence_ppm": new_confidence_ppm,
            "contradicts_prior": contradicts_prior,
            "contradiction_reason": contradiction_reason, "kind": kind,
            "last_evidence_days": last_evidence_days, "evidence": evidence or {},
            "actor": actor, "tag": tag, "run_cascade": run_cascade,
            "llm_inputs": list(llm_inputs), "max_depth": max_depth,
            "max_nodes": max_nodes, "created_at": created_at,
        }
        request_hash = self._request_hash("revise", request)
        with self._transaction():
            existing = self._claim_operation(
                idempotency_key, "revise", request_hash, timestamp
            )
            if existing is not None:
                return existing
            item = self._item(root_kref, include_deprecated=False)
            if int(item["confidence_ppm"]) != old_confidence_ppm:
                raise StaleWriteConflict(
                    "old_confidence_ppm does not match persisted current confidence"
                )
            revision_kind = kind or item["kind"]
            evidence_days = (
                last_evidence_days
                if last_evidence_days is not None
                else item["last_evidence_days"]
            )
            self.db.execute(
                """
                UPDATE items SET kind=?, confidence_ppm=?, last_evidence_days=?
                WHERE item_id=?
                """,
                (revision_kind, new_confidence_ppm, evidence_days, item["item_id"]),
            )
            item = self._item(root_kref)
            revision = self._append_revision(
                item, content, kind=revision_kind, reason=revision_reason,
                evidence=evidence or {}, actor=actor, tag=tag,
                last_evidence_days=evidence_days,
                contradicts_prior=contradicts_prior,
                contradiction_reason=contradiction_reason, created_at=timestamp,
            )
            result: dict[str, Any] = {
                "item": self._item_summary(item), "revision": revision,
            }
            if run_cascade:
                result["cascade"] = self._cascade_in_transaction(
                    idempotency_key=f"{idempotency_key}:cascade",
                    origin=item, old_confidence_ppm=old_confidence_ppm,
                    new_confidence_ppm=new_confidence_ppm,
                    trigger_revision_id=revision["revision_id"],
                    llm_inputs=llm_inputs, max_depth=max_depth, max_nodes=max_nodes,
                    created_at=timestamp,
                )
            self._audit(
                "item_revised", root_kref, actor=actor,
                details={
                    "revision_id": revision["revision_id"],
                    "idempotency_key": idempotency_key,
                    "old_confidence_ppm": old_confidence_ppm,
                    "new_confidence_ppm": new_confidence_ppm,
                    "contradicts_prior": contradicts_prior,
                },
                created_at=timestamp,
            )
            self._finish_operation(idempotency_key, result)
            return result

    def run_cascade(
        self,
        *,
        idempotency_key: str,
        origin_kref: str,
        old_confidence_ppm: int,
        new_confidence_ppm: int,
        llm_inputs: Sequence[Mapping[str, Any]] = (),
        max_depth: int = 10,
        max_nodes: int = 5000,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        validate_ppm(old_confidence_ppm, name="old_confidence_ppm")
        validate_ppm(new_confidence_ppm, name="new_confidence_ppm")
        validate_cascade_bounds(max_depth, max_nodes)
        timestamp = created_at or utc_now()
        request = {
            "origin_kref": origin_kref,
            "old_confidence_ppm": old_confidence_ppm,
            "new_confidence_ppm": new_confidence_ppm,
            "llm_inputs": list(llm_inputs), "max_depth": max_depth,
            "max_nodes": max_nodes, "created_at": created_at,
        }
        request_hash = self._request_hash("cascade", request)
        with self._transaction():
            existing = self._claim_operation(
                idempotency_key, "cascade", request_hash, timestamp
            )
            if existing is not None:
                return existing
            origin = self._item(origin_kref, include_deprecated=False)
            result = self._cascade_in_transaction(
                idempotency_key=idempotency_key, origin=origin,
                old_confidence_ppm=old_confidence_ppm,
                new_confidence_ppm=new_confidence_ppm,
                trigger_revision_id=None, llm_inputs=llm_inputs,
                max_depth=max_depth, max_nodes=max_nodes, created_at=timestamp,
            )
            self._finish_operation(idempotency_key, result)
            return result

    def get_item(self, root_kref: str) -> dict[str, Any]:
        with self._lock:
            item = self._item(root_kref, include_deprecated=False)
            revisions = self.db.execute(
                "SELECT revision_id FROM revisions WHERE item_id=? ORDER BY revision_id",
                (item["item_id"],),
            ).fetchall()
            current = self.db.execute(
                """
                SELECT r.revision_id FROM tags t JOIN revisions r
                  ON r.revision_id=t.revision_id
                WHERE t.item_id=? AND t.name='current'
                """,
                (item["item_id"],),
            ).fetchone()
            dependencies = self.db.execute(
                """
                SELECT support.root_kref,d.strength_ppm
                FROM dependencies d JOIN items support
                  ON support.item_id=d.support_item_id
                WHERE d.dependent_item_id=? ORDER BY support.root_kref
                """,
                (item["item_id"],),
            ).fetchall()
            proposals = self.db.execute(
                """
                SELECT p.proposal_id,p.route,p.status,p.canonical_output
                FROM proposals p WHERE p.target_item_id=?
                ORDER BY p.created_at,p.proposal_id
                """,
                (item["item_id"],),
            ).fetchall()
            return {
                "item": self._item_summary(item),
                "current_revision": (
                    self._revision_result(current["revision_id"]) if current else None
                ),
                "lineage": [self._revision_result(row["revision_id"]) for row in revisions],
                "dependencies": [dict(row) for row in dependencies],
                "proposals": [
                    {
                        "proposal_id": row["proposal_id"], "route": row["route"],
                        "status": row["status"],
                        "canonical_output": row["canonical_output"],
                    }
                    for row in proposals
                ],
            }

    def list_items(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 10_000:
            raise ServiceError("limit must be between 1 and 10000")
        with self._lock:
            rows = self.db.execute(
                """
                SELECT i.*,r.content_json FROM items i
                LEFT JOIN tags t ON t.item_id=i.item_id AND t.name='current'
                LEFT JOIN revisions r ON r.revision_id=t.revision_id
                WHERE i.scope_id=? AND i.deprecated=0
                ORDER BY root_kref LIMIT ?
                """,
                (self.scope_id, limit),
            ).fetchall()
            return [
                {
                    **self._item_summary(row),
                    "content": (
                        json.loads(row["content_json"])
                        if row["content_json"] is not None else None
                    ),
                    "content_json": row["content_json"],
                }
                for row in rows
            ]

    def search_items(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
            raise ServiceError("limit must be an integer between 1 and 10000")
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return []
        with self._lock:
            rows = self.db.execute(
                """
                SELECT i.*,r.content_json FROM items i
                JOIN tags t ON t.item_id=i.item_id AND t.name='current'
                JOIN revisions r ON r.revision_id=t.revision_id
                WHERE i.scope_id=? AND i.deprecated=0
                """,
                (self.scope_id,),
            ).fetchall()
        scored = []
        for row in rows:
            haystack = f"{row['root_kref']} {row['hypothesis']} {row['content_json']}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                scored.append((score, row["root_kref"], row))
        scored.sort(key=lambda entry: (-entry[0], entry[1]))
        return [
            {
                **self._item_summary(row), "score": score,
                "content": json.loads(row["content_json"]),
                "content_json": row["content_json"],
            }
            for score, _, row in scored[:limit]
        ]

    def audit_item(self, root_kref: str) -> dict[str, Any]:
        """Return durable provenance, including deprecated items and moved tags."""
        with self._lock:
            item = self._item(root_kref, include_deprecated=True)
            revisions = self.db.execute(
                "SELECT revision_id FROM revisions WHERE item_id=? ORDER BY revision_id",
                (item["item_id"],),
            ).fetchall()
            tags = self.db.execute(
                """
                SELECT t.name,t.revision_id,t.moved_at,r.logical_kref
                FROM tags t JOIN revisions r ON r.revision_id=t.revision_id
                WHERE t.item_id=? ORDER BY t.name
                """,
                (item["item_id"],),
            ).fetchall()
            events = self.db.execute(
                """
                SELECT event_id,event_type,actor,details_json,created_at
                FROM audit_events
                WHERE scope_id=? AND root_kref=? ORDER BY event_id
                """,
                (self.scope_id, root_kref),
            ).fetchall()
            return {
                "item": self._item_summary(item),
                "tags": [dict(row) for row in tags],
                "lineage": [
                    self._revision_result(row["revision_id"]) for row in revisions
                ],
                "audit_events": [
                    {
                        "event_id": row["event_id"],
                        "event_type": row["event_type"],
                        "actor": row["actor"],
                        "details": json.loads(row["details_json"]),
                        "created_at": row["created_at"],
                    }
                    for row in events
                ],
            }

    def forget_item(
        self,
        root_kref: str,
        proposition: str,
        *,
        reason: str,
        actor: str = "atlas",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        timestamp = created_at or utc_now()
        with self._transaction():
            item = self._item(root_kref)
            if item["deprecated"]:
                event = self.db.execute(
                    """
                    SELECT details_json FROM audit_events
                    WHERE scope_id=? AND root_kref=? AND event_type='item_forgotten'
                    ORDER BY event_id LIMIT 1
                    """,
                    (self.scope_id, root_kref),
                ).fetchone()
                details = json.loads(event["details_json"]) if event else {}
                return details.get("result", {
                    "root_kref": root_kref,
                    "deprecated": True,
                    "tags_removed": details.get("tags_removed", []),
                })
            tags = self.db.execute(
                """
                SELECT t.name,r.content_json FROM tags t JOIN revisions r
                  ON r.revision_id=t.revision_id WHERE t.item_id=?
                """,
                (item["item_id"],),
            ).fetchall()
            removed = [row["name"] for row in tags if proposition in row["content_json"]]
            for tag in removed:
                self.db.execute(
                    "DELETE FROM tags WHERE item_id=? AND name=?", (item["item_id"], tag)
                )
            self.db.execute(
                """
                UPDATE items SET deprecated=1,deprecated_at=?,deprecation_reason=?,
                  deprecated_by=? WHERE item_id=?
                """,
                (timestamp, reason, actor, item["item_id"]),
            )
            result = {
                "root_kref": root_kref,
                "deprecated": True,
                "tags_removed": removed,
            }
            self._audit(
                "item_forgotten", root_kref, actor=actor,
                details={
                    "proposition": proposition,
                    "reason": reason,
                    "tags_removed": removed,
                    "result": result,
                },
                created_at=timestamp,
            )
        return result

    def reset_scope(self) -> dict[str, int]:
        with self._transaction():
            item_ids = [
                row[0] for row in self.db.execute(
                    "SELECT item_id FROM items WHERE scope_id=?", (self.scope_id,)
                )
            ]
            count = len(item_ids)
            self.db.execute("DELETE FROM operations WHERE scope_id=?", (self.scope_id,))
            self.db.execute("DELETE FROM cascades WHERE scope_id=?", (self.scope_id,))
            self.db.execute("DELETE FROM audit_events WHERE scope_id=?", (self.scope_id,))
            if item_ids:
                placeholders = ",".join("?" for _ in item_ids)
                self.db.execute(
                    f"DELETE FROM dependencies WHERE dependent_item_id IN ({placeholders})",
                    item_ids,
                )
                self.db.execute(
                    f"DELETE FROM tags WHERE item_id IN ({placeholders})", item_ids
                )
                self.db.execute(
                    f"DELETE FROM revisions WHERE item_id IN ({placeholders})", item_ids
                )
                self.db.execute(
                    f"DELETE FROM items WHERE item_id IN ({placeholders})", item_ids
                )
        return {"items_deleted": count}

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def __enter__(self) -> CognitiveServiceCore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
