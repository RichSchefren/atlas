"""Atlas Coffee Roasting Co. — synthetic business corpus + question
generator for BusinessMemBench.

Deterministic from a single seed so benchmark runs are reproducible.
Covers a 90-day operational window (2026-01-01 → 2026-03-31) with
realistic events: pricing changes, hires, decisions, contradictions,
deprecations.

Public surface:
  generate_corpus(out_dir, seed=42)         — writes corpus/ + ground_truth.json
  generate_questions(out_dir, seed=42)      — writes gold/<category>.jsonl

Spec: 08 - BusinessMemBench Design.md § 2.2 (synthetic business)
"""

from benchmarks.business_mem_bench.corpus_generator.business import (
    AtlasCoffeeWorld,
)
from benchmarks.business_mem_bench.corpus_generator.events import (
    EventLog,
    generate_events,
)
from benchmarks.business_mem_bench.corpus_generator.generator import (
    generate_corpus,
    generate_questions,
)

__all__ = [
    "AtlasCoffeeWorld",
    "EventLog",
    "generate_events",
    "generate_corpus",
    "generate_questions",
]
