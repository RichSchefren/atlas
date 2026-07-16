"""Windows CI smoke for the installed native Atlas Hermes provider."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

PINNED_HERMES_COMMIT = "b5bd0ef38b538627a0e5d2cbe5d3eef2c38ec792"


def main() -> int:
    upstream = Path(os.environ["HERMES_UPSTREAM"]).resolve()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=upstream,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert commit == PINNED_HERMES_COMMIT
    sys.path.insert(0, str(upstream))

    import hermes_constants

    importlib.reload(hermes_constants)
    memory_plugins = importlib.import_module("plugins.memory")
    provider = memory_plugins.load_memory_provider("atlas")
    assert provider is not None
    provider.initialize(
        "windows-ci",
        hermes_home=os.environ["HERMES_HOME"],
        agent_identity="windows-ci",
        platform="cli",
        user_id="ci",
    )

    from agent.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.add_provider(provider)
    assert manager.has_tool("atlas_memory_store")
    created = json.loads(
        manager.handle_tool_call(
            "atlas_memory_store",
            {
                "kind": "fact",
                "content": {"windows_native": True},
                "confidence_ppm": 900000,
            },
        )
    )
    fetched = json.loads(
        manager.handle_tool_call(
            "atlas_memory_get", {"memory_id": created["memory_id"]}
        )
    )
    assert fetched["cognitive"]["current_revision"]["content"] == {
        "windows_native": True
    }
    process = provider._cognitive._process
    health = provider._cognitive._health()
    assert health["managed_owner"]["instance_id"] == provider._cognitive._owner_instance
    provider.shutdown()
    assert process is not None and process.poll() is not None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
