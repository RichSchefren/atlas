"""Full BusinessMemBench runner — runs every adapter the host machine
can support and writes a JSON head-to-head matrix.

Run:
    PYTHONPATH=. python scripts/run_bmb.py [--corpus DIR] [--seed N]

Adapters that need API keys / external services raise
MissingClientError on reset() and are skipped with a clear log line.
The output is always honest about which systems were actually run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

# Repo-relative path for direct invocation
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus", type=Path, default=Path("/tmp/bmb_run"),
        help="Where the corpus + gold get written",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="RNG seed for the corpus",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("/tmp/bmb_run/results.json"),
        help="Output JSON file for the head-to-head matrix",
    )
    args = parser.parse_args()

    from benchmarks.business_mem_bench import BenchmarkRunner
    from benchmarks.business_mem_bench.adapters import (
        AtlasSystem,
        GraphitiSystem,
        KumihoSystem,
        LettaSystem,
        Mem0System,
        MemoriSystem,
        MemPalaceSystem,
        MissingClientError,
        VanillaSystem,
    )
    from benchmarks.business_mem_bench.corpus_generator import (
        generate_corpus,
        generate_questions,
    )

    if args.corpus.exists():
        shutil.rmtree(args.corpus)
    print(f"Generating corpus → {args.corpus}")
    generate_corpus(args.corpus, seed=args.seed)
    counts = generate_questions(args.corpus, seed=args.seed)
    n_total = sum(counts.values())
    print(f"Questions: {n_total} across {len(counts)} categories")
    print()

    # Order matters — cheaper / always-runnable first
    systems = [
        VanillaSystem,
        GraphitiSystem,
        AtlasSystem,
        Mem0System,
        LettaSystem,
        MemoriSystem,
        KumihoSystem,
        MemPalaceSystem,
    ]

    matrix: dict[str, dict] = {}
    for cls in systems:
        sys_inst = cls()
        name = sys_inst.name
        print(f"━━ {name} ━━")
        try:
            started = time.time()
            report = BenchmarkRunner(
                system=sys_inst,
                corpus_dir=args.corpus,
                gold_dir=args.corpus / "gold",
            ).run()
            elapsed = time.time() - started
            n_perfect = sum(c.n_perfect for c in report.per_category.values())
            print(f"  overall {report.overall_mean_score:.3f} "
                  f"({n_perfect}/{n_total} perfect, {elapsed:.1f}s)")
            for cat, c in report.per_category.items():
                print(f"    {cat.value:<14} {c.mean_score:.3f}  "
                      f"perfect={c.n_perfect}/{c.n_questions}")
            matrix[name] = report.to_dict()
        except MissingClientError as exc:
            print(f"  SKIP — {exc}")
            matrix[name] = {"skipped": True, "reason": str(exc)}
        except Exception as exc:
            print(f"  ERROR — {type(exc).__name__}: {exc}")
            matrix[name] = {"errored": True, "reason": f"{type(exc).__name__}: {exc}"}
        finally:
            if hasattr(sys_inst, "close"):
                try:
                    sys_inst.close()
                except Exception:
                    pass

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(matrix, indent=2))
    print()
    print(f"Matrix written → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
