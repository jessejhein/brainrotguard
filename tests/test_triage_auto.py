"""Auto-apply of a confident triage verdict, and the parent override."""

import asyncio

from bot.approval import ApprovalMixin
from config import TriageConfig
from data.child_store import ChildStore
from triage.service import TriageService
from triage.store import TriageStore


class _Bot:
    def __init__(self):
        self.events = []

    async def notify_new_request(self, video, profile_id="default", receipt=None):
        self.events.append(("notify", receipt))
        return type("Ref", (), {"chat_id": -100, "message_id": 4})()

    async def send_triage_reply(self, chat_id, message_id, text):
        self.events.append(("reply", text))
        return True


class _Query:
    def __init__(self):
        self.edits = []

    async def answer(self, *args, **kwargs):
        return None

    async def edit_message_caption(self, **kwargs):
        raise RuntimeError("no caption")

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


class _Host(ApprovalMixin):
    def __init__(self, video_store, triage_store):
        self.video_store = video_store
        self.triage_store = triage_store
        self.on_video_change = None
        self.on_channel_change = None

    def tr(self, key, **kwargs):
        return key.format(**kwargs) if kwargs else key

    def _child_store(self, profile_id):
        return ChildStore(self.video_store, profile_id)

    def cat_label(self, category, short=False):
        return category

    def _get_profiles(self):
        return self.video_store.get_profiles()


def _service(video_store, tmp_path, *, mode="auto", bot=None):
    async def poster(context, body):
        return True

    cfg = TriageConfig(
        enabled=True, mode=mode, url="http://hermes/x", secret="out", callback_secret="cb",
        hold_notification=True, hold_timeout_s=240,
    )
    store = TriageStore(str(tmp_path / "auto.db"))
    svc = TriageService(cfg, video_store, store, bot=bot or _Bot(), poster=poster)
    return svc, store


def _payload(**over):
    body = {
        "request_id": "default:abc123",
        "verdict": "allow",
        "confidence": 0.91,
        "category": "edu",
        "summary": "A calm science demonstration.",
        "reason": "secret parent reason",
    }
    body.update(over)
    return body


def _run_verdict(svc, video_store, payload):
    video = video_store.add_video("abc123", "Science demo", "Lab", profile_id="default")

    async def go():
        await svc.on_request(video, "default", None)
        await asyncio.gather(*list(svc._tasks))
        return await svc.handle_verdict("default:abc123", payload)

    return asyncio.run(go())


def _callbacks(video, receipt):
    host = _Host(None, None)
    host._get_profiles = lambda: [{"id": "default"}]
    host.video_store = type("S", (), {"find_video_approved_for_others": lambda *a, **k: None})()
    buttons = host._request_buttons("default", video["video_id"], video, receipt)
    data = []
    for row in buttons:
        for button in row:
            if getattr(button, "callback_data", None):
                data.append(button.callback_data)
    return data


def test_high_allow_applies_and_receipt_can_revoke(video_store, tmp_path):
    bot = _Bot()
    svc, store = _service(video_store, tmp_path, bot=bot)
    result = _run_verdict(svc, video_store, _payload())
    assert result["outcome"] == "hold_released"
    video = video_store.get_video("abc123")
    assert video["status"] == "approved"
    assert video["category"] == "edu"
    receipt = bot.events[0][1]
    assert receipt["applied"] == "auto_approved"
    assert "revoke:default:abc123" in _callbacks(video, receipt)
    assert store.get("default:abc123")["applied"] == "auto_approved"


def test_high_deny_applies_and_receipt_can_undeny(video_store, tmp_path):
    bot = _Bot()
    svc, store = _service(video_store, tmp_path, bot=bot)
    _run_verdict(svc, video_store, _payload(verdict="deny", category=None))
    video = video_store.get_video("abc123")
    assert video["status"] == "denied"
    receipt = bot.events[0][1]
    assert receipt["applied"] == "auto_denied"
    data = _callbacks(video, receipt)
    assert "undeny:default:abc123:edu" in data
    assert "undeny:default:abc123:fun" in data
    assert store.get("default:abc123")["applied"] == "auto_denied"


def test_medium_and_uncertain_do_nothing(video_store, tmp_path):
    bot = _Bot()
    svc, _ = _service(video_store, tmp_path, bot=bot)
    _run_verdict(svc, video_store, _payload(confidence=0.70, category=None))
    assert video_store.get_video("abc123")["status"] == "pending"
    assert bot.events[0][1] is None


def test_uncertain_does_nothing(video_store, tmp_path):
    bot = _Bot()
    svc, store = _service(video_store, tmp_path, bot=bot)
    _run_verdict(svc, video_store, _payload(verdict="uncertain", confidence=0.95))
    assert video_store.get_video("abc123")["status"] == "pending"
    assert store.get("default:abc123")["applied"] == ""
    assert bot.events[0][1] is None


def test_shadow_mode_writes_nothing(video_store, tmp_path):
    bot = _Bot()
    svc, store = _service(video_store, tmp_path, mode="shadow", bot=bot)
    _run_verdict(svc, video_store, _payload())
    assert video_store.get_video("abc123")["status"] == "pending"
    assert store.get("default:abc123")["applied"] == ""
    assert bot.events[0][1] is None


def test_undeny_override_approves_and_stamps(video_store, tmp_path):
    triage = TriageStore(str(tmp_path / "triage.db"))
    video_store.add_video("abc12345678", "Science demo", "Lab", profile_id="default")
    video_store.update_status("abc12345678", "denied")
    triage.record(
        request_id="default:abc12345678", profile_id="default", video_id="abc12345678",
        verdict="deny", summary="A calm science demonstration.",
        applied="auto_denied", outcome="hold_released", mode="auto", rank="HIGH",
        confidence=0.95,
    )
    host = _Host(video_store, triage)
    query = _Query()

    async def go():
        await host._cb_video_action(query, "undeny", "default", "abc12345678", category="edu")
        await asyncio.sleep(0)

    asyncio.run(go())
    video = video_store.get_video("abc12345678")
    assert video["status"] == "approved"
    assert video["category"] == "edu"
    assert triage.get("default:abc12345678")["overridden_at"]
