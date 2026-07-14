"""Tests for Telegram admin authorization behavior."""

from bot.telegram_bot import BrainRotGuardBot
from config import AppConfig, Config, TelegramConfig
from data.video_store import VideoStore


class _DummyMessage:
    def __init__(self):
        self.replies: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs):
        self.replies.append((text, kwargs))


class _DummyCallbackQuery:
    def __init__(self):
        self.answers: list[str] = []

    async def answer(self, text: str = ""):
        self.answers.append(text)


class _DummyUpdate:
    def __init__(self, *, chat_id: int | None, user_id: int | None, callback: bool = False):
        self.effective_chat = None if chat_id is None else type("Chat", (), {"id": chat_id})()
        self.effective_user = None if user_id is None else type("User", (), {"id": user_id})()
        self.effective_message = _DummyMessage()
        self.message = None if callback else self.effective_message
        self.callback_query = _DummyCallbackQuery() if callback else None


def _make_bot(tmp_path, *, admin_chat_id: str = "-100123456", admin_user_ids: str = "") -> tuple[BrainRotGuardBot, VideoStore]:
    store = VideoStore(str(tmp_path / "videos.db"))
    bot = BrainRotGuardBot(
        bot_token="token",
        admin_chat_id=admin_chat_id,
        video_store=store,
        config=Config(
            app=AppConfig(locale="en"),
            telegram=TelegramConfig(
                bot_token="token",
                admin_chat_id=admin_chat_id,
                admin_user_ids=admin_user_ids,
            ),
        ),
    )
    return bot, store


def test_check_admin_allows_configured_group_chat(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate(chat_id=-100123456, user_id=111)
        assert bot._check_admin(update) is True
    finally:
        store.close()


def test_check_admin_allows_listed_direct_message_user(tmp_path):
    bot, store = _make_bot(tmp_path, admin_user_ids="123456,987654")
    try:
        update = _DummyUpdate(chat_id=123456, user_id=123456)
        assert bot._check_admin(update) is True
    finally:
        store.close()


def test_check_admin_rejects_unlisted_direct_message_user_when_admin_chat_is_group(tmp_path):
    bot, store = _make_bot(tmp_path, admin_user_ids="123456,987654")
    try:
        update = _DummyUpdate(chat_id=555555, user_id=555555)
        assert bot._check_admin(update) is False
    finally:
        store.close()


def test_check_admin_rejects_listed_user_in_unrelated_group(tmp_path):
    bot, store = _make_bot(tmp_path, admin_user_ids="123456,987654")
    try:
        update = _DummyUpdate(chat_id=-100999888, user_id=123456)
        assert bot._check_admin(update) is False
    finally:
        store.close()

