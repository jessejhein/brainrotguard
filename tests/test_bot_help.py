"""Tests for Telegram /help rendering."""

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


def _make_bot(tmp_path, *, admin_chat_id: str = "1", locale: str = "en") -> tuple[BrainRotGuardBot, VideoStore]:
    store = VideoStore(str(tmp_path / "videos.db"))
    store.create_profile("default", "Default")
    bot = BrainRotGuardBot(
        bot_token="token",
        admin_chat_id=admin_chat_id,
        video_store=store,
        config=Config(
            app=AppConfig(locale=locale),
            telegram=TelegramConfig(bot_token="token", admin_chat_id=admin_chat_id),
        ),
    )
    return bot, store


def test_cmd_help_uses_rendered_help_text(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/help")
        context = _DummyContext([])

        asyncio.run(bot._cmd_help(update, context))

        reply = update.message.replies[-1][0]
        assert "/addlink" in reply
        assert "/approveurl" in reply
        assert "/importplaylist" in reply
        assert "/import_playlist" in reply
        assert "Full command reference" in reply
        assert "Buy me a coffee" in reply
    finally:
        store.close()


def test_cmd_help_is_translated_in_norwegian(tmp_path):
    bot, store = _make_bot(tmp_path, locale="nb")
    try:
        update = _DummyUpdate("/help")
        context = _DummyContext([])

        asyncio.run(bot._cmd_help(update, context))

        reply = update.message.replies[-1][0]
        assert "Kommandoer" in reply
        assert "Godkjenn en YouTube" in reply
        assert "/addlink" in reply
        assert "Spander en kaffe" in reply
    finally:
        store.close()
