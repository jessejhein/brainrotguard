"""Tests for Telegram link handling and text routing."""

import asyncio

from bot.telegram_bot import BrainRotGuardBot
from config import AppConfig, Config, TelegramConfig
from data.video_store import VideoStore


class _DummyMessage:
    def __init__(self, text: str, chat_id: int = 1):
        self.text = text
        self.chat_id = chat_id
        self.replies: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs):
        self.replies.append((text, kwargs))


class _DummyUpdate:
    def __init__(self, text: str, chat_id: int = 1, user_id: int = 1):
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("User", (), {"id": user_id})()
        self.message = _DummyMessage(text, chat_id=chat_id)
        self.effective_message = self.message
        self.callback_query = None


class _DummyContext:
    def __init__(self, args=None):
        self.args = args or []


def _make_bot(tmp_path, *, admin_chat_id: str = "1") -> tuple[BrainRotGuardBot, VideoStore]:
    store = VideoStore(str(tmp_path / "videos.db"))
    store.create_profile("default", "Default")
    bot = BrainRotGuardBot(
        bot_token="token",
        admin_chat_id=admin_chat_id,
        video_store=store,
        config=Config(
            app=AppConfig(locale="en"),
            telegram=TelegramConfig(bot_token="token", admin_chat_id=admin_chat_id),
        ),
    )
    return bot, store


def test_handle_text_message_ignores_non_links_without_wizard(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("hello world")
        handled = asyncio.run(bot._handle_text_message(update, _DummyContext()))
        assert handled is False
    finally:
        store.close()


def test_handle_text_message_routes_video_links_without_wizard(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("https://youtu.be/dQw4w9WgXcQ")
        called: list[str] = []

        async def _fake_handle_plain_text_link(update, context):
            called.append(update.message.text)
            return True

        bot._handle_plain_text_link = _fake_handle_plain_text_link
        handled = asyncio.run(bot._handle_text_message(update, _DummyContext()))

        assert handled is True
        assert called == ["https://youtu.be/dQw4w9WgXcQ"]
    finally:
        store.close()


def test_handle_text_message_preserves_wizard_priority(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("https://youtu.be/dQw4w9WgXcQ")
        bot._pending_wizard[1] = {"step": "onboard_hub", "hub_message_id": 99}
        called: list[str] = []

        async def _fake_handle_plain_text_link(update, context):
            called.append(update.message.text)
            return True

        bot._handle_plain_text_link = _fake_handle_plain_text_link
        handled = asyncio.run(bot._handle_text_message(update, _DummyContext()))

        assert handled is True
        assert called == []
    finally:
        store.close()


def test_addlink_approves_video_with_category(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/addlink https://youtu.be/dQw4w9WgXcQ edu")
        context = _DummyContext(["https://youtu.be/dQw4w9WgXcQ", "edu"])

        async def _fake_extract(video_id: str):
            assert video_id == "dQw4w9WgXcQ"
            return {
                "video_id": video_id,
                "title": "Test Video",
                "channel_name": "Test Channel",
                "channel_id": "UC123",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                "duration": 120,
                "view_count": 99,
                "is_short": False,
            }

        bot._extract_video_metadata = _fake_extract
        asyncio.run(bot._cmd_addlink(update, context))

        video = store.get_video("dQw4w9WgXcQ", profile_id="default")
        assert video is not None
        assert video["status"] == "approved"
        assert video["category"] == "edu"
    finally:
        store.close()


def test_addlink_rejects_invalid_url(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/addlink not-a-link")
        context = _DummyContext(["not-a-link"])

        asyncio.run(bot._cmd_addlink(update, context))

        assert update.message.replies
        assert "YouTube" in update.message.replies[0][0]
    finally:
        store.close()


def test_addlink_requires_admin(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/addlink https://youtu.be/dQw4w9WgXcQ", chat_id=2, user_id=2)
        context = _DummyContext(["https://youtu.be/dQw4w9WgXcQ"])

        asyncio.run(bot._cmd_addlink(update, context))

        assert update.message.replies
        assert "parent/admin" in update.message.replies[0][0]
        assert store.get_video("dQw4w9WgXcQ", profile_id="default") is None
    finally:
        store.close()


def test_addlink_prompts_for_child_when_multiple_profiles(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        store.create_profile("kid2", "Kid 2")
        update = _DummyUpdate("/addlink https://youtu.be/dQw4w9WgXcQ")
        context = _DummyContext(["https://youtu.be/dQw4w9WgXcQ"])

        asyncio.run(bot._cmd_addlink(update, context))

        assert update.message.replies
        text, kwargs = update.message.replies[0]
        assert "Which child?" in text
        assert kwargs.get("reply_markup") is not None
    finally:
        store.close()


def test_plain_text_link_approves_video_as_fun(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("https://youtu.be/dQw4w9WgXcQ")

        async def _fake_extract(video_id: str):
            assert video_id == "dQw4w9WgXcQ"
            return {
                "video_id": video_id,
                "title": "Test Video",
                "channel_name": "Test Channel",
                "channel_id": "UC123",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                "duration": 120,
                "view_count": 99,
                "is_short": False,
            }

        bot._extract_video_metadata = _fake_extract
        handled = asyncio.run(bot._handle_plain_text_link(update, _DummyContext()))

        assert handled is True
        video = store.get_video("dQw4w9WgXcQ", profile_id="default")
        assert video is not None
        assert video["status"] == "approved"
        assert video["category"] == "fun"
    finally:
        store.close()


def test_plain_text_link_requires_admin(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("https://youtu.be/dQw4w9WgXcQ", chat_id=2, user_id=2)
        handled = asyncio.run(bot._handle_plain_text_link(update, _DummyContext()))

        assert handled is False
        assert update.message.replies
        assert "parent/admin" in update.message.replies[0][0]
        assert store.get_video("dQw4w9WgXcQ", profile_id="default") is None
    finally:
        store.close()
