"""Contract tests for the native Atlas plugin against pinned Hermes Agent."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ATLAS_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ATLAS_ROOT / "integrations" / "hermes-atlas"
PINNED_HERMES_COMMIT = "b5bd0ef38b538627a0e5d2cbe5d3eef2c38ec792"


def _hermes_root() -> Path:
    configured = os.environ.get("HERMES_UPSTREAM")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path("/tmp/atlas-hermes-upstream.FBOBi8"))
    for candidate in candidates:
        if (candidate / "agent" / "memory_provider.py").exists():
            return candidate.resolve()
    pytest.skip("pinned Hermes fixture unavailable; set HERMES_UPSTREAM")


@pytest.fixture(scope="session")
def hermes_root() -> Path:
    root = _hermes_root()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert commit == PINNED_HERMES_COMMIT
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _install_fixture(home: Path) -> Path:
    destination = home / "plugins" / "atlas"
    destination.mkdir(parents=True)
    shutil.copy2(PACKAGE_ROOT / "atlas" / "__init__.py", destination / "__init__.py")
    shutil.copy2(PACKAGE_ROOT / "atlas" / "store.py", destination / "store.py")
    shutil.copy2(
        PACKAGE_ROOT / "atlas" / "cognitive_client.py",
        destination / "cognitive_client.py",
    )
    shutil.copy2(PACKAGE_ROOT / "plugin.yaml", destination / "plugin.yaml")
    shutil.copytree(
        ATLAS_ROOT / "integrations" / "cognitive-service",
        destination / "cognitive-service",
    )
    return destination


def _load_real_hermes_provider(monkeypatch: pytest.MonkeyPatch, hermes_root: Path, home: Path):
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_constants

    importlib.reload(hermes_constants)
    memory_plugins = importlib.import_module("plugins.memory")
    provider = memory_plugins.load_memory_provider("atlas")
    assert provider is not None
    return provider


def _tool(provider, name: str, args: dict) -> dict:
    return json.loads(provider.handle_tool_call(name, args))


def test_real_loader_subclasses_pinned_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    from agent.memory_provider import MemoryProvider

    assert isinstance(provider, MemoryProvider)
    assert provider.name == "atlas"
    assert provider.is_available() is True
    memory_plugins = importlib.import_module("plugins.memory")
    assert "atlas" in memory_plugins.list_memory_provider_names()
    schemas = provider.get_tool_schemas()
    assert [schema["name"] for schema in schemas] == [
        "atlas_memory_search",
        "atlas_memory_get",
        "atlas_memory_list",
        "atlas_memory_forget",
        "atlas_memory_store",
        "atlas_memory_depend",
    ]
    assert all(
        "profile_id" not in schema["parameters"]["properties"]
        for schema in schemas
    )
    by_name = {schema["name"]: schema for schema in schemas}
    assert set(by_name["atlas_memory_get"]["parameters"]["properties"]) == {"memory_id"}
    assert set(by_name["atlas_memory_forget"]["parameters"]["properties"]) == {
        "memory_id",
        "proposition",
        "reason",
    }
    assert by_name["atlas_memory_store"]["parameters"]["required"] == [
        "kind",
        "content",
        "confidence_ppm",
    ]


def test_real_host_cognitive_revision_persists_exact_reassessment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize(
        "cognitive-one",
        hermes_home=str(home),
        agent_identity="coder",
        platform="cli",
        user_id="rich",
    )

    from agent.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.add_provider(provider)

    fact = _tool(
        manager,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"price_usd": 2995},
            "confidence_ppm": 920000,
            "last_evidence_days": 0,
        },
    )
    belief = _tool(
        manager,
        "atlas_memory_store",
        {
            "kind": "belief",
            "content": {"claim": "belief B depends on fact A"},
            "confidence_ppm": 880000,
            "last_evidence_days": 0,
        },
    )
    fact_id = fact["memory_id"]
    belief_id = belief["memory_id"]
    linked = _tool(
        manager,
        "atlas_memory_depend",
        {
            "dependent_memory_id": belief_id,
            "support_memory_id": fact_id,
            "strength_ppm": 950000,
        },
    )
    assert linked["dependency"] == {
        "dependent_kref": belief_id,
        "support_kref": fact_id,
        "strength_ppm": 950000,
    }
    assert linked["cognitive"]["dependencies"] == [
        {"root_kref": fact_id, "strength_ppm": 950000}
    ]

    revised_args = {
        "memory_id": fact_id,
        "kind": "fact",
        "content": {"price_usd": 997},
        "confidence_ppm": 300000,
        "last_evidence_days": 7,
        "revision_reason": "contradicting verified price",
        "contradicts_prior": True,
        "contradiction_reason": "2995 replaced by 997",
    }
    revised = _tool(manager, "atlas_memory_store", revised_args)
    assert revised["operation"] == "revised"
    assert len(revised["proposals"]) == 1
    proposal = revised["proposals"][0]
    assert proposal["target_kref"] == belief_id
    assert proposal["upstream_kref"] == fact_id
    assert proposal["old_confidence_ppm"] == 880000
    assert proposal["new_confidence_ppm"] == 766650
    assert proposal["components_ppm"] == {
        "beta": -176700,
        "gamma": -75000,
        "delta": 25000,
        "perturbation": -226700,
        "damped": -113350,
    }
    assert proposal["status"] == "pending"
    proposal_id = proposal["proposal_id"]

    provider.shutdown()

    restarted = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    restarted.initialize(
        "cognitive-two",
        hermes_home=str(home),
        agent_identity="coder",
        platform="cli",
        user_id="rich",
    )
    persisted = _tool(restarted, "atlas_memory_get", {"memory_id": belief_id})
    assert persisted["memory"] is None
    assert persisted["cognitive"]["proposals"][0]["proposal_id"] == proposal_id
    assert (
        json.loads(persisted["cognitive"]["proposals"][0]["canonical_output"])[
            "new_confidence_ppm"
        ]
        == 766650
    )
    fact_state = _tool(restarted, "atlas_memory_get", {"memory_id": fact_id})["cognitive"]
    assert len(fact_state["lineage"]) == 2
    assert fact_state["item"]["kind"] == "fact"
    assert fact_state["item"]["last_evidence_days"] == 7
    assert fact_state["lineage"][1]["kind"] == "fact"
    assert fact_state["lineage"][1]["last_evidence_days"] == 7
    assert fact_state["lineage"][1]["contradicts_prior"] is True
    assert fact_state["lineage"][1]["contradiction_reason"] == "2995 replaced by 997"

    search = _tool(restarted, "atlas_memory_search", {"query": "price_usd", "limit": 5})
    assert [row["root_kref"] for row in search["cognitive"]] == [fact_id]
    assert search["cognitive"][0]["content"] == {"price_usd": 997}
    listed = _tool(restarted, "atlas_memory_list", {"limit": 5})
    assert {row["root_kref"] for row in listed["cognitive"]} == {fact_id, belief_id}
    assert "997" in restarted.prefetch("price_usd", session_id="cognitive-two")

    forgotten = _tool(
        restarted,
        "atlas_memory_forget",
        {
            "memory_id": belief_id,
            "proposition": "belief B",
            "reason": "contract test",
        },
    )
    assert forgotten["cognitive"]["deprecated"] is True
    after_forget = _tool(restarted, "atlas_memory_get", {"memory_id": belief_id})
    assert after_forget["cognitive"] is None
    assert after_forget["cognitive_audit"]["item"]["deprecated"] is True
    assert after_forget["cognitive_audit"]["audit_events"][-1]["event_type"] == "item_forgotten"
    restarted.shutdown()


def test_memory_manager_revision_retries_are_semantically_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize(
        "idempotent-revisions",
        hermes_home=str(home),
        agent_identity="coder",
        platform="cli",
        user_id="rich",
    )

    from agent.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.add_provider(provider)
    invalid_create = _tool(
        manager,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"must_not_exist": True},
            "confidence_ppm": 900000,
            "revision_reason": "silently discarded input",
        },
    )
    assert invalid_create == {
        "error": "revision_reason is only valid when memory_id revises an item"
    }
    assert provider._cognitive._process is None
    created = _tool(
        manager,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"price_usd": 2995},
            "confidence_ppm": 900000,
            "last_evidence_days": 0,
        },
    )
    memory_id = created["memory_id"]

    missing_reason = _tool(
        manager,
        "atlas_memory_store",
        {
            "memory_id": memory_id,
            "kind": "fact",
            "content": {"price_usd": 997},
            "confidence_ppm": 500000,
        },
    )
    assert missing_reason == {
        "error": "revision_reason is required when revising a memory"
    }

    auto_args = {
        "memory_id": memory_id,
        "kind": "fact",
        "content": {"price_usd": 997},
        "confidence_ppm": 500000,
        "last_evidence_days": 1,
        "revision_reason": "verified correction",
        "contradicts_prior": True,
        "contradiction_reason": "new source",
    }
    auto_first = _tool(manager, "atlas_memory_store", auto_args)
    auto_retry = _tool(manager, "atlas_memory_store", auto_args)
    assert auto_retry["cognitive"]["revision"]["revision_id"] == (
        auto_first["cognitive"]["revision"]["revision_id"]
    )
    assert auto_retry["cognitive"]["cascade"]["cascade_id"] == (
        auto_first["cognitive"]["cascade"]["cascade_id"]
    )

    explicit_args = {
        **auto_args,
        "content": {"price_usd": 799},
        "confidence_ppm": 400000,
        "revision_reason": "second verified correction",
        "idempotency_key": "hermes-explicit-revision-retry",
    }
    explicit_first = _tool(manager, "atlas_memory_store", explicit_args)
    explicit_retry = _tool(manager, "atlas_memory_store", explicit_args)
    assert explicit_retry["cognitive"]["revision"]["revision_id"] == (
        explicit_first["cognitive"]["revision"]["revision_id"]
    )
    assert explicit_retry["cognitive"]["cascade"]["cascade_id"] == (
        explicit_first["cognitive"]["cascade"]["cascade_id"]
    )

    audit = provider._cognitive.audit(memory_id)
    assert len(audit["lineage"]) == 3
    assert sum(
        event["event_type"] == "cascade_created"
        for event in audit["audit_events"]
    ) == 2
    provider.shutdown()


def test_cognitive_ids_cannot_cross_profile_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    shared = tmp_path / "shared"
    monkeypatch.setenv("ATLAS_HERMES_DATA_DIR", str(shared))
    first_home = tmp_path / "profiles" / "first"
    second_home = tmp_path / "profiles" / "second"
    _install_fixture(first_home)
    _install_fixture(second_home)

    first = _load_real_hermes_provider(monkeypatch, hermes_root, first_home)
    first.initialize(
        "one", hermes_home=str(first_home), agent_identity="team/a", user_id="rich"
    )
    created = _tool(
        first,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"secret": "indigo"},
            "confidence_ppm": 900000,
        },
    )
    first.shutdown()

    second = _load_real_hermes_provider(monkeypatch, hermes_root, second_home)
    second.initialize(
        "two", hermes_home=str(second_home), agent_identity="team a", user_id="rich"
    )
    assert _tool(second, "atlas_memory_get", {"memory_id": created["memory_id"]}) == {
        "memory": None,
        "cognitive": None,
        "cognitive_audit": None,
        "degraded": False,
        "cognitive_error": None,
    }
    denied = _tool(
        second,
        "atlas_memory_depend",
        {
            "dependent_memory_id": created["memory_id"],
            "support_memory_id": created["memory_id"],
        },
    )
    assert "error" in denied
    second.shutdown()


def test_revision_operation_linkage_handles_create_match_explicit_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize("linked-retry", hermes_home=str(home), agent_identity="coder")
    from agent.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.add_provider(provider)
    created = _tool(
        manager,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"state": "same-as-create"},
            "confidence_ppm": 900000,
            "last_evidence_days": 0,
        },
    )
    memory_id = created["memory_id"]
    same_as_create = {
        "memory_id": memory_id,
        "kind": "fact",
        "content": {"state": "same-as-create"},
        "confidence_ppm": 900000,
        "last_evidence_days": 0,
        "revision_reason": "initial",
    }
    first_revision = _tool(manager, "atlas_memory_store", same_as_create)
    first_revision_id = first_revision["cognitive"]["revision"]["revision_id"]
    for _ in range(3):
        replay = _tool(manager, "atlas_memory_store", same_as_create)
        assert replay["cognitive"]["revision"]["revision_id"] == first_revision_id
    assert len(
        _tool(manager, "atlas_memory_get", {"memory_id": memory_id})["cognitive"][
            "lineage"
        ]
    ) == 2

    explicit = {
        **same_as_create,
        "content": {"state": "explicit"},
        "confidence_ppm": 800000,
        "revision_reason": "explicit state",
        "idempotency_key": "explicit-linkage-key",
    }
    explicit_result = _tool(manager, "atlas_memory_store", explicit)
    explicit_revision_id = explicit_result["cognitive"]["revision"]["revision_id"]
    automatic_same = {key: value for key, value in explicit.items() if key != "idempotency_key"}
    automatic_replay = _tool(manager, "atlas_memory_store", automatic_same)
    assert automatic_replay["cognitive"]["revision"]["revision_id"] == explicit_revision_id

    attached = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    attached.initialize("linked-retry", hermes_home=str(home), agent_identity="coder")
    attached_manager = MemoryManager()
    attached_manager.add_provider(attached)
    attached_replay = _tool(attached_manager, "atlas_memory_store", automatic_same)
    assert attached_replay["cognitive"]["revision"]["revision_id"] == explicit_revision_id
    attached.shutdown()
    provider.shutdown()

    restarted = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    restarted.initialize("linked-retry", hermes_home=str(home), agent_identity="coder")
    restarted_manager = MemoryManager()
    restarted_manager.add_provider(restarted)
    restart_replay = _tool(restarted_manager, "atlas_memory_store", automatic_same)
    assert restart_replay["cognitive"]["revision"]["revision_id"] == explicit_revision_id
    assert len(
        _tool(restarted_manager, "atlas_memory_get", {"memory_id": memory_id})[
            "cognitive"
        ]["lineage"]
    ) == 3
    restarted.shutdown()


def test_auto_revision_key_distinguishes_retry_from_later_same_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize("revision-cycle", hermes_home=str(home), agent_identity="coder")
    from agent.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.add_provider(provider)
    created = _tool(
        manager,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"state": "v0"},
            "confidence_ppm": 900000,
        },
    )
    memory_id = created["memory_id"]
    x_args = {
        "memory_id": memory_id,
        "kind": "fact",
        "content": {"state": "X"},
        "confidence_ppm": 700000,
        "last_evidence_days": 2,
        "revision_reason": "set X",
    }
    first_x = _tool(manager, "atlas_memory_store", x_args)
    retry_x = _tool(manager, "atlas_memory_store", x_args)
    assert retry_x["cognitive"]["revision"]["revision_id"] == (
        first_x["cognitive"]["revision"]["revision_id"]
    )

    y_args = {
        **x_args,
        "content": {"state": "Y"},
        "confidence_ppm": 600000,
        "revision_reason": "set Y",
    }
    y_result = _tool(manager, "atlas_memory_store", y_args)
    later_x = _tool(manager, "atlas_memory_store", x_args)
    assert later_x["cognitive"]["revision"]["revision_id"] not in {
        first_x["cognitive"]["revision"]["revision_id"],
        y_result["cognitive"]["revision"]["revision_id"],
    }
    assert later_x["cognitive"]["revision"]["content"] == {"state": "X"}
    later_x_revision = later_x["cognitive"]["revision"]["revision_id"]
    assert len(
        _tool(manager, "atlas_memory_get", {"memory_id": memory_id})["cognitive"][
            "lineage"
        ]
    ) == 4
    provider.shutdown()

    restarted = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    restarted.initialize(
        "revision-cycle", hermes_home=str(home), agent_identity="coder"
    )
    restarted_manager = MemoryManager()
    restarted_manager.add_provider(restarted)
    restart_retry = _tool(restarted_manager, "atlas_memory_store", x_args)
    assert restart_retry["cognitive"]["revision"]["revision_id"] == later_x_revision
    assert len(
        _tool(restarted_manager, "atlas_memory_get", {"memory_id": memory_id})[
            "cognitive"
        ]["lineage"]
    ) == 4
    restarted.shutdown()


def test_failed_service_cascade_rolls_back_revision_and_confidence_over_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize("rollback", hermes_home=str(home), agent_identity="coder")
    create_args = {
        "kind": "fact",
        "content": {"price_usd": 2995},
        "confidence_ppm": 920000,
    }
    created = _tool(
        provider,
        "atlas_memory_store",
        create_args,
    )
    memory_id = created["memory_id"]
    retried_create = _tool(provider, "atlas_memory_store", create_args)
    assert retried_create["memory_id"] == memory_id
    assert len(retried_create["cognitive"]["item"]) > 0
    assert len(_tool(provider, "atlas_memory_get", {"memory_id": memory_id})["cognitive"]["lineage"]) == 1
    dependent = _tool(
        provider,
        "atlas_memory_store",
        {
            "kind": "belief",
            "content": {"claim": "dependent"},
            "confidence_ppm": 880000,
        },
    )
    _tool(
        provider,
        "atlas_memory_depend",
        {
            "dependent_memory_id": dependent["memory_id"],
            "support_memory_id": memory_id,
        },
    )
    database = provider._cognitive._database
    assert database is not None
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER inject_proposal_failure
            BEFORE INSERT ON proposals
            BEGIN
              SELECT RAISE(ABORT, 'injected cascade failure');
            END
            """
        )
    failed = _tool(
        provider,
        "atlas_memory_store",
        {
            "memory_id": memory_id,
            "kind": "fact",
            "content": {"price_usd": 997},
            "confidence_ppm": 300000,
            "revision_reason": "must roll back",
            "contradicts_prior": True,
        },
    )
    assert failed == {"error": "internal service error"}
    state = _tool(provider, "atlas_memory_get", {"memory_id": memory_id})["cognitive"]
    assert state["item"]["confidence_ppm"] == 920000
    assert len(state["lineage"]) == 1
    assert state["proposals"] == []
    provider.shutdown()


def test_two_live_clients_attach_without_thrash_then_fail_over_after_owner_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    first = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    first.initialize("first", hermes_home=str(home), agent_identity="coder")
    created = _tool(
        first,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"lifecycle": "owned"},
            "confidence_ppm": 900000,
        },
    )
    first_process = first._cognitive._process
    first_owner = first._cognitive._owner_instance
    assert first_process is not None and first_process.poll() is None
    first_pid = first_process.pid

    attached = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    attached.initialize("second", hermes_home=str(home), agent_identity="coder")
    state = _tool(attached, "atlas_memory_get", {"memory_id": created["memory_id"]})
    assert state["cognitive"]["item"]["root_kref"] == created["memory_id"]
    attached_health = attached._cognitive._health()
    assert attached_health["managed_owner"]["instance_id"] == first_owner
    assert attached_health["managed_owner"]["server_pid"] == first_pid
    assert attached._cognitive._owns_running_instance is False
    assert attached._cognitive._process is None

    # Alternating operations share one stable process without kill/relaunch thrash.
    for index in range(4):
        client = first if index % 2 == 0 else attached
        operation = _tool(
            client,
            "atlas_memory_search",
            {"query": "lifecycle", "limit": 5},
        )
        assert operation["degraded"] is False
        assert operation["cognitive"][0]["root_kref"] == created["memory_id"]
        assert client._cognitive._health()["managed_owner"]["server_pid"] == first_pid
        assert first_process.poll() is None

    # Non-owner shutdown is sidecar-inert.
    attached._cognitive.shutdown()
    assert first._cognitive._health()["managed_owner"]["server_pid"] == first_pid
    assert first_process.poll() is None

    # Owner shutdown stops the service. The attached client can then fail over.
    first._cognitive.shutdown()
    first_process.wait(timeout=5)
    assert first_process.poll() is not None
    recovered = _tool(attached, "atlas_memory_get", {"memory_id": created["memory_id"]})
    assert recovered["cognitive"]["item"]["root_kref"] == created["memory_id"]
    replacement = attached._cognitive._process
    replacement_health = attached._cognitive._health()
    assert replacement is not None and replacement.poll() is None
    assert attached._cognitive._owns_running_instance is True
    assert replacement_health["managed_owner"]["server_pid"] == replacement.pid
    assert replacement_health["managed_owner"]["instance_id"] == attached._cognitive._owner_instance

    attached.shutdown()
    replacement.wait(timeout=5)
    assert replacement.poll() is not None
    first.shutdown()


def test_parent_watchdog_exits_after_launcher_disappears(tmp_path: Path) -> None:
    service = ATLAS_ROOT / "integrations" / "cognitive-service" / "server.py"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    token = "parent-watch-token-0123456789abcdef"
    database = tmp_path / "watchdog.sqlite3"
    launcher = "\n".join(
        [
            "import os, subprocess, sys, time",
            "command = [sys.executable, sys.argv[1], '--db', sys.argv[2], '--scope', "
            "'watchdog-scope', '--port', sys.argv[3], '--owner-instance', "
            "'watchdog-owner', '--parent-pid', str(os.getpid())]",
            "child = subprocess.Popen(command, env=os.environ.copy())",
            "print(child.pid, flush=True)",
            "time.sleep(0.4)",
            "os._exit(0)",
        ]
    )
    environment = os.environ.copy()
    environment["ATLAS_COGNITIVE_TOKEN"] = token
    completed = subprocess.run(
        [sys.executable, "-c", launcher, str(service), str(database), str(port)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    )
    assert int(completed.stdout.strip()) > 0
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(request, timeout=0.5)


def test_concurrent_managed_launch_race_converges_on_one_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    providers = [
        _load_real_hermes_provider(monkeypatch, hermes_root, home),
        _load_real_hermes_provider(monkeypatch, hermes_root, home),
    ]
    for index, provider in enumerate(providers):
        provider.initialize(
            f"race-{index}", hermes_home=str(home), agent_identity="race"
        )
    barrier = threading.Barrier(3)
    results: list[dict] = []
    failures: list[Exception] = []

    def start(provider) -> None:
        barrier.wait()
        try:
            results.append(provider._cognitive.ensure_available())
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=start, args=(provider,)) for provider in providers]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=8)
        assert not thread.is_alive()

    assert failures == []
    assert len(results) == 2
    assert len({result["managed_owner"]["server_pid"] for result in results}) == 1
    owners = [provider for provider in providers if provider._cognitive._owns_running_instance]
    attached = [provider for provider in providers if not provider._cognitive._owns_running_instance]
    assert len(owners) == 1
    assert len(attached) == 1
    server_pid = owners[0]._cognitive._health()["managed_owner"]["server_pid"]
    attached[0]._cognitive.shutdown()
    assert owners[0]._cognitive._health()["managed_owner"]["server_pid"] == server_pid
    owner_process = owners[0]._cognitive._process
    owners[0]._cognitive.shutdown()
    assert owner_process is not None
    owner_process.wait(timeout=5)
    for provider in providers:
        provider.shutdown()


def test_simultaneous_processes_atomically_publish_one_managed_state(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".hermes"
    data_dir = home / "atlas" / "data"
    start_gate = tmp_path / "start"
    stop_gate = tmp_path / "stop"
    ready_gates = [tmp_path / f"ready-{index}" for index in range(2)]
    client_path = PACKAGE_ROOT / "atlas" / "cognitive_client.py"
    scope_id = "atomic-state-scope"
    script = "\n".join(
        [
            "import importlib.util, json, sys, time",
            "from pathlib import Path",
            "client_path, home, data, scope, start, ready, stop = sys.argv[1:]",
            "spec = importlib.util.spec_from_file_location('atomic_client', client_path)",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "while not Path(start).exists(): time.sleep(0.005)",
            "client = module.ManagedCognitiveClient(scope_id=scope, "
            "hermes_home=Path(home), data_dir=Path(data))",
            "health = client.ensure_available()",
            "print(json.dumps({'token': client.token, 'port': client.base_url, "
            "'owns': client._owns_running_instance, "
            "'server_pid': health['managed_owner']['server_pid']}), flush=True)",
            "Path(ready).touch()",
            "while not Path(stop).exists(): time.sleep(0.005)",
            "client.shutdown()",
        ]
    )
    commands = [
        [
            sys.executable,
            "-c",
            script,
            str(client_path),
            str(home),
            str(data_dir),
            scope_id,
            str(start_gate),
            str(ready_gate),
            str(stop_gate),
        ]
        for ready_gate in ready_gates
    ]
    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for command in commands
    ]
    assert not (home / "atlas" / "service" / f"{scope_id}.json").exists()
    start_gate.touch()
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline and not all(gate.exists() for gate in ready_gates):
        time.sleep(0.01)
    assert all(gate.exists() for gate in ready_gates), [
        process.poll() for process in processes
    ]
    stop_gate.touch()
    outputs = [process.communicate(timeout=10) for process in processes]
    assert [process.returncode for process in processes] == [0, 0], outputs
    states = [json.loads(stdout.strip()) for stdout, _ in outputs]
    assert len({state["token"] for state in states}) == 1
    assert len({state["port"] for state in states}) == 1
    assert len({state["server_pid"] for state in states}) == 1
    assert sorted(state["owns"] for state in states) == [False, True]

    state_dir = home / "atlas" / "service"
    state_path = state_dir / f"{scope_id}.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["token"] == states[0]["token"]
    assert persisted["scope_id"] == scope_id
    assert list(state_dir.glob("*.tmp")) == []
    assert list(state_dir.glob("*.lock")) == []
    if os.name != "nt":
        assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(state_path.stat().st_mode) == 0o600


@pytest.mark.parametrize("crash_point", ["before_link", "after_link"])
def test_state_publisher_crash_cannot_block_or_publish_partial_json(
    tmp_path: Path,
    crash_point: str,
) -> None:
    home = tmp_path / crash_point
    data_dir = home / "atlas" / "data"
    marker = tmp_path / f"{crash_point}.ready"
    client_path = PACKAGE_ROOT / "atlas" / "cognitive_client.py"
    scope_id = f"crash-safe-{crash_point}"
    crashing_script = "\n".join(
        [
            "import importlib.util, sys, time",
            "from pathlib import Path",
            "client_path, home, data, scope, marker, point = sys.argv[1:]",
            "spec = importlib.util.spec_from_file_location('crash_client', client_path)",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "real_link = module.os.link",
            "def crash_window(source, target):",
            "    if point == 'after_link': real_link(source, target)",
            "    Path(marker).write_text('temp-fsynced', encoding='utf-8')",
            "    time.sleep(30)",
            "    if point == 'before_link': real_link(source, target)",
            "module.os.link = crash_window",
            "module.ManagedCognitiveClient(scope_id=scope, hermes_home=Path(home), "
            "data_dir=Path(data))",
        ]
    )
    crashing = subprocess.Popen(
        [
            sys.executable,
            "-c",
            crashing_script,
            str(client_path),
            str(home),
            str(data_dir),
            scope_id,
            str(marker),
            crash_point,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 8
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), crashing.communicate(timeout=1)
    state_dir = home / "atlas" / "service"
    temporary_files = list(state_dir.glob("*.tmp"))
    assert len(temporary_files) == 1
    assert json.loads(temporary_files[0].read_text(encoding="utf-8"))["scope_id"] == scope_id
    if crash_point == "after_link":
        live_reader = "\n".join(
            [
                "import importlib.util, sys",
                "from pathlib import Path",
                "client_path, home, data, scope = sys.argv[1:]",
                "spec = importlib.util.spec_from_file_location('live_reader', client_path)",
                "module = importlib.util.module_from_spec(spec)",
                "spec.loader.exec_module(module)",
                "module.ManagedCognitiveClient(scope_id=scope, "
                "hermes_home=Path(home), data_dir=Path(data))",
            ]
        )
        subprocess.run(
            [
                sys.executable,
                "-c",
                live_reader,
                str(client_path),
                str(home),
                str(data_dir),
                scope_id,
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        assert crashing.poll() is None
        assert temporary_files[0].exists(), "fresh live contender temp was removed"
    crashing.kill()
    crashing.communicate(timeout=5)

    clean_script = "\n".join(
        [
            "import importlib.util, json, sys",
            "from pathlib import Path",
            "client_path, home, data, scope = sys.argv[1:]",
            "spec = importlib.util.spec_from_file_location('clean_client', client_path)",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "client = module.ManagedCognitiveClient(scope_id=scope, "
            "hermes_home=Path(home), data_dir=Path(data))",
            "print(json.dumps({'token': client.token, 'port': client.base_url}))",
        ]
    )
    recovered = subprocess.run(
        [
            sys.executable,
            "-c",
            clean_script,
            str(client_path),
            str(home),
            str(data_dir),
            scope_id,
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    recovered_state = json.loads(recovered.stdout)
    state_path = state_dir / f"{scope_id}.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert recovered_state["token"] == persisted["token"]
    assert persisted["scope_id"] == scope_id
    assert list(state_dir.glob("*.lock")) == []

    # Crash temps are correctness-irrelevant and fresh contender temps are not
    # touched. Once conservatively stale, the next constructor removes all of
    # this scope's stale files, bounding retained stale files and bytes at zero.
    remaining = list(state_dir.glob("*.tmp"))
    assert len(remaining) == 1
    stale_time = time.time() - 7200
    os.utime(remaining[0], (stale_time, stale_time))
    subprocess.run(
        [
            sys.executable,
            "-c",
            clean_script,
            str(client_path),
            str(home),
            str(data_dir),
            scope_id,
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert list(state_dir.glob("*.tmp")) == []


def test_attached_client_recovers_if_owner_exits_between_health_and_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    owner = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    owner.initialize("owner", hermes_home=str(home), agent_identity="race-window")
    _tool(
        owner,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"seed": True},
            "confidence_ppm": 900000,
        },
    )
    owner_pid = owner._cognitive._health()["managed_owner"]["server_pid"]

    attached = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    attached.initialize(
        "attached", hermes_home=str(home), agent_identity="race-window"
    )
    assert attached._cognitive.ensure_available()["managed_owner"]["server_pid"] == owner_pid
    assert attached._cognitive._owns_running_instance is False
    original_ensure = attached._cognitive.ensure_available
    armed = True

    def ensure_then_owner_exits():
        nonlocal armed
        health = original_ensure()
        if armed:
            armed = False
            owner._cognitive.shutdown()
        return health

    monkeypatch.setattr(attached._cognitive, "ensure_available", ensure_then_owner_exits)
    from agent.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.add_provider(attached)
    created = _tool(
        manager,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"race_window": "survived"},
            "confidence_ppm": 880000,
        },
    )
    assert "error" not in created
    replacement_health = attached._cognitive._health()
    assert attached._cognitive._owns_running_instance is True
    assert replacement_health["managed_owner"]["server_pid"] != owner_pid
    replacement_pid = replacement_health["managed_owner"]["server_pid"]
    audit = attached._cognitive.audit(created["memory_id"])
    assert audit is not None
    assert [event["event_type"] for event in audit["audit_events"]].count(
        "item_created"
    ) == 1
    searched = _tool(manager, "atlas_memory_search", {"query": "race_window"})
    assert searched["cognitive"][0]["root_kref"] == created["memory_id"]
    assert attached._cognitive._health()["managed_owner"]["server_pid"] == replacement_pid
    attached.shutdown()
    owner.shutdown()


def test_cognitive_outage_preserves_legacy_retrieval_and_reports_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize("degraded", hermes_home=str(home), agent_identity="coder")
    memory_id = provider._store.add(
        profile_id=provider._profile_id,
        session_id="degraded",
        kind="turn",
        content="Legacy SQLite remembers the amber launch protocol.",
    )
    error_type = provider.handle_tool_call.__globals__["CognitiveServiceError"]

    def unavailable(*args, **kwargs):
        raise error_type("cognitive sidecar offline")

    for method in ("search", "get", "audit", "list", "forget"):
        monkeypatch.setattr(provider._cognitive, method, unavailable)

    searched = _tool(provider, "atlas_memory_search", {"query": "amber launch"})
    assert [row["memory_id"] for row in searched["memories"]] == [memory_id]
    assert searched["cognitive"] == []
    assert searched["degraded"] is True
    assert searched["cognitive_error"] == "cognitive sidecar offline"

    fetched = _tool(provider, "atlas_memory_get", {"memory_id": memory_id})
    assert fetched["memory"]["memory_id"] == memory_id
    assert fetched["degraded"] is True
    listed = _tool(provider, "atlas_memory_list", {})
    assert [row["memory_id"] for row in listed["memories"]] == [memory_id]
    assert listed["degraded"] is True
    recalled = provider.prefetch("amber launch")
    assert "amber launch protocol" in recalled
    assert "cognitive recall degraded" in recalled

    forgotten = _tool(provider, "atlas_memory_forget", {"memory_id": memory_id})
    assert forgotten["local_forgotten"] is True
    assert forgotten["forgotten"] is True
    assert forgotten["degraded"] is True
    provider.shutdown()


def test_memory_manager_forget_retry_replays_exact_response_and_single_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize("forget-retry", hermes_home=str(home), agent_identity="coder")
    from agent.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.add_provider(provider)
    created = _tool(
        manager,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"forgettable": "exactly once"},
            "confidence_ppm": 850000,
        },
    )
    forget_args = {
        "memory_id": created["memory_id"],
        "proposition": "forgettable",
        "reason": "explicit retry contract",
    }
    first = manager.handle_tool_call("atlas_memory_forget", forget_args)
    second = manager.handle_tool_call("atlas_memory_forget", forget_args)
    assert second == first
    decoded = json.loads(first)
    assert decoded["forgotten"] is True
    assert decoded["cognitive"] == {
        "root_kref": created["memory_id"],
        "deprecated": True,
        "tags_removed": ["current"],
    }
    audit = provider._cognitive.audit(created["memory_id"])
    assert audit is not None
    assert [
        event["event_type"] for event in audit["audit_events"]
    ].count("item_forgotten") == 1

    unknown_args = {
        "memory_id": "unknown-cognitive-id",
        "proposition": "missing",
        "reason": "unknown contract",
    }
    unknown_first = manager.handle_tool_call("atlas_memory_forget", unknown_args)
    unknown_second = manager.handle_tool_call("atlas_memory_forget", unknown_args)
    assert unknown_second == unknown_first
    assert json.loads(unknown_first) == {
        "forgotten": False,
        "local_forgotten": False,
        "cognitive": None,
        "memory_id": "unknown-cognitive-id",
        "degraded": False,
        "cognitive_error": None,
    }
    provider.shutdown()


def test_nonblocking_sync_tools_restart_and_forget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize(
        "session-one",
        hermes_home=str(home),
        agent_identity="coder",
        user_id="rich",
        agent_context="primary",
    )

    gate = threading.Event()
    original_add = provider._store.add

    def delayed_add(**kwargs):
        gate.wait(timeout=2)
        return original_add(**kwargs)

    provider._store.add = delayed_add
    provider.sync_turn(
        "My launch color is ultraviolet marmalade.",
        "I will remember that launch color.",
        session_id="session-one",
    )
    assert provider._write_queue.qsize() <= 1
    gate.set()
    provider.shutdown()

    restarted = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    restarted.initialize(
        "session-two",
        hermes_home=str(home),
        agent_identity="coder",
        user_id="rich",
    )
    from agent.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.add_provider(restarted)
    assert manager.has_tool("atlas_memory_search")
    recalled = restarted.prefetch("What was the ultraviolet launch color?", session_id="session-two")
    assert "ultraviolet marmalade" in recalled

    search = json.loads(manager.handle_tool_call("atlas_memory_search", {"query": "ultraviolet", "limit": 3}))
    assert search["backend"] == "sqlite+atlas-cognitive-service"
    assert search["count"] == 1
    memory_id = search["memories"][0]["memory_id"]
    assert _tool(restarted, "atlas_memory_get", {"memory_id": memory_id})["memory"]["session_id"] == "session-one"
    assert _tool(restarted, "atlas_memory_list", {})["count"] == 1
    assert _tool(restarted, "atlas_memory_forget", {"memory_id": memory_id})["forgotten"] is True
    assert _tool(restarted, "atlas_memory_get", {"memory_id": memory_id})["memory"] is None
    assert _tool(restarted, "atlas_memory_search", {"query": "ultraviolet"})["count"] == 0
    restarted.shutdown()


def test_profile_user_and_session_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    shared_data = tmp_path / "shared-atlas"
    monkeypatch.setenv("ATLAS_HERMES_DATA_DIR", str(shared_data))

    coder_home = tmp_path / "profiles" / "coder"
    writer_home = tmp_path / "profiles" / "writer"
    _install_fixture(coder_home)
    _install_fixture(writer_home)

    coder = _load_real_hermes_provider(monkeypatch, hermes_root, coder_home)
    coder.initialize("coder-a", hermes_home=str(coder_home), agent_identity="coder", user_id="rich")
    coder.sync_turn("Coder-only tungsten memory", "Stored", session_id="coder-a")
    coder.on_session_switch("coder-b", parent_session_id="coder-a")
    coder.sync_turn("Second-session cobalt memory", "Stored", session_id="coder-b")
    coder.shutdown()

    writer = _load_real_hermes_provider(monkeypatch, hermes_root, writer_home)
    writer.initialize("writer-a", hermes_home=str(writer_home), agent_identity="writer", user_id="rich")
    writer.sync_turn("Writer-only vermilion memory", "Stored", session_id="writer-a")
    writer.shutdown()

    coder_restart = _load_real_hermes_provider(monkeypatch, hermes_root, coder_home)
    coder_restart.initialize("coder-c", hermes_home=str(coder_home), agent_identity="coder", user_id="rich")
    assert _tool(coder_restart, "atlas_memory_search", {"query": "tungsten"})["count"] == 1
    assert _tool(coder_restart, "atlas_memory_search", {"query": "vermilion"})["count"] == 0
    assert _tool(coder_restart, "atlas_memory_list", {"session_id": "coder-a"})["count"] == 1
    assert _tool(coder_restart, "atlas_memory_list", {"session_id": "coder-b"})["count"] == 1

    other_user = _load_real_hermes_provider(monkeypatch, hermes_root, coder_home)
    other_user.initialize("coder-d", hermes_home=str(coder_home), agent_identity="coder", user_id="someone-else")
    assert _tool(other_user, "atlas_memory_search", {"query": "tungsten"})["count"] == 0
    coder_restart.shutdown()
    other_user.shutdown()


def test_pinned_hermes_backup_safely_snapshots_and_restores_live_atlas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / "source-home"
    _install_fixture(home)
    (home / "config.yaml").write_text("memory:\n  provider: atlas\n", encoding="utf-8")
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize(
        "backup-session",
        hermes_home=str(home),
        agent_identity="backup",
        platform="cli",
        user_id="rich",
    )
    legacy_id = provider._store.add(
        profile_id=provider._profile_id,
        session_id="backup-session",
        kind="turn",
        content="Legacy backup remembers the copper protocol.",
    )
    cognitive = _tool(
        provider,
        "atlas_memory_store",
        {
            "kind": "fact",
            "content": {"backup_fact": "cognitive copper"},
            "confidence_ppm": 910000,
        },
    )
    cognitive_id = cognitive["memory_id"]
    legacy_db = provider._store.db_path
    cognitive_db = provider._cognitive._database
    assert legacy_db.suffix == ".db"
    assert cognitive_db is not None and cognitive_db.suffix == ".db"

    # Keep a live WAL connection for the legacy store while the cognitive
    # service keeps its own WAL connection active throughout pinned backup.
    legacy_hold = sqlite3.connect(legacy_db)
    legacy_hold.execute("PRAGMA journal_mode=WAL")
    legacy_hold.execute("CREATE TABLE IF NOT EXISTS backup_wal_probe(value TEXT)")
    legacy_hold.execute("INSERT INTO backup_wal_probe(value) VALUES('active')")
    legacy_hold.commit()
    for database in (legacy_db, cognitive_db):
        assert Path(str(database) + "-wal").exists()
        assert Path(str(database) + "-shm").exists()

    import hermes_cli.backup as pinned_backup

    safe_copy_calls: list[Path] = []
    real_safe_copy = pinned_backup._safe_copy_db

    def record_safe_copy(source: Path, destination: Path) -> bool:
        safe_copy_calls.append(source.resolve())
        return real_safe_copy(source, destination)

    monkeypatch.setattr(pinned_backup, "_safe_copy_db", record_safe_copy)
    monkeypatch.setenv("HERMES_HOME", str(home))
    archive = tmp_path / "atlas-backup.zip"
    pinned_backup.run_backup(SimpleNamespace(output=str(archive)))
    legacy_hold.close()
    assert {legacy_db.resolve(), cognitive_db.resolve()} <= set(safe_copy_calls)

    legacy_arc = legacy_db.relative_to(home).as_posix()
    cognitive_arc = cognitive_db.relative_to(home).as_posix()
    with zipfile.ZipFile(archive, "r") as backup_zip:
        names = set(backup_zip.namelist())
    assert legacy_arc in names
    assert cognitive_arc in names
    for database_arc in (legacy_arc, cognitive_arc):
        assert database_arc + "-wal" not in names
        assert database_arc + "-shm" not in names

    provider.shutdown()
    restored_home = tmp_path / "restored-home"
    monkeypatch.setenv("HERMES_HOME", str(restored_home))
    pinned_backup.run_import(SimpleNamespace(zipfile=str(archive), force=True))
    restored = _load_real_hermes_provider(monkeypatch, hermes_root, restored_home)
    restored.initialize(
        "backup-session",
        hermes_home=str(restored_home),
        agent_identity="backup",
        platform="cli",
        user_id="rich",
    )
    legacy_search = _tool(restored, "atlas_memory_search", {"query": "copper protocol"})
    assert [row["memory_id"] for row in legacy_search["memories"]] == [legacy_id]
    assert any(row["memory_id"] == legacy_id for row in _tool(restored, "atlas_memory_list", {})["memories"])
    restored_cognitive = _tool(
        restored, "atlas_memory_get", {"memory_id": cognitive_id}
    )
    assert restored_cognitive["cognitive"]["current_revision"]["content"] == {
        "backup_fact": "cognitive copper"
    }
    assert restored_cognitive["cognitive_audit"]["audit_events"][0][
        "event_type"
    ] == "item_created"
    restored.shutdown()


def test_precompress_config_backup_and_nonprimary_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    schema = {field["key"] for field in provider.get_config_schema()}
    assert schema == {
        "data_dir",
        "prefetch_limit",
        "capture_turns",
        "max_turn_chars",
        "cognitive_url",
        "cognitive_expected_scope",
        "cognitive_token",
    }

    external = tmp_path / "external-atlas"
    provider.save_config(
        {"data_dir": str(external), "prefetch_limit": 3, "capture_turns": True},
        str(home),
    )
    provider.initialize("before", hermes_home=str(home), agent_identity="default")
    assert provider.backup_paths() == [str(external.resolve())]
    provider.on_session_switch("after", parent_session_id="before")
    assert provider._session_id == "after"
    assert provider.on_pre_compress(
        [{"role": "user", "content": "Compression keeps the saffron protocol."}]
    ) == ""
    provider.shutdown()

    restarted = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    restarted.initialize("restart", hermes_home=str(home), agent_identity="default")
    result = _tool(restarted, "atlas_memory_search", {"query": "saffron protocol"})
    assert result["count"] == 1
    assert result["memories"][0]["kind"] == "pre_compress"
    restarted.shutdown()

    default_home = tmp_path / "default-home"
    _install_fixture(default_home)
    monkeypatch.delenv("ATLAS_HERMES_DATA_DIR", raising=False)
    default_provider = _load_real_hermes_provider(monkeypatch, hermes_root, default_home)
    default_provider.initialize(
        "cron-session",
        hermes_home=str(default_home),
        agent_identity="default",
        agent_context="cron",
    )
    assert default_provider.backup_paths() == []
    default_provider.sync_turn("Do not capture cron prompt", "Skipped")
    default_provider.shutdown()

    check = _load_real_hermes_provider(monkeypatch, hermes_root, default_home)
    check.initialize("primary", hermes_home=str(default_home), agent_identity="default")
    assert _tool(check, "atlas_memory_list", {})["count"] == 0
    check.shutdown()


def test_posix_installer_targets_hermes_home(tmp_path: Path) -> None:
    home = tmp_path / "custom-home"
    legacy = home / "plugins" / "atlas" / "cognitive-kernel"
    legacy.mkdir(parents=True)
    (legacy / "stub.py").write_text("legacy stub", encoding="utf-8")
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    subprocess.run(
        ["bash", str(PACKAGE_ROOT / "install.sh"), "--no-activate"],
        check=True,
        cwd=ATLAS_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    destination = home / "plugins" / "atlas"
    assert (destination / "__init__.py").exists()
    assert (destination / "store.py").exists()
    assert (destination / "cognitive_client.py").exists()
    assert (destination / "plugin.yaml").exists()
    assert (destination / "cognitive-service" / "server.py").exists()
    assert (destination / "cognitive-service" / "service_core.py").exists()
    assert (destination / "cognitive-service" / "schema.sql").exists()
    assert not (destination / "cognitive-kernel").exists()


def test_windows_installer_is_portable() -> None:
    script = (PACKAGE_ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "$env:HERMES_HOME" in script
    assert "plugins\\atlas" in script
    assert "hermes memory setup atlas" in script
    assert "cognitive-service" in script
    assert "cognitive_client.py" in script
    assert 'Join-Path $Destination "cognitive-kernel"' in script
    assert "Remove-Item $StalePath -Recurse -Force" in script


def test_lossy_display_names_cannot_cross_profile_platform_or_user_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    shared_data = tmp_path / "shared-atlas"
    monkeypatch.setenv("ATLAS_HERMES_DATA_DIR", str(shared_data))
    home_a = tmp_path / "profile-a"
    home_b = tmp_path / "profile-b"
    _install_fixture(home_a)
    _install_fixture(home_b)

    first = _load_real_hermes_provider(monkeypatch, hermes_root, home_a)
    first.initialize(
        "one",
        hermes_home=str(home_a),
        agent_identity="team/a",
        platform="telegram",
        user_id="user/a",
        user_id_alt="stable/a",
    )
    first.sync_turn("Top secret indigo scope", "Stored")
    first.shutdown()

    second = _load_real_hermes_provider(monkeypatch, hermes_root, home_b)
    second.initialize(
        "two",
        hermes_home=str(home_b),
        agent_identity="team a",
        platform="discord",
        user_id="user a",
        user_id_alt="stable a",
    )
    assert _tool(second, "atlas_memory_search", {"query": "indigo"})["count"] == 0
    assert first._profile_name != second._profile_name
    assert first._profile_id != second._profile_id
    second.shutdown()


def test_search_does_not_hide_relevant_memory_older_than_200_rows(tmp_path: Path) -> None:
    import importlib.util

    store_path = PACKAGE_ROOT / "atlas" / "store.py"
    spec = importlib.util.spec_from_file_location("atlas_native_store_regression", store_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.AtlasSQLiteStore(tmp_path / "search.sqlite3")
    oldest_id = store.add(
        profile_id="profile",
        session_id="old",
        kind="turn",
        content="The unique zephyr protocol is authoritative.",
    )
    for index in range(205):
        store.add(
            profile_id="profile",
            session_id="new",
            kind="turn",
            content=f"Unrelated recent record {index}",
        )
    hits = store.search("zephyr", profile_id="profile", limit=5)
    assert [hit["memory_id"] for hit in hits] == [oldest_id]


def test_shutdown_reports_undrained_writer_and_retains_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    provider.initialize("blocked", hermes_home=str(home), agent_identity="default")
    gate = threading.Event()
    original_add = provider._store.add

    def blocked_add(**kwargs):
        gate.wait(timeout=10)
        return original_add(**kwargs)

    provider._store.add = blocked_add
    provider.sync_turn("Final queued obsidian fact", "Stored")
    deadline = time.monotonic() + 1
    while provider._write_queue.qsize() and time.monotonic() < deadline:
        time.sleep(0.01)
    with pytest.raises(RuntimeError, match="shutdown is incomplete"):
        provider.shutdown()
    assert provider._writer is not None and provider._writer.is_alive()
    gate.set()
    provider._writer.join(timeout=2)
    provider.shutdown()

    restarted = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    restarted.initialize("restart", hermes_home=str(home), agent_identity="default")
    assert _tool(restarted, "atlas_memory_search", {"query": "obsidian"})["count"] == 1
    restarted.shutdown()
