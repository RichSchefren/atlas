"""Contract tests for the native Atlas plugin against pinned Hermes Agent."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

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
    shutil.copy2(PACKAGE_ROOT / "plugin.yaml", destination / "plugin.yaml")
    return destination


def _load_real_hermes_provider(monkeypatch: pytest.MonkeyPatch, hermes_root: Path, home: Path):
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_constants

    importlib.reload(hermes_constants)
    memory_plugins = importlib.import_module("plugins.memory")
    destination = home / "plugins" / "atlas"
    provider = memory_plugins._load_provider_from_dir(destination)
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
    assert [schema["name"] for schema in provider.get_tool_schemas()] == [
        "atlas_memory_search",
        "atlas_memory_get",
        "atlas_memory_list",
        "atlas_memory_forget",
    ]


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
    assert search["backend"] == "sqlite"
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


def test_precompress_config_backup_and_nonprimary_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermes_root: Path,
) -> None:
    home = tmp_path / ".hermes"
    _install_fixture(home)
    provider = _load_real_hermes_provider(monkeypatch, hermes_root, home)
    schema = {field["key"] for field in provider.get_config_schema()}
    assert schema == {"data_dir", "prefetch_limit", "capture_turns", "max_turn_chars"}

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
    assert (destination / "plugin.yaml").exists()


def test_windows_installer_is_portable() -> None:
    script = (PACKAGE_ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "$env:HERMES_HOME" in script
    assert "plugins\\atlas" in script
    assert "hermes memory setup atlas" in script
