"""Black-box conformance proof for the authoritative localhost service.

The suite intentionally talks only to the authenticated HTTP API.  It never
imports service_core and never reads SQLite, so a passing result proves the
same boundary Hermes uses in production and OpenClaw must clear before
claiming cognition.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "integrations" / "cognitive-service" / "server.py"
VECTORS = REPO / "integrations" / "cognitive-service" / "vectors"
PYTHON_CLIENT = REPO / "integrations" / "cognitive-service" / "clients" / "python_client.py"
NODE_CLIENT = REPO / "integrations" / "cognitive-service" / "clients" / "node-client.mjs"
TOKEN_A = "atlas-service-test-token-a-0000000000000000"
TOKEN_B = "atlas-service-test-token-b-0000000000000000"


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _api(
    base_url: str,
    token: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    encoded = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url + path, data=encoded, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


class Service:
    def __init__(
        self,
        tmp_path: Path,
        *,
        scope: str = "profile-test-a",
        token: str = TOKEN_A,
        database: Path | None = None,
    ) -> None:
        self.scope = scope
        self.token = token
        self.database = database or tmp_path / "cognitive.sqlite3"
        self.port = _port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> Service:
        env = {**os.environ, "ATLAS_COGNITIVE_TOKEN": self.token}
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(SERVICE),
                "--db",
                str(self.database),
                "--scope",
                self.scope,
                "--port",
                str(self.port),
                "--allow-test-reset",
            ],
            cwd=REPO,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate()
                raise RuntimeError(f"service exited during startup: {stdout}\n{stderr}")
            try:
                status, payload = _api(self.base_url, self.token, "GET", "/v1/health")
                if status == 200 and payload.get("ok") is True:
                    return self
            except OSError:
                pass
            time.sleep(0.03)
        self.stop()
        raise RuntimeError("service did not become ready")

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None

    def restart(self) -> None:
        self.stop()
        self.port = _port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.start()

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None, *, token: str | None = None
    ) -> tuple[int, dict[str, Any]]:
        return _api(self.base_url, token or self.token, method, path, body)


@pytest.fixture
def service(tmp_path: Path):
    running = Service(tmp_path).start()
    try:
        yield running
    finally:
        running.stop()


def _ok(result: tuple[int, dict[str, Any]], status: int = 200) -> Any:
    actual_status, payload = result
    assert actual_status == status, payload
    assert payload["api_version"] == "v1"
    assert payload["ok"] is True
    return payload["data"]


def _get(service: Service, root_kref: str, route: str = "get") -> tuple[int, dict[str, Any]]:
    query = urllib.parse.urlencode({"root_kref": root_kref})
    return service.request("GET", f"/v1/items/{route}?{query}")


def _create_body(
    key: str,
    root: str,
    content: Any,
    *,
    confidence: int = 800_000,
    created_at: str = "2026-01-01T00:00:01.000000Z",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "idempotency_key": key,
        "root_kref": root,
        "kind": "fact",
        "content": content,
        "confidence_ppm": confidence,
        "created_at": created_at,
        **extra,
    }


def test_health_authentication_and_launch_fixed_scope(service: Service) -> None:
    health = _ok(service.request("GET", "/v1/health"))
    assert health == {
        **health,
        "status": "ok",
        "api_version": "v1",
        "scope_id": "profile-test-a",
        "cognitive_owner": "python-service",
    }
    status, payload = service.request("GET", "/v1/health", token=TOKEN_B)
    assert (status, payload["error"]["code"]) == (401, "unauthorized")
    status, payload = service.request(
        "POST",
        "/v1/items/create",
        {**_create_body("scope-forbidden", "kref://scope/forbidden", {}), "scope_id": "other"},
    )
    assert status == 400
    assert "scope_id" in payload["error"]["message"]


def test_unicode_scalar_key_canonicalization(service: Service) -> None:
    vector = json.loads((VECTORS / "service-boundary.json").read_text())["unicode_scalar_keys"]
    data = _ok(
        service.request(
            "POST",
            "/v1/items/create",
            _create_body("unicode-scalar-key", vector["root_kref"], vector["content"]),
        ),
        201,
    )
    assert data["revision"]["content_json"] == vector["expected_canonical_content"]


@pytest.mark.parametrize("invalid_limit", [0, -1, 10_001, True, 1.5])
def test_public_search_limit_validation(
    service: Service,
    invalid_limit: object,
) -> None:
    status, payload = service.request(
        "POST",
        "/v1/items/search",
        {"query": "anything", "limit": invalid_limit},
    )
    assert (status, payload["error"]["code"]) == (400, "service_error")


def test_public_revision_provenance_on_responses_and_audit_lineage(
    service: Service,
) -> None:
    root = "kref://provenance/fact"
    created = _ok(
        service.request(
            "POST",
            "/v1/items/create",
            _create_body(
                "provenance-create",
                root,
                {"version": 1},
                actor="source-agent",
            ),
        ),
        201,
    )
    assert created["revision"]["actor"] == "source-agent"
    assert created["revision"]["revision_reason"] == "initial"

    revised = _ok(
        service.request(
            "POST",
            "/v1/items/revise",
            {
                "idempotency_key": "provenance-revise",
                "root_kref": root,
                "content": {"version": 2},
                "revision_reason": "verified correction",
                "old_confidence_ppm": 800_000,
                "new_confidence_ppm": 700_000,
                "actor": "review-agent",
                "run_cascade": False,
            },
        )
    )
    assert revised["revision"]["actor"] == "review-agent"
    assert revised["revision"]["revision_reason"] == "verified correction"

    audit = _ok(_get(service, root, route="audit"))
    assert [revision["actor"] for revision in audit["lineage"]] == [
        "source-agent",
        "review-agent",
    ]
    assert [revision["revision_reason"] for revision in audit["lineage"]] == [
        "initial",
        "verified correction",
    ]
    revised_event = next(
        event for event in audit["audit_events"]
        if event["event_type"] == "item_revised"
    )
    assert revised_event["details"]["idempotency_key"] == "provenance-revise"
    assert revised_event["details"]["revision_id"] == audit["lineage"][-1][
        "revision_id"
    ]


def test_public_cascade_ignores_forgotten_dependency_endpoints(
    service: Service,
) -> None:
    dependent_support = "kref://forgotten-dependent/support"
    forgotten_dependent = "kref://forgotten-dependent/dependent"
    for key, root in (
        ("forgotten-dependent-support", dependent_support),
        ("forgotten-dependent-item", forgotten_dependent),
    ):
        _ok(service.request(
            "POST", "/v1/items/create", _create_body(key, root, {"root": root})
        ), 201)
    _ok(service.request("POST", "/v1/dependencies", {
        "dependent_kref": forgotten_dependent,
        "support_kref": dependent_support,
        "strength_ppm": 1_000_000,
    }), 201)
    _ok(service.request("POST", "/v1/items/forget", {
        "root_kref": forgotten_dependent,
        "proposition": "root",
        "reason": "deprecated dependent",
    }))
    dependent_result = _ok(service.request("POST", "/v1/cascades", {
        "idempotency_key": "cascade-forgotten-dependent",
        "origin_kref": dependent_support,
        "old_confidence_ppm": 800_000,
        "new_confidence_ppm": 500_000,
    }), 201)
    assert dependent_result["nodes_visited"] == 1
    assert dependent_result["impacted_count"] == 0
    assert dependent_result["proposals"] == []

    forgotten_support = "kref://forgotten-support/support"
    active_dependent = "kref://forgotten-support/dependent"
    for key, root in (
        ("forgotten-support-item", forgotten_support),
        ("forgotten-support-dependent", active_dependent),
    ):
        _ok(service.request(
            "POST", "/v1/items/create", _create_body(key, root, {"root": root})
        ), 201)
    _ok(service.request("POST", "/v1/dependencies", {
        "dependent_kref": active_dependent,
        "support_kref": forgotten_support,
        "strength_ppm": 1_000_000,
    }), 201)
    _ok(service.request("POST", "/v1/items/forget", {
        "root_kref": forgotten_support,
        "proposition": "root",
        "reason": "deprecated support",
    }))
    support_result = _ok(service.request("POST", "/v1/cascades", {
        "idempotency_key": "cascade-forgotten-support",
        "origin_kref": active_dependent,
        "old_confidence_ppm": 800_000,
        "new_confidence_ppm": 500_000,
    }), 201)
    assert support_result["nodes_visited"] == 1
    assert support_result["impacted_count"] == 0
    assert support_result["proposals"] == []


def test_public_dependency_exact_replay_is_audit_idempotent(
    service: Service,
) -> None:
    support = "kref://dependency-replay/support"
    dependent = "kref://dependency-replay/dependent"
    for key, root in (("dependency-replay-a", support), ("dependency-replay-b", dependent)):
        _ok(service.request(
            "POST", "/v1/items/create", _create_body(key, root, {"root": root})
        ), 201)
    body = {
        "dependent_kref": dependent,
        "support_kref": support,
        "strength_ppm": 900_000,
    }
    first = service.request("POST", "/v1/dependencies", body)
    retry = service.request("POST", "/v1/dependencies", body)
    assert retry == first
    assert first[0] == 201
    audit = _ok(_get(service, dependent, route="audit"))
    assert sum(
        event["event_type"] == "dependency_declared"
        for event in audit["audit_events"]
    ) == 1

    changed = _ok(service.request(
        "POST", "/v1/dependencies", {**body, "strength_ppm": 700_000}
    ), 201)
    assert changed["strength_ppm"] == 700_000
    audit = _ok(_get(service, dependent, route="audit"))
    assert sum(
        event["event_type"] == "dependency_declared"
        for event in audit["audit_events"]
    ) == 2


def test_public_revise_rejects_deprecated_item_without_mutation(
    service: Service,
) -> None:
    root = "kref://deprecated-revision/fact"
    _ok(service.request(
        "POST", "/v1/items/create",
        _create_body("deprecated-revision-create", root, {"version": 1}),
    ), 201)
    _ok(service.request("POST", "/v1/items/forget", {
        "root_kref": root,
        "proposition": "version",
        "reason": "retired fact",
    }))
    before = _ok(_get(service, root, route="audit"))
    status, payload = service.request("POST", "/v1/items/revise", {
        "idempotency_key": "deprecated-revision-attempt",
        "root_kref": root,
        "content": {"version": 2},
        "revision_reason": "must not restore",
        "old_confidence_ppm": 800_000,
        "new_confidence_ppm": 500_000,
    })
    assert (status, payload["error"]["code"]) == (404, "not_found")
    assert _ok(_get(service, root, route="audit")) == before


def test_create_and_revise_idempotency(service: Service) -> None:
    vectors = json.loads((VECTORS / "service-boundary.json").read_text())
    create = vectors["create_idempotency"]
    create_body = _create_body(
        create["idempotency_key"], create["root_kref"], create["content"]
    )
    first = service.request("POST", "/v1/items/create", create_body)
    second = service.request("POST", "/v1/items/create", create_body)
    assert first == second
    assert first[0] == 201
    status, payload = service.request(
        "POST", "/v1/items/create", {**create_body, "content": create["conflicting_content"]}
    )
    assert (status, payload["error"]["code"]) == (409, "idempotency_conflict")

    revise = vectors["revise_idempotency"]
    _ok(
        service.request(
            "POST",
            "/v1/items/create",
            _create_body(revise["create_key"], revise["root_kref"], revise["initial_content"]),
        ),
        201,
    )
    revise_body = {
        "idempotency_key": revise["revise_key"],
        "root_kref": revise["root_kref"],
        "content": revise["revised_content"],
        "revision_reason": "idempotency proof",
        "old_confidence_ppm": 800_000,
        "new_confidence_ppm": 700_000,
        "run_cascade": False,
        "created_at": "2026-01-01T00:00:02.000000Z",
    }
    first = service.request("POST", "/v1/items/revise", revise_body)
    second = service.request("POST", "/v1/items/revise", revise_body)
    assert first == second
    assert len(_ok(_get(service, revise["root_kref"]))["lineage"]) == 2
    status, payload = service.request(
        "POST", "/v1/items/revise", {**revise_body, "content": revise["conflicting_content"]}
    )
    assert (status, payload["error"]["code"]) == (409, "idempotency_conflict")


def _build_cascade(service: Service) -> tuple[dict[str, Any], dict[str, Any]]:
    vector = json.loads((VECTORS / "cascade-ab.json").read_text())
    a_root, b_root = "kref://cascade/A", "kref://cascade/B"
    _ok(service.request("POST", "/v1/items/create", _create_body(
        "ab-create-a", a_root, {"price_usd": 2995}, confidence=920_000
    )), 201)
    _ok(service.request("POST", "/v1/items/create", _create_body(
        "ab-create-b", b_root, {"claim": "belief B depends on A"}, confidence=880_000,
        created_at="2026-01-01T00:00:02.000000Z", kind="belief", last_evidence_days=0,
    )), 201)
    _ok(service.request("POST", "/v1/dependencies", {
        "dependent_kref": b_root,
        "support_kref": a_root,
        "strength_ppm": 950_000,
        "created_at": "2026-01-01T00:00:03.000000Z",
    }), 201)
    data = _ok(service.request("POST", "/v1/items/revise", {
        "idempotency_key": vector["expected"]["cascade_key"],
        "root_kref": a_root,
        "content": {"price_usd": 3495},
        "revision_reason": "new evidence contradicts prior price",
        "old_confidence_ppm": 920_000,
        "new_confidence_ppm": 300_000,
        "contradicts_prior": True,
        "contradiction_reason": "new evidence contradicts prior price",
        "llm_inputs": [{
            "target_kref": b_root,
            "llm_delta_ppm": -500_000,
            "llm_rationale": "fixed conformance input",
        }],
        "max_depth": 10,
        "max_nodes": 5000,
        "created_at": vector["clock"],
    }))
    return vector, data


def test_cascade_ab_and_restart_persistence(service: Service) -> None:
    vector, result = _build_cascade(service)
    expected = vector["expected"]["proposals"][0]
    proposal = result["cascade"]["proposals"][0]
    for field in (
        "old_confidence_ppm",
        "new_confidence_ppm",
        "depth",
        "status",
        "components_ppm",
    ):
        assert proposal[field] == expected[field]
    assert proposal["target_kref"] == "kref://cascade/B"
    b_before = _ok(_get(service, "kref://cascade/B"))
    a_before = _ok(_get(service, "kref://cascade/A"))
    assert b_before["item"]["confidence_ppm"] == 880_000
    persisted_ids = {
        "a_revision": a_before["current_revision"]["revision_id"],
        "b_revision": b_before["current_revision"]["revision_id"],
        "proposal": b_before["proposals"][0]["proposal_id"],
    }
    service.restart()
    a_after = _ok(_get(service, "kref://cascade/A"))
    b_after = _ok(_get(service, "kref://cascade/B"))
    assert {
        "a_revision": a_after["current_revision"]["revision_id"],
        "b_revision": b_after["current_revision"]["revision_id"],
        "proposal": b_after["proposals"][0]["proposal_id"],
    } == persisted_ids
    assert a_after["current_revision"]["content"] == {"price_usd": 3495}
    assert a_after["item"]["confidence_ppm"] == 300_000


def test_scope_and_token_isolation(tmp_path: Path) -> None:
    first = Service(tmp_path / "a", scope="profile-a", token=TOKEN_A).start()
    second = Service(tmp_path / "b", scope="profile-b", token=TOKEN_B).start()
    try:
        root = "kref://vectors/scope-isolation.fact"
        _ok(first.request("POST", "/v1/items/create", _create_body("scope-a", root, {"owner": "A"})), 201)
        _ok(second.request("POST", "/v1/items/create", _create_body("scope-b", root, {"owner": "B"})), 201)
        assert _ok(_get(first, root))["current_revision"]["content"] == {"owner": "A"}
        assert _ok(_get(second, root))["current_revision"]["content"] == {"owner": "B"}
        status, payload = first.request("GET", "/v1/health", token=TOKEN_B)
        assert (status, payload["error"]["code"]) == (401, "unauthorized")
        status, payload = second.request("GET", "/v1/health", token=TOKEN_A)
        assert (status, payload["error"]["code"]) == (401, "unauthorized")
    finally:
        first.stop()
        second.stop()


def _node() -> str | None:
    for candidate in ("/opt/homebrew/opt/node@22/bin/node", shutil.which("node")):
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


@pytest.mark.parametrize("client", ["python", "node"])
def test_transport_only_clients_execute_public_http_plan(
    service: Service, tmp_path: Path, client: str
) -> None:
    root = f"kref://clients/{client}"
    plan = {
        "cases": [{
            "id": f"{client}-public-http",
            "steps": [
                {
                    "name": "health",
                    "request": {"method": "GET", "path": "/v1/health"},
                    "expect": {"status": 200, "json_subset": {"ok": True, "data": {"scope_id": service.scope}}},
                },
                {
                    "name": "create",
                    "request": {"method": "POST", "path": "/v1/items/create", "json": _create_body(f"client-{client}", root, {"transport": client})},
                    "expect": {"status": 201, "json_subset": {"ok": True}},
                    "capture": {"/data/revision/content_json": "canonical_content"},
                },
                {
                    "name": "read-server-output",
                    "request": {"method": "GET", "path": "/v1/items/get?" + urllib.parse.urlencode({"root_kref": root})},
                    "expect": {"status": 200, "equals_capture": {"/data/current_revision/content_json": "canonical_content"}},
                },
            ],
        }]
    }
    plan_path = tmp_path / f"{client}-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    if client == "python":
        command = [sys.executable, str(PYTHON_CLIENT)]
    else:
        node = _node()
        if node is None:
            pytest.skip("Node.js is not installed")
        command = [node, str(NODE_CLIENT)]
    result = subprocess.run(
        [*command, "--plan", str(plan_path), "--base-url", service.base_url],
        cwd=REPO,
        env={**os.environ, "ATLAS_COGNITIVE_TOKEN": service.token},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    reports = [json.loads(line) for line in result.stdout.splitlines()]
    assert reports == [{
        "id": f"{client}-public-http",
        "passed": True,
        "steps": [
            {"name": "health", "passed": True, "status": 200},
            {"name": "create", "passed": True, "status": 201},
            {"name": "read-server-output", "passed": True, "status": 200},
        ],
    }]


AGM = json.loads((VECTORS / "agm-49.json").read_text())
SCENARIOS = AGM["scenarios"]


def _content(fixture: dict[str, Any], value: dict[str, Any]) -> Any:
    if "content_json" in value:
        return json.loads(value["content_json"])
    spec = fixture["content_fixtures"][value["content_json_ref"]]
    assert spec["kind"] == "json_string_field_repeat"
    return {spec["field"]: spec["character"] * spec["count"]}


def _apply_agm_fixture(service: Service, fixture_name: str) -> dict[str, Any]:
    fixture = AGM["fixtures"][fixture_name]
    roots: dict[str, str] = {}
    created: set[str] = set()
    confidence: dict[str, int] = {}
    for index, operation in enumerate(fixture["ops"], start=1):
        item = operation["item"]
        root = roots.setdefault(item, f"kref://agm/{fixture_name}/{item}")
        if operation["op"] == "revise":
            content = _content(fixture, operation)
            evidence = json.loads(operation["evidence_json"])
            if item not in created:
                _ok(service.request("POST", "/v1/items/create", _create_body(
                    f"agm-{fixture_name}-{index}", root, content,
                    created_at=operation["at"], evidence=evidence,
                    actor=operation["actor"], tag=operation["tag"],
                )), 201)
                created.add(item)
                confidence[item] = 800_000
            else:
                response = service.request("POST", "/v1/items/revise", {
                    "idempotency_key": f"agm-{fixture_name}-{index}",
                    "root_kref": root,
                    "content": content,
                    "revision_reason": operation["reason"],
                    "old_confidence_ppm": confidence[item],
                    "new_confidence_ppm": confidence[item],
                    "evidence": evidence,
                    "actor": operation["actor"],
                    "tag": operation["tag"],
                    "run_cascade": False,
                    "created_at": operation["at"],
                })
                if "expect_error" in operation:
                    status, payload = response
                    assert (status, payload["error"]["code"]) == (
                        404,
                        operation["expect_error"],
                    )
                else:
                    _ok(response)
        elif operation["op"] == "contract":
            _ok(service.request("POST", "/v1/items/forget", {
                "root_kref": root,
                "proposition": operation["proposition"],
                "reason": operation["reason"],
                "actor": operation["actor"],
                "created_at": operation["at"],
            }))
        else:
            raise AssertionError(f"unsupported AGM vector operation: {operation['op']}")
    return roots


def _assert_agm_state(service: Service, fixture_name: str, roots: dict[str, str]) -> None:
    fixture = AGM["fixtures"][fixture_name]
    expected = fixture["state"]
    expected_tags: dict[str, list[dict[str, Any]]] = {}
    expected_revisions: dict[str, list[dict[str, Any]]] = {}
    expected_supersedes: dict[str, list[dict[str, Any]]] = {}
    for row in expected["tags"]:
        expected_tags.setdefault(row["item"], []).append(row)
    for row in expected["revisions"]:
        expected_revisions.setdefault(row["item"], []).append(row)
    for row in expected["supersedes"]:
        expected_supersedes.setdefault(row["item"], []).append(row)

    for item in expected["items"]:
        root = roots[item["item"]]
        status, payload = _get(service, root, "audit")
        assert status == 200, (
            "AGM conformance requires the authenticated /v1/items/audit surface "
            "so tags and deprecated-item provenance are verified over HTTP; "
            f"service returned {status}: {payload}"
        )
        audit = payload["data"]
        assert audit["item"]["deprecated"] is item["deprecated"]
        lineage = audit["lineage"]
        wanted = expected_revisions.get(item["item"], [])
        assert len(lineage) == len(wanted)
        id_to_seq = {row["revision_id"]: row["revision_seq"] for row in lineage}
        for actual, vector in zip(lineage, wanted, strict=True):
            assert actual["revision_seq"] == vector["seq"]
            assert actual["content"] == _content(fixture, vector)
            assert actual["content_hash"] == vector["content_sha256"]
            assert actual["evidence"] == json.loads(vector["evidence_json"])
            assert actual["created_at"] == vector["created_at"]
        tags = sorted(
            [
                {
                    "item": item["item"],
                    "tag": row["name"],
                    "revision_seq": id_to_seq[row["revision_id"]],
                }
                for row in audit["tags"]
            ],
            key=lambda row: row["tag"],
        )
        assert tags == sorted(expected_tags.get(item["item"], []), key=lambda row: row["tag"])
        supersedes = [
            {
                "item": item["item"],
                "new_seq": row["revision_seq"],
                "old_seq": id_to_seq[row["supersedes_revision_id"]],
                "created_at": row["created_at"],
            }
            for row in lineage
            if row["supersedes_revision_id"] is not None
        ]
        assert supersedes == expected_supersedes.get(item["item"], [])
        public_status, public_payload = _get(service, root)
        if item["deprecated"]:
            assert (public_status, public_payload["error"]["code"]) == (404, "not_found")
        else:
            assert public_status == 200


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[row["id"] for row in SCENARIOS])
def test_agm_49_over_public_service(service: Service, scenario: dict[str, Any]) -> None:
    assert len(SCENARIOS) == 49
    roots = _apply_agm_fixture(service, scenario["fixture"])
    _assert_agm_state(service, scenario["fixture"], roots)
