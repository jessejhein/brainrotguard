"""Tests for the triage service: contract validation, push, verdict handling."""

import asyncio
import json
import time

import pytest

from bot.approval import NotifyRef
from config import TriageConfig
from triage.service import (
    TriageService,
    VerdictError,
    normalise_verdict,
    rank_for,
    render_reply,
)
from triage.store import TriageStore


class FakeBot:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.sent: list[tuple] = []

    async def send_triage_reply(self, chat_id, message_id, text):
        self.sent.append((chat_id, message_id, text))
        return self.ok


def _verdict(**over):
    payload = {
        "request_id": "default:abc123",
        "verdict": "allow",
        "confidence": 0.91,
        "rank": "HIGH",
        "category": "fun",
        "summary": "A Minecraft build tutorial.",
        "reason": "Matches 14 approved build videos.",
    }
    payload.update(over)
    return payload


def _service(video_store, tmp_path, *, bot=None, poster=None, enabled=True):
    cfg = TriageConfig(
        enabled=enabled, url="http://hermes.local:8644/p/brgtriage/webhooks/brg-request",
        secret="out-secret", callback_secret="cb-secret", deadline_s=60,
    )
    store = TriageStore(str(tmp_path / "triage.db"))
    svc = TriageService(cfg, video_store, store, bot=bot or FakeBot(), poster=poster)
    return svc, store


def _video(video_store):
    return video_store.add_video("abc123", "Minecraft build tutorial", "SomeCreator",
                                 duration=412, channel_id="UC123", profile_id="default")


def test_rank_thresholds():
    assert rank_for(0.95) == "HIGH"
    assert rank_for(0.7) == "MEDIUM"
    assert rank_for(0.2) == "LOW"


def test_normalise_derives_rank_and_null_category():
    payload = _verdict()
    payload.pop("rank")
    payload["category"] = None
    out = normalise_verdict(payload)
    assert out["rank"] == "HIGH"
    assert out["category"] is None


@pytest.mark.parametrize("bad, needle", [
    ({}, "request_id"),
    ({"request_id": "default:abc", "verdict": "maybe", "summary": "x"}, "verdict"),
    ({"request_id": "default:abc", "verdict": "allow"}, "summary"),
    ({"request_id": "default:abc", "verdict": "allow", "confidence": 2, "summary": "x"}, "confidence"),
    ({"request_id": "default:abc", "verdict": "allow", "confidence": "high", "summary": "x"}, "confidence"),
    ({"request_id": "default:abc", "verdict": "allow", "summary": "x", "category": "music"}, "category"),
])
def test_normalise_rejects(bad, needle):
    with pytest.raises(VerdictError) as exc:
        normalise_verdict(bad)
    assert needle in str(exc.value)


def test_render_reply_is_explicit_about_shadow():
    text = render_reply(normalise_verdict(_verdict()))
    assert "shadow" in text.lower()
    assert "no action" in text.lower()
    assert "ALLOW" in text
    assert "HIGH" in text
    assert "A Minecraft build tutorial." in text
    assert "Matches 14 approved build videos." in text


def test_on_request_pushes_context(video_store, tmp_path):
    posted = []

    async def poster(context, body):
        posted.append((context, json.loads(body)))
        return True

    svc, _ = _service(video_store, tmp_path, poster=poster)
    video = _video(video_store)

    async def go():
        await svc.on_request(video, "default", NotifyRef(chat_id=-100, message_id=7))
        await asyncio.gather(*list(svc._tasks))

    asyncio.run(go())
    assert len(posted) == 1
    context, body = posted[0]
    assert context["request_id"] == "default:abc123"
    assert body["channel_state"] == "none"


def test_disabled_service_sends_nothing(video_store, tmp_path):
    posted = []

    async def poster(context, body):
        posted.append(context)
        return True

    svc, _ = _service(video_store, tmp_path, poster=poster, enabled=False)
    video = _video(video_store)

    async def go():
        await svc.on_request(video, "default", NotifyRef(1, 2))
        await asyncio.gather(*list(svc._tasks))

    asyncio.run(go())
    assert posted == []


def test_poster_failure_is_swallowed(video_store, tmp_path):
    async def poster(context, body):
        raise RuntimeError("connection refused")

    svc, _ = _service(video_store, tmp_path, poster=poster)
    video = _video(video_store)

    async def go():
        await svc.on_request(video, "default", NotifyRef(1, 2))
        results = await asyncio.gather(*list(svc._tasks))
        return results

    assert asyncio.run(go()) == [False]


def test_verdict_posts_threaded_reply_and_never_mutates_status(video_store, tmp_path):
    bot = FakeBot()
    svc, store = _service(video_store, tmp_path, bot=bot)
    video = _video(video_store)

    async def go():
        await svc.on_request(video, "default", NotifyRef(chat_id=-100, message_id=7))
        await asyncio.gather(*list(svc._tasks))
        return await svc.handle_verdict("default:abc123", _verdict())

    result = asyncio.run(go())
    assert result["outcome"] == "replied"
    assert len(bot.sent) == 1
    chat_id, message_id, text = bot.sent[0]
    assert (chat_id, message_id) == (-100, 7)
    assert "Triage" in text
    assert video_store.get_video("abc123")["status"] == "pending"
    row = store.get("default:abc123")
    assert row["verdict"] == "allow"
    assert row["outcome"] == "replied"
    assert row["rank"] == "HIGH"


def test_decided_request_gets_no_reply(video_store, tmp_path):
    bot = FakeBot()
    svc, store = _service(video_store, tmp_path, bot=bot)
    video = _video(video_store)
    video_store.update_status("abc123", "approved")

    async def go():
        await svc.on_request(video, "default", NotifyRef(-100, 7))
        await asyncio.gather(*list(svc._tasks))
        return await svc.handle_verdict("default:abc123", _verdict())

    assert asyncio.run(go())["outcome"] == "skipped_decided"
    assert bot.sent == []
    assert store.get("default:abc123")["outcome"] == "skipped_decided"


def test_late_verdict_is_recorded_without_reply(video_store, tmp_path):
    bot = FakeBot()
    svc, store = _service(video_store, tmp_path, bot=bot)
    video = _video(video_store)

    async def go():
        await svc.on_request(video, "default", NotifyRef(-100, 7))
        await asyncio.gather(*list(svc._tasks))
        svc._pending["default:abc123"].deadline = time.monotonic() - 1
        return await svc.handle_verdict("default:abc123", _verdict())

    assert asyncio.run(go())["outcome"] == "late"
    assert bot.sent == []


def test_unknown_request_is_recorded(video_store, tmp_path):
    bot = FakeBot()
    svc, store = _service(video_store, tmp_path, bot=bot)
    _video(video_store)

    result = asyncio.run(svc.handle_verdict("default:abc123", _verdict()))
    assert result["outcome"] == "unknown_request"
    assert bot.sent == []
    assert store.get("default:abc123") is not None


def test_duplicate_verdict_is_idempotent(video_store, tmp_path):
    svc, store = _service(video_store, tmp_path)
    _video(video_store)

    async def go():
        first = await svc.handle_verdict("default:abc123", _verdict())
        second = await svc.handle_verdict("default:abc123", _verdict(verdict="deny"))
        return first, second

    first, second = asyncio.run(go())
    assert first["status"] == "ok"
    assert second["status"] == "duplicate"
    assert store.recent()[0]["verdict"] == "allow"


def test_request_id_mismatch_is_rejected(video_store, tmp_path):
    svc, _ = _service(video_store, tmp_path)
    _video(video_store)
    with pytest.raises(VerdictError):
        asyncio.run(svc.handle_verdict("default:other", _verdict()))


def test_reply_failure_still_records_verdict(video_store, tmp_path):
    bot = FakeBot(ok=False)
    svc, store = _service(video_store, tmp_path, bot=bot)
    video = _video(video_store)

    async def go():
        await svc.on_request(video, "default", NotifyRef(-100, 7))
        await asyncio.gather(*list(svc._tasks))
        return await svc.handle_verdict("default:abc123", _verdict())

    assert asyncio.run(go())["outcome"] == "logged"
    assert store.get("default:abc123")["verdict"] == "allow"
