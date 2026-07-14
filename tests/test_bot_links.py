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
