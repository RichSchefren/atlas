"""BenchmarkSystem adapters for BusinessMemBench.

Each module wires one system-under-test to the BenchmarkSystem protocol
the harness expects.

Currently shipped:
  - atlas    — the host system itself; routes through AtlasMCPServer
  - vanilla  — no-memory baseline (returns canned None answers); useful
               for quantifying lift over zero-memory.

Wired in W1 follow-ups (need their respective Python clients):
  - graphiti, memori, letta, mem0, kumiho, mempalace
"""

from benchmarks.business_mem_bench.adapters.vanilla import VanillaSystem

__all__ = ["VanillaSystem"]
