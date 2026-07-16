"""Dependency-free Atlas SQLite memory store for the Hermes provider."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AtlasSQLiteStore:
    """Profile-scoped, audit-preserving SQLite memory and retrieval store.

    Every operation opens and closes its own connection. That keeps the store
    safe across Hermes's background worker threads and avoids Windows teardown
    failures caused by lingering SQLite handles.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS atlas_memories (
                    memory_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    profile_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    forgotten_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_atlas_memory_profile
                    ON atlas_memories(profile_id, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_atlas_memory_session
                    ON atlas_memories(profile_id, session_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS atlas_memory_events (
                    event_id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES atlas_memories(memory_id)
                );
                CREATE INDEX IF NOT EXISTS idx_atlas_events_memory
                    ON atlas_memory_events(memory_id, recorded_at);
                """
            )

    @staticmethod
    def _fingerprint(profile_id: str, session_id: str, kind: str, content: str) -> str:
        canonical = json.dumps(
            [profile_id, session_id, kind, content],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _public(row: sqlite3.Row | dict[str, Any], score: float | None = None) -> dict[str, Any]:
        data = dict(row)
        return {
            "memory_id": data["memory_id"],
            "profile_id": data["profile_id"],
            "session_id": data["session_id"],
            "kind": data["kind"],
            "content": data["content"],
            "metadata": json.loads(data["metadata_json"]),
            "status": data["status"],
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "score": score,
        }

    def add(
        self,
        *,
        profile_id: str,
        session_id: str,
        kind: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        content = content.strip()
        if not content:
            raise ValueError("memory content cannot be empty")
        fingerprint = self._fingerprint(profile_id, session_id, kind, content)
        now = _utc_now()
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT memory_id FROM atlas_memories WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if existing:
                return str(existing["memory_id"])

            memory_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO atlas_memories (
                    memory_id, fingerprint, profile_id, session_id, kind,
                    content, metadata_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    memory_id,
                    fingerprint,
                    profile_id,
                    session_id,
                    kind,
                    content,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO atlas_memory_events (
                    event_id, memory_id, event_type, recorded_at, payload_json
                ) VALUES (?, ?, 'memory.created', ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    memory_id,
                    now,
                    json.dumps({"kind": kind, "session_id": session_id}, sort_keys=True),
                ),
            )
        return memory_id

    def get(self, memory_id: str, *, profile_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM atlas_memories
                WHERE memory_id = ? AND profile_id = ? AND status = 'active'
                """,
                (memory_id, profile_id),
            ).fetchone()
        return self._public(row) if row else None

    def list(
        self,
        *,
        profile_id: str,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        sql = "SELECT * FROM atlas_memories WHERE profile_id = ? AND status = 'active'"
        params: list[Any] = [profile_id]
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(min(limit, 200))
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._public(row) for row in rows]

    def search(
        self,
        query: str,
        *,
        profile_id: str,
        session_id: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        terms = tuple(
            dict.fromkeys(
                token
                for token in re.findall(r"[a-z0-9_]+", query.lower())
                if len(token) > 1
            )
        )
        if not terms or limit < 1:
            return []
        rows = self.list(profile_id=profile_id, session_id=session_id, limit=200)
        phrase = " ".join(terms)
        ranked: list[tuple[float, str, dict[str, Any]]] = []
        for row in rows:
            text = row["content"].lower()
            matched = sum(term in text for term in terms)
            if not matched:
                continue
            coverage = matched / len(terms)
            exact = 1.0 if phrase in text else 0.0
            recency = 0.05
            score = min(1.0, 0.75 * coverage + 0.20 * exact + recency)
            row["score"] = round(score, 6)
            ranked.append((score, row["updated_at"], row))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[: min(limit, 50)]]

    def forget(self, memory_id: str, *, profile_id: str) -> bool:
        now = _utc_now()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT status FROM atlas_memories WHERE memory_id = ? AND profile_id = ?",
                (memory_id, profile_id),
            ).fetchone()
            if row is None:
                return False
            if row["status"] != "forgotten":
                conn.execute(
                    """
                    UPDATE atlas_memories
                    SET status = 'forgotten', forgotten_at = ?, updated_at = ?
                    WHERE memory_id = ? AND profile_id = ?
                    """,
                    (now, now, memory_id, profile_id),
                )
                conn.execute(
                    """
                    INSERT INTO atlas_memory_events (
                        event_id, memory_id, event_type, recorded_at, payload_json
                    ) VALUES (?, ?, 'memory.forgotten', ?, '{}')
                    """,
                    (uuid.uuid4().hex, memory_id, now),
                )
        return True

    def count(self, *, profile_id: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM atlas_memories
                WHERE profile_id = ? AND status = 'active'
                """,
                (profile_id,),
            ).fetchone()
        return int(row["count"])
