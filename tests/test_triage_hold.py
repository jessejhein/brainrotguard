"""Store coverage for held notifications. Service behaviour is added with the hold path."""

from triage.store import TriageStore


def test_holds_round_trip_and_for_video_is_latest(tmp_path):
    store = TriageStore(str(tmp_path / "triage.db"))
    video = {"video_id": "abc123", "title": "A title", "channel_name": "Chan"}
    store.save_hold("default:abc123", "default", "abc123", video)
    again = dict(video, title="replaced")
    store.save_hold("default:abc123", "default", "abc123", again)

    hold = store.get_hold("default:abc123")
    assert hold["video"]["title"] == "replaced"
    assert len(store.list_holds()) == 1

    store.record(
        request_id="default:abc123", profile_id="default", video_id="abc123",
        verdict="allow", summary="first", outcome="logged", applied="",
    )
    # request_id is the primary key, so a second insert is ignored. for_video
    # still returns that row, including the new columns.
    assert store.record(
        request_id="default:abc123", profile_id="default", video_id="abc123",
        verdict="deny", summary="second",
    ) is False
    row = store.for_video("default", "abc123")
    assert row["summary"] == "first"
    assert row["applied"] == ""
    assert row["overridden_at"] is None

    store.set_applied("default:abc123", "auto_approved")
    store.set_overridden_at("default:abc123", "2026-11-11 12:00:00")
    row = store.for_video("default", "abc123")
    assert row["applied"] == "auto_approved"
    assert row["overridden_at"] == "2026-11-11 12:00:00"

    store.delete_hold("default:abc123")
    assert store.list_holds() == []
    assert store.for_video("other", "abc123") is None
    store.close()


def test_existing_decision_table_gains_new_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE triage_decisions (
            request_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            verdict TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            rank TEXT NOT NULL DEFAULT '',
            category TEXT,
            summary TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT 'shadow',
            outcome TEXT NOT NULL DEFAULT 'logged',
            latency_ms INTEGER,
            raw TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "INSERT INTO triage_decisions (request_id, profile_id, video_id, verdict, summary) "
        "VALUES ('default:abc', 'default', 'abc', 'allow', 'old')"
    )
    conn.commit()
    conn.close()

    store = TriageStore(str(path))
    row = store.for_video("default", "abc")
    assert row["summary"] == "old"
    assert row["applied"] == ""
    store.set_applied("default:abc", "auto_denied")
    assert store.get("default:abc")["applied"] == "auto_denied"
    store.close()
