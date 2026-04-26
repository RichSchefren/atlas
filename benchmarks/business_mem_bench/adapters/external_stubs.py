"""External baseline stubs — Mem0, Letta, Memori, Kumiho, MemPalace.

Each adapter raises a clear `MissingClientError` from `reset()` with the
exact pip install instructions. The harness catches and logs, allowing
benchmark runs to proceed against the systems that ARE installed.

This pattern keeps the benchmark matrix complete in the repo while
requiring no upfront install of every baseline. Rich (or CI) installs
the ones we want to compare against per benchmark cycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class MissingClientError(RuntimeError):
    """Raised when a baseline's Python client isn't installed."""


def _stub(name: str, install_hint: str):
    """Factory — produces a BenchmarkSystem that fails fast with a hint."""
    class _Stub:
        def __init__(self, **kwargs):
            self._kwargs = kwargs
        @property
        def name(self) -> str:
            return name

        def reset(self) -> None:
            raise MissingClientError(
                f"{name} client not installed. {install_hint}"
            )

        def ingest(self, corpus_dir: Path) -> None:
            raise MissingClientError(
                f"{name} client not installed. {install_hint}"
            )

        def query(self, payload: dict[str, Any]) -> Any:
            raise MissingClientError(
                f"{name} client not installed. {install_hint}"
            )

    _Stub.__name__ = f"{name.capitalize()}System"
    return _Stub


Mem0System = _stub("mem0", "pip install mem0ai")
LettaSystem = _stub("letta", "pip install letta")
MemoriSystem = _stub("memori", "pip install memori-ai")
KumihoSystem = _stub("kumiho", "pip install kumiho-sdk")
MemPalaceSystem = _stub("mempalace", "pip install mempalace")
