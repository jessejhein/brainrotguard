"""Persistence for triage decisions.

Separate connection and table from VideoStore so the bridge can be added and
removed without touching the videos schema. Every verdict is written once, keyed
by ``request_id`` (``profile_id:video_id``), which is what makes the callback
idempotent under Telegram/Hermes retries.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone

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
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    applied         TEXT NOT NULL DEFAULT '',
    overridden_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_triage_created ON triage_decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_triage_video ON triage_decisions(profile_id, video_id);

CREATE TABLE IF NOT EXISTS triage_holds (
    request_id  TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL,
    video_id    TEXT NOT NULL,
    video_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns added after the original table shipped. CREATE TABLE IF NOT EXISTS
# does not alter an existing database, so each one is added on open.
_DECISION_COLUMNS = (
    ("applied", "TEXT NOT NULL DEFAULT ''"),
    ("overridden_at", "TEXT"),
)

OUTCOMES = (
    "logged", "replied", "skipped_decided", "late", "unknown_request", "timeout",
    "hold_released", "hold_timeout", "push_failed",
)


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
            self._ensure_decision_columns()
            self.conn.commit()

    def _ensure_decision_columns(self) -> None:
        """Add decision columns that older databases do not have yet."""
        present = {
            row[1] for row in self.conn.execute("PRAGMA table_info(triage_decisions)")
        }
        for name, col_type in _DECISION_COLUMNS:
            if name not in present:
                self.conn.execute(
                    f'ALTER TABLE triage_decisions ADD COLUMN "{name}" {col_type}'
                )

    def record(self, *, request_id: str, profile_id: str, video_id: str, verdict: str,
               confidence: float = 0.0, rank: str = "", category: str | None = None,
               summary: str = "", reason: str = "", mode: str = "shadow",
               outcome: str = "logged", latency_ms: int | None = None,
               raw: dict | list | None = None, applied: str = "") -> bool:
        """Insert one decision. Returns False when the request already has one."""
        payload = json.dumps(raw, ensure_ascii=False) if raw is not None else ""
        with self._lock:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO triage_decisions
                (request_id, profile_id, video_id, verdict, confidence, rank, category,
                 summary, reason, mode, outcome, latency_ms, raw, applied)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (request_id, profile_id, video_id, verdict, float(confidence or 0), rank or "",
                 category, summary or "", reason or "", mode, outcome, latency_ms, payload,
                 applied or ""),
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

    def for_video(self, profile_id: str, video_id: str) -> dict | None:
        """Latest decision for one child's video, if any."""
        with self._lock:
            row = self.conn.execute(
                """
                SELECT * FROM triage_decisions
                WHERE profile_id = ? AND video_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (profile_id, video_id),
            ).fetchone()
        return dict(row) if row else None

    def set_applied(self, request_id: str, applied: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE triage_decisions SET applied = ? WHERE request_id = ?",
                (applied or "", request_id),
            )
            self.conn.commit()

    def set_overridden_at(self, request_id: str, when: str | None = None) -> None:
        stamp = when or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self.conn.execute(
                "UPDATE triage_decisions SET overridden_at = ? WHERE request_id = ?",
                (stamp, request_id),
            )
            self.conn.commit()

    def save_hold(self, request_id: str, profile_id: str, video_id: str, video: dict) -> None:
        """Remember a notification that is waiting on a verdict across restarts."""
        payload = json.dumps(video, ensure_ascii=False)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO triage_holds (request_id, profile_id, video_id, video_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    profile_id = excluded.profile_id,
                    video_id = excluded.video_id,
                    video_json = excluded.video_json
                """,
                (request_id, profile_id, video_id, payload),
            )
            self.conn.commit()

    def get_hold(self, request_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM triage_holds WHERE request_id = ?", (request_id,)
            ).fetchone()
        return self._hold_dict(row) if row else None

    def list_holds(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM triage_holds ORDER BY created_at ASC, rowid ASC"
            ).fetchall()
        return [self._hold_dict(row) for row in rows]

    def delete_hold(self, request_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM triage_holds WHERE request_id = ?", (request_id,))
            self.conn.commit()

    @staticmethod
    def _hold_dict(row) -> dict:
        item = dict(row)
        try:
            item["video"] = json.loads(item.get("video_json") or "{}")
        except json.JSONDecodeError:
            item["video"] = {}
        return item

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM triage_decisions ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self.conn.close()
