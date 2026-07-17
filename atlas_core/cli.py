"""Atlas umbrella CLI — one `atlas` command over the existing surfaces.

Before this entry point, a `pip install`ed user could run nothing: every
capability lived behind a `PYTHONPATH=. python -m ...` incantation, a raw
Cypher query, or a curl call, even though the underlying functions were all
implemented and tested. This module is the thin dispatch layer that turns
those functions into subcommands. It reimplements no logic — each handler is
a wrapper over a function that already ships.

Subcommands:
  atlas search <query>   — semantic retrieval via the vault-search daemon
                           (atlas_core.retrieval.VaultSearchClient.search)
  atlas queue            — list pending adjudication candidates
                           (atlas_core.trust.QuarantineStore.list_pending)
  atlas status           — most recent ingestion-daemon health row
                           (atlas_core.daemon.health.HealthLogger.latest)
  atlas ingest           — run one ingestion cycle
                           (atlas_core.daemon.cycle.run_ingestion_cycle)
  atlas demo             — run the end-to-end demo (delegates to demo.sh)

Registered as the `atlas` console script in pyproject.toml.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROG = "atlas"


# ─── Shared config helpers (match the env conventions of the sibling surfaces) ─


def _data_dir() -> Path:
    """Atlas data directory. Mirrors the daemon / adjudicate CLI default."""
    return Path(os.path.expanduser(os.environ.get("ATLAS_DATA_DIR", "~/.atlas")))


def _quarantine_db() -> Path:
    """Candidate (quarantine) DB path.

    Honors ATLAS_QUARANTINE_DB first (the var the MCP adapter reads), then
    falls back to ATLAS_DATA_DIR/candidates.db (the daemon / adjudicate default).
    """
    override = os.environ.get("ATLAS_QUARANTINE_DB")
    if override:
        return Path(os.path.expanduser(override))
    return _data_dir() / "candidates.db"


def _print_json(obj: object) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


# ─── search ───────────────────────────────────────────────────────────────────


def cmd_search(args: argparse.Namespace) -> int:
    """Delegate to VaultSearchClient.search — no retrieval logic lives here."""
    from atlas_core.retrieval import DEFAULT_VAULT_SEARCH_URL, VaultSearchClient

    base_url = args.url or DEFAULT_VAULT_SEARCH_URL
    client = VaultSearchClient(base_url=base_url)
    hits = client.search(args.query, k=args.k)

    if args.json:
        _print_json([
            {"path": h.path, "score": h.score, "excerpt": h.excerpt}
            for h in hits
        ])
        return 0

    if not hits:
        print(f"No hits for {args.query!r} (vault-search at {base_url}).")
        return 0

    print(f"{len(hits)} hit(s) for {args.query!r}:\n")
    for h in hits:
        print(f"  [{h.score:.3f}] {h.path}")
        if h.excerpt:
            print(f"          {h.excerpt.strip()[:160]}")
    return 0


# ─── queue ─────────────────────────────────────────────────────────────────────


def cmd_queue(args: argparse.Namespace) -> int:
    """Delegate to QuarantineStore.list_pending — the adjudication backlog."""
    from atlas_core.trust import QuarantineStore

    db_path = _quarantine_db()
    if not db_path.exists():
        print(f"error: {db_path} does not exist. Run `atlas ingest` first.", file=sys.stderr)
        return 2

    store = QuarantineStore(db_path)
    rows = store.list_pending(lane=args.lane)[: args.limit]

    if args.json:
        _print_json(rows)
        return 0

    if not rows:
        scope = f" on lane {args.lane!r}" if args.lane else ""
        print(f"No pending candidates{scope}.")
        return 0

    print(f"{len(rows)} pending candidate(s):\n")
    for r in rows:
        conf = float(r.get("confidence", 0.0))
        print(
            f"  {r.get('candidate_id', '?')}  [{r.get('lane', '?')}]  "
            f"conf={conf:.2f}  {r.get('subject_kref', '?')} "
            f"{r.get('predicate', '?')} {r.get('object_value', '?')}"
        )
    return 0


# ─── status ────────────────────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> int:
    """Delegate to HealthLogger.latest — the last ingestion-cycle health row."""
    from atlas_core.daemon.health import HealthLogger

    row = HealthLogger("com.atlas.ingestion").latest()

    if args.json:
        _print_json(row.to_dict() if row is not None else None)
        return 0

    if row is None:
        print("No ingestion cycles recorded yet. Run `atlas ingest`.")
        return 0

    state = "ok" if row.success else "FAILED"
    print(f"ingestion daemon: {state}")
    print(f"  started : {row.started_at}")
    print(f"  finished: {row.finished_at}")
    print(f"  elapsed : {row.elapsed_sec:.2f}s")
    if row.summary:
        print(f"  summary : {json.dumps(row.summary, sort_keys=True)}")
    if row.error:
        print(f"  error   : {row.error}")
    return 0 if row.success else 1


# ─── ingest ────────────────────────────────────────────────────────────────────


def cmd_ingest(args: argparse.Namespace) -> int:
    """Delegate to run_ingestion_cycle — one orchestration pass, returns its code."""
    from atlas_core.daemon.cycle import run_ingestion_cycle

    return run_ingestion_cycle()


# ─── demo ──────────────────────────────────────────────────────────────────────


def _find_demo_script() -> Path | None:
    """Locate demo.sh.

    demo.sh lives at the repo root and is intentionally excluded from the
    packaged distribution (the sdist allowlist ships only atlas_core/** plus
    metadata), so `atlas demo` resolves it from a source checkout. Resolution
    order: ATLAS_DEMO_SCRIPT override, then the repo root above this package,
    then the current working directory.
    """
    override = os.environ.get("ATLAS_DEMO_SCRIPT")
    if override:
        p = Path(os.path.expanduser(override))
        return p if p.exists() else None

    repo_root = Path(__file__).resolve().parent.parent
    candidate = repo_root / "demo.sh"
    if candidate.exists():
        return candidate

    cwd_candidate = Path.cwd() / "demo.sh"
    if cwd_candidate.exists():
        return cwd_candidate

    return None


def cmd_demo(args: argparse.Namespace) -> int:
    """Delegate to demo.sh — the existing end-to-end demo path.

    This is a minimal wrapper: it locates the script and shells out, passing
    through any extra args (e.g. --quiet, --reset). demo.sh's own environment
    requirements (a repo-root .venv, a reachable Neo4j) are unchanged and out
    of scope for this entry point.
    """
    script = _find_demo_script()
    if script is None:
        print(
            "error: demo.sh not found. It ships only in a source checkout, "
            "not in the installed package. Run from the repo root, or set "
            "ATLAS_DEMO_SCRIPT to its path.",
            file=sys.stderr,
        )
        return 2

    try:
        completed = subprocess.run([str(script), *args.demo_args])  # noqa: S603
    except OSError as exc:
        print(f"error: could not run {script}: {exc}", file=sys.stderr)
        return 2
    return completed.returncode


# ─── parser ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Atlas — local-first cognitive memory. One command over the graph.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_search = sub.add_parser("search", help="semantic search over the vault")
    p_search.add_argument("query", help="search query")
    p_search.add_argument("-k", type=int, default=10, help="max hits (default: 10)")
    p_search.add_argument("--url", default=None, help="vault-search base URL")
    p_search.add_argument("--json", action="store_true", help="emit JSON")
    p_search.set_defaults(func=cmd_search)

    p_queue = sub.add_parser("queue", help="list pending adjudication candidates")
    p_queue.add_argument("--lane", default=None, help="filter by lane")
    p_queue.add_argument("--limit", type=int, default=50, help="max rows (default: 50)")
    p_queue.add_argument("--json", action="store_true", help="emit JSON")
    p_queue.set_defaults(func=cmd_queue)

    p_status = sub.add_parser("status", help="show the last ingestion-cycle health")
    p_status.add_argument("--json", action="store_true", help="emit JSON")
    p_status.set_defaults(func=cmd_status)

    p_ingest = sub.add_parser("ingest", help="run one ingestion cycle")
    p_ingest.set_defaults(func=cmd_ingest)

    # demo passes any extra flags (e.g. --quiet, --reset) straight through to
    # demo.sh. Those are collected as unrecognized args in main() rather than
    # declared here, so leading-dash flags aren't intercepted by this parser.
    p_demo = sub.add_parser("demo", help="run the end-to-end demo (delegates to demo.sh)")
    p_demo.set_defaults(func=cmd_demo, demo_args=[])

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, extras = parser.parse_known_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help()
        return 2
    if args.command == "demo":
        args.demo_args = extras
    elif extras:
        parser.error(f"unrecognized arguments: {' '.join(extras)}")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
