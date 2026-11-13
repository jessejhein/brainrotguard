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


import asyncio

from bot.approval import NotifyRef
from config import TriageConfig
from triage.service import TriageService


class _HoldBot:
    def __init__(self):
        self.events = []

    async def notify_new_request(self, video, profile_id="default", receipt=None):
        self.events.append(("notify", video["video_id"], receipt))
        return NotifyRef(chat_id=-100, message_id=11)

    async def send_triage_reply(self, chat_id, message_id, text):
        self.events.append(("reply", chat_id, message_id, text))
        return True


def _hold_service(video_store, tmp_path, *, poster, bot=None, hold_timeout_s=240):
    cfg = TriageConfig(
        enabled=True, mode="shadow", url="http://hermes/x", secret="out", callback_secret="cb",
        hold_notification=True, hold_timeout_s=hold_timeout_s, deadline_s=60,
    )
    store = TriageStore(str(tmp_path / "hold.db"))
    svc = TriageService(cfg, video_store, store, bot=bot or _HoldBot(), poster=poster)
    return svc, store


def _verdict():
    return {
        "request_id": "default:abc123",
        "verdict": "allow",
        "confidence": 0.91,
        "category": "fun",
        "summary": "A Minecraft build tutorial.",
        "reason": "Matches approved builds.",
    }


def test_verdict_releases_hold_once_in_order(video_store, tmp_path):
    posted = []

    async def poster(context, body):
        posted.append(context["request_id"])
        return True

    bot = _HoldBot()
    svc, store = _hold_service(video_store, tmp_path, poster=poster, bot=bot)
    video = video_store.add_video("abc123", "Minecraft build tutorial", "SomeCreator", profile_id="default")

    async def go():
        await svc.on_request(video, "default", None)
        await asyncio.gather(*list(svc._tasks))
        assert bot.events == []
        return await svc.handle_verdict("default:abc123", _verdict())

    result = asyncio.run(go())
    assert result["outcome"] == "hold_released"
    assert posted == ["default:abc123"]
    kinds = [event[0] for event in bot.events]
    assert kinds == ["notify", "reply"]
    assert bot.events[1][1] == -100
    assert bot.events[1][2] == 11
    assert "A Minecraft build tutorial." in bot.events[1][3]
    assert store.get("default:abc123")["outcome"] == "hold_released"
    assert store.list_holds() == []


def test_timeout_releases_without_a_verdict(video_store, tmp_path, monkeypatch):
    monkeypatch.setattr("triage.service.TIMEOUT_GRACE_S", 0.0)

    async def poster(context, body):
        return True

    bot = _HoldBot()
    svc, store = _hold_service(video_store, tmp_path, poster=poster, bot=bot, hold_timeout_s=1)
    video = video_store.add_video("abc123", "Title", "Chan", profile_id="default")

    async def go():
        await svc.on_request(video, "default", None)
        await asyncio.gather(*list(svc._tasks))
        await asyncio.gather(*list(svc._timers))

    asyncio.run(go())
    assert [event[0] for event in bot.events] == ["notify"]
    row = store.get("default:abc123")
    assert row["outcome"] == "hold_timeout"
    assert row["verdict"] == "none"
    assert store.list_holds() == []


def test_push_failure_releases_immediately(video_store, tmp_path):
    async def poster(context, body):
        raise RuntimeError("connection refused")

    bot = _HoldBot()
    svc, store = _hold_service(video_store, tmp_path, poster=poster, bot=bot, hold_timeout_s=240)
    video = video_store.add_video("abc123", "Title", "Chan", profile_id="default")

    async def go():
        await svc.on_request(video, "default", None)
        await asyncio.gather(*list(svc._tasks))

    asyncio.run(go())
    assert [event[0] for event in bot.events] == ["notify"]
    assert store.get("default:abc123")["outcome"] == "push_failed"
    assert store.list_holds() == []
    assert not svc._timers


def test_restart_flush_does_not_duplicate(video_store, tmp_path):
    async def poster(context, body):
        return True

    bot = _HoldBot()
    svc, store = _hold_service(video_store, tmp_path, poster=poster, bot=bot)
    video = video_store.add_video("abc123", "Title", "Chan", profile_id="default")

    async def arm():
        await svc.on_request(video, "default", None)
        await asyncio.gather(*list(svc._tasks))
        for timer in list(svc._timers):
            timer.cancel()
        await asyncio.gather(*list(svc._timers), return_exceptions=True)

    asyncio.run(arm())
    assert store.get_hold("default:abc123") is not None
    store.conn.execute(
        "UPDATE triage_holds SET created_at = ? WHERE request_id = ?",
        ("2000-01-01 00:00:00", "default:abc123"),
    )
    store.conn.commit()

    bot2 = _HoldBot()
    restarted = TriageService(svc.config, video_store, store, bot=bot2, poster=poster)

    async def flush_twice():
        await restarted.restore_holds()
        await restarted.restore_holds()

    asyncio.run(flush_twice())
    assert [event[0] for event in bot2.events] == ["notify"]
    assert store.list_holds() == []
    assert store.get("default:abc123")["outcome"] == "hold_timeout"
