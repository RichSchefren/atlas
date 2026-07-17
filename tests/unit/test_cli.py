"""Unit tests for the `atlas` umbrella CLI.

The CLI is a thin dispatch layer: every subcommand forwards to a function
that already ships and is tested elsewhere. These tests exercise argument
parsing and dispatch with the delegated functions mocked, so they need no
Neo4j, no vault-search daemon, and no filesystem state.
"""

from __future__ import annotations

import json

import pytest

from atlas_core import cli

# ─── parser wiring ─────────────────────────────────────────────────────────────


def test_no_command_prints_help_and_returns_2(capsys):
    rc = cli.main([])
    out = capsys.readouterr().out
    assert rc == 2
    assert "usage" in out.lower()
    # Every subcommand should be advertised in the top-level help.
    for name in ("search", "queue", "status", "ingest", "demo"):
        assert name in out


@pytest.mark.parametrize("argv", [["--help"], ["search", "--help"], ["queue", "--help"],
                                  ["status", "--help"], ["ingest", "--help"], ["demo", "--help"]])
def test_help_exits_zero(argv):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 0


def test_each_subcommand_dispatches_to_its_handler():
    parser = cli.build_parser()
    expected = {
        "search": cli.cmd_search,
        "queue": cli.cmd_queue,
        "status": cli.cmd_status,
        "ingest": cli.cmd_ingest,
        "demo": cli.cmd_demo,
    }
    for name, handler in expected.items():
        args = parser.parse_args([name] if name != "search" else [name, "q"])
        assert args.func is handler


# ─── search ────────────────────────────────────────────────────────────────────


class _FakeHit:
    def __init__(self, path, score, excerpt):
        self.path = path
        self.score = score
        self.excerpt = excerpt


def test_search_delegates_to_vault_search_client(monkeypatch, capsys):
    captured = {}

    class FakeClient:
        def __init__(self, *, base_url):
            captured["base_url"] = base_url

        def search(self, query, *, k):
            captured["query"] = query
            captured["k"] = k
            return [_FakeHit("notes/a.md", 0.91, "an excerpt")]

    monkeypatch.setattr("atlas_core.retrieval.VaultSearchClient", FakeClient)

    rc = cli.main(["search", "quarterly plan", "-k", "3", "--url", "http://x:9999"])
    out = capsys.readouterr().out

    assert rc == 0
    assert captured == {"base_url": "http://x:9999", "query": "quarterly plan", "k": 3}
    assert "notes/a.md" in out
    assert "0.910" in out


def test_search_json_output(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, *, base_url):
            pass

        def search(self, query, *, k):
            return [_FakeHit("p.md", 0.5, "ex")]

    monkeypatch.setattr("atlas_core.retrieval.VaultSearchClient", FakeClient)

    rc = cli.main(["search", "x", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload == [{"path": "p.md", "score": 0.5, "excerpt": "ex"}]


def test_search_empty_results(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, *, base_url):
            pass

        def search(self, query, *, k):
            return []

    monkeypatch.setattr("atlas_core.retrieval.VaultSearchClient", FakeClient)
    rc = cli.main(["search", "nothing"])
    assert rc == 0
    assert "No hits" in capsys.readouterr().out


# ─── queue ─────────────────────────────────────────────────────────────────────


def test_queue_delegates_to_list_pending(monkeypatch, tmp_path, capsys):
    db = tmp_path / "candidates.db"
    db.write_text("")  # existence is all the handler checks
    monkeypatch.setenv("ATLAS_QUARANTINE_DB", str(db))

    captured = {}

    class FakeStore:
        def __init__(self, path):
            captured["path"] = path

        def list_pending(self, *, lane):
            captured["lane"] = lane
            return [
                {"candidate_id": "c1", "lane": "atlas_vault", "confidence": 0.7,
                 "subject_kref": "S", "predicate": "P", "object_value": "O"},
            ]

    monkeypatch.setattr("atlas_core.trust.QuarantineStore", FakeStore)

    rc = cli.main(["queue", "--lane", "atlas_vault", "--limit", "10"])
    out = capsys.readouterr().out
    assert rc == 0
    assert captured["lane"] == "atlas_vault"
    assert str(captured["path"]) == str(db)
    assert "c1" in out
    assert "conf=0.70" in out


def test_queue_limit_truncates(monkeypatch, tmp_path, capsys):
    db = tmp_path / "candidates.db"
    db.write_text("")
    monkeypatch.setenv("ATLAS_QUARANTINE_DB", str(db))

    class FakeStore:
        def __init__(self, path):
            pass

        def list_pending(self, *, lane):
            return [{"candidate_id": f"c{i}", "lane": "l", "confidence": 0.5,
                     "subject_kref": "s", "predicate": "p", "object_value": "o"}
                    for i in range(100)]

    monkeypatch.setattr("atlas_core.trust.QuarantineStore", FakeStore)
    rc = cli.main(["queue", "--limit", "2", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert len(payload) == 2


def test_queue_missing_db_returns_2(monkeypatch, tmp_path, capsys):
    missing = tmp_path / "nope.db"
    monkeypatch.setenv("ATLAS_QUARANTINE_DB", str(missing))
    rc = cli.main(["queue"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "does not exist" in err


# ─── status ────────────────────────────────────────────────────────────────────


class _FakeRow:
    def __init__(self, success):
        self.success = success
        self.started_at = "2026-07-16T00:00:00Z"
        self.finished_at = "2026-07-16T00:00:06Z"
        self.elapsed_sec = 6.0
        self.summary = {"ingested": 3}
        self.error = None if success else "boom"

    def to_dict(self):
        return {"success": self.success, "started_at": self.started_at}


def test_status_ok_row(monkeypatch, capsys):
    class FakeLogger:
        def __init__(self, name):
            pass

        def latest(self):
            return _FakeRow(success=True)

    monkeypatch.setattr("atlas_core.daemon.health.HealthLogger", FakeLogger)
    rc = cli.main(["status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ok" in out
    assert "ingested" in out


def test_status_failed_row_returns_1(monkeypatch, capsys):
    class FakeLogger:
        def __init__(self, name):
            pass

        def latest(self):
            return _FakeRow(success=False)

    monkeypatch.setattr("atlas_core.daemon.health.HealthLogger", FakeLogger)
    rc = cli.main(["status"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAILED" in out
    assert "boom" in out


def test_status_no_history(monkeypatch, capsys):
    class FakeLogger:
        def __init__(self, name):
            pass

        def latest(self):
            return None

    monkeypatch.setattr("atlas_core.daemon.health.HealthLogger", FakeLogger)
    rc = cli.main(["status", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) is None


# ─── ingest ────────────────────────────────────────────────────────────────────


def test_ingest_delegates_and_returns_code(monkeypatch):
    calls = {"n": 0}

    def fake_cycle():
        calls["n"] += 1
        return 7

    monkeypatch.setattr("atlas_core.daemon.cycle.run_ingestion_cycle", fake_cycle)
    rc = cli.main(["ingest"])
    assert rc == 7
    assert calls["n"] == 1


# ─── demo ──────────────────────────────────────────────────────────────────────


def test_demo_delegates_to_demo_sh(monkeypatch, tmp_path):
    fake_script = tmp_path / "demo.sh"
    fake_script.write_text("#!/bin/sh\n")
    monkeypatch.setattr(cli, "_find_demo_script", lambda: fake_script)

    captured = {}

    class FakeCompleted:
        returncode = 0

    def fake_run(cmd, *a, **k):
        captured["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    rc = cli.main(["demo", "--quiet", "--reset"])
    assert rc == 0
    assert captured["cmd"] == [str(fake_script), "--quiet", "--reset"]


def test_demo_missing_script_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_find_demo_script", lambda: None)
    rc = cli.main(["demo"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "demo.sh not found" in err


def test_demo_propagates_returncode(monkeypatch, tmp_path):
    fake_script = tmp_path / "demo.sh"
    fake_script.write_text("#!/bin/sh\n")
    monkeypatch.setattr(cli, "_find_demo_script", lambda: fake_script)

    class FakeCompleted:
        returncode = 3

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, *a, **k: FakeCompleted())
    assert cli.main(["demo"]) == 3


def test_find_demo_script_env_override(monkeypatch, tmp_path):
    script = tmp_path / "custom-demo.sh"
    script.write_text("#!/bin/sh\n")
    monkeypatch.setenv("ATLAS_DEMO_SCRIPT", str(script))
    assert cli._find_demo_script() == script


def test_find_demo_script_repo_root(monkeypatch):
    # The real demo.sh sits at the repo root above the package; no override.
    monkeypatch.delenv("ATLAS_DEMO_SCRIPT", raising=False)
    found = cli._find_demo_script()
    assert found is not None
    assert found.name == "demo.sh"
