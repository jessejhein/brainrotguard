"""Persistence for triage decisions.

Separate connection and table from VideoStore so the bridge can be added and
removed without touching the videos schema. Every verdict is written once, keyed
by ``request_id`` (``profile_id:video_id``), which is what makes the callback
idempotent under Telegram/Hermes retries.
"""

import json
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS triage_decisions (
    request_id      TEXT PRIMARY KEY,
    profile_id      TEXT NOT NULL,
    video_id        TEXT NOT NULL,
    verdict         TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 0,
    rank            TEXT NOT NULL DEFAULT '',
    category        TEXT,
    summary         TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL DEFAULT '',
    mode            TEXT NOT NULL DEFAULT 'shadow',
    outcome         TEXT NOT NULL DEFAULT 'logged',
    latency_ms      INTEGER,
    raw             TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_triage_created ON triage_decisions(created_at);
"""

OUTCOMES = ("logged", "replied", "skipped_decided", "late", "unknown_request", "timeout")


class TriageStore:
    """Small SQLite store for triage decisions (WAL, single writer lock)."""

    def __init__(self, db_path: str = "db/videos.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError:
            pass
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    def record(self, *, request_id: str, profile_id: str, video_id: str, verdict: str,
               confidence: float = 0.0, rank: str = "", category: str | None = None,
               summary: str = "", reason: str = "", mode: str = "shadow",
               outcome: str = "logged", latency_ms: int | None = None,
               raw: dict | list | None = None) -> bool:
        """Insert one decision. Returns False when the request already has one."""
        payload = json.dumps(raw, ensure_ascii=False) if raw is not None else ""
        with self._lock:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO triage_decisions
                (request_id, profile_id, video_id, verdict, confidence, rank, category,
                 summary, reason, mode, outcome, latency_ms, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (request_id, profile_id, video_id, verdict, float(confidence or 0), rank or "",
                 category, summary or "", reason or "", mode, outcome, latency_ms, payload),
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def get(self, request_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM triage_decisions WHERE request_id = ?", (request_id,)
            ).fetchone()
        return dict(row) if row else None

    def set_outcome(self, request_id: str, outcome: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE triage_decisions SET outcome = ? WHERE request_id = ?", (outcome, request_id)
            )
            self.conn.commit()

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM triage_decisions ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self.conn.close()
