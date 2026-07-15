"""Tests for Telegram playlist management commands."""

import asyncio

from bot.telegram_bot import BrainRotGuardBot
from config import AppConfig, Config, TelegramConfig, WebConfig
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


def _make_bot(tmp_path, *, admin_chat_id: str = "1", base_url: str = "") -> tuple[BrainRotGuardBot, VideoStore]:
    store = VideoStore(str(tmp_path / "videos.db"))
    store.create_profile("default", "Default")
    bot = BrainRotGuardBot(
        bot_token="token",
        admin_chat_id=admin_chat_id,
        video_store=store,
        config=Config(
            app=AppConfig(locale="en"),
            web=WebConfig(base_url=base_url),
            telegram=TelegramConfig(bot_token="token", admin_chat_id=admin_chat_id),
        ),
    )
    return bot, store


def test_playlist_create_makes_native_playlist(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/playlist create Robots")
        context = _DummyContext(["create", "Robots"])

        asyncio.run(bot._cmd_playlist(update, context))

        playlists = store.get_playlists(profile_id="default")
        assert [p["name"] for p in playlists] == ["Robots"]
    finally:
        store.close()


def test_playlist_create_reply_includes_child_url(tmp_path):
    bot, store = _make_bot(tmp_path, base_url="http://brg.local:8080")
    try:
        update = _DummyUpdate("/playlist create Robots")
        context = _DummyContext(["create", "Robots"])

        asyncio.run(bot._cmd_playlist(update, context))

        playlist = store.get_playlists(profile_id="default")[0]
        assert f"http://brg.local:8080/playlists/{playlist['id']}" in update.message.replies[-1][0]
    finally:
        store.close()


def test_playlist_list_shows_existing_playlists(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        store.create_playlist("Robots", profile_id="default")
        update = _DummyUpdate("/playlist")
        context = _DummyContext([])

        asyncio.run(bot._cmd_playlist(update, context))

        assert update.message.replies
        assert "Robots" in update.message.replies[0][0]
    finally:
        store.close()


def test_playlist_list_reply_includes_child_urls(tmp_path):
    bot, store = _make_bot(tmp_path, base_url="http://brg.local:8080")
    try:
        playlist = store.create_playlist("Robots", profile_id="default")
        update = _DummyUpdate("/playlist")
        context = _DummyContext([])

        asyncio.run(bot._cmd_playlist(update, context))

        assert f"playlists/{playlist['id']}" in update.message.replies[0][0]
    finally:
        store.close()


def test_playlist_add_approves_and_appends_video(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        playlist = store.create_playlist("Robots", profile_id="default")
        update = _DummyUpdate(f"/playlist add {playlist['id']} https://youtu.be/dQw4w9WgXcQ edu")
        context = _DummyContext(["add", str(playlist["id"]), "https://youtu.be/dQw4w9WgXcQ", "edu"])

        async def _fake_extract(video_id: str):
            return {
                "video_id": video_id,
                "title": "Robot Intro",
                "channel_name": "Robot Channel",
                "channel_id": "UC123",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                "duration": 120,
                "view_count": 99,
                "is_short": False,
            }

        bot._extract_video_metadata = _fake_extract
        asyncio.run(bot._cmd_playlist(update, context))

        items = store.get_playlist_items(playlist["id"], profile_id="default")
        video = store.get_video("dQw4w9WgXcQ", profile_id="default")
        assert [item["video_id"] for item in items] == ["dQw4w9WgXcQ"]
        assert video["status"] == "approved"
        assert video["category"] == "edu"
    finally:
        store.close()


def test_playlist_add_reply_includes_child_urls(tmp_path):
    bot, store = _make_bot(tmp_path, base_url="http://brg.local:8080")
    try:
        playlist = store.create_playlist("Robots", profile_id="default")
        update = _DummyUpdate(f"/playlist add {playlist['id']} https://youtu.be/dQw4w9WgXcQ edu")
        context = _DummyContext(["add", str(playlist["id"]), "https://youtu.be/dQw4w9WgXcQ", "edu"])

        async def _fake_extract(video_id: str):
            return {
                "video_id": video_id,
                "title": "Robot Intro",
                "channel_name": "Robot Channel",
                "channel_id": "UC123",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                "duration": 120,
                "view_count": 99,
                "is_short": False,
            }

        bot._extract_video_metadata = _fake_extract
        asyncio.run(bot._cmd_playlist(update, context))

        reply = update.message.replies[-1][0]
        assert f"http://brg.local:8080/playlists/{playlist['id']}" in reply
        assert "http://brg.local:8080/watch/dQw4w9WgXcQ" in reply
    finally:
        store.close()


def test_playlist_add_rejects_multiple_video_urls_when_args_are_split(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        playlist = store.create_playlist("Robots", profile_id="default")
        update = _DummyUpdate(
            f"/playlist add {playlist['id']} https://youtu.be/dQw4w9WgXcQ https://youtu.be/jjpjjcMeujM"
        )
        context = _DummyContext([
            "add",
            str(playlist["id"]),
            "https://youtu.be/dQw4w9WgXcQ",
            "https://youtu.be/jjpjjcMeujM",
        ])

        async def _fake_extract(video_id: str):
            raise AssertionError("multiple URLs should be rejected before metadata fetch")

        bot._extract_video_metadata = _fake_extract
        asyncio.run(bot._cmd_playlist(update, context))

        assert update.message.replies
        assert "one YouTube video" in update.message.replies[0][0]
        assert store.get_playlist_items(playlist["id"], profile_id="default") == []
        assert store.get_video("dQw4w9WgXcQ", profile_id="default") is None
        assert store.get_video("jjpjjcMeujM", profile_id="default") is None
    finally:
        store.close()


def test_playlist_add_rejects_multiple_video_urls_with_trailing_category(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        playlist = store.create_playlist("Robots", profile_id="default")
        update = _DummyUpdate(
            f"/playlist add {playlist['id']} https://youtu.be/dQw4w9WgXcQ https://youtu.be/jjpjjcMeujM fun"
        )
        context = _DummyContext([
            "add",
            str(playlist["id"]),
            "https://youtu.be/dQw4w9WgXcQ",
            "https://youtu.be/jjpjjcMeujM",
            "fun",
        ])

        async def _fake_extract(video_id: str):
            raise AssertionError("multiple URLs should be rejected before metadata fetch")

        bot._extract_video_metadata = _fake_extract
        asyncio.run(bot._cmd_playlist(update, context))

        assert update.message.replies
        assert "one YouTube video" in update.message.replies[0][0]
        assert store.get_playlist_items(playlist["id"], profile_id="default") == []
        assert store.get_video("dQw4w9WgXcQ", profile_id="default") is None
        assert store.get_video("jjpjjcMeujM", profile_id="default") is None
    finally:
        store.close()


def test_playlist_delete_removes_playlist(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        playlist = store.create_playlist("Robots", profile_id="default")
        update = _DummyUpdate(f"/playlist delete {playlist['id']}")
        context = _DummyContext(["delete", str(playlist["id"])])

        asyncio.run(bot._cmd_playlist(update, context))

        assert store.get_playlists(profile_id="default") == []
    finally:
        store.close()


def test_importplaylist_defaults_to_edu(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/importplaylist https://www.youtube.com/playlist?list=PL1234567890ABCDE")
        context = _DummyContext(["https://www.youtube.com/playlist?list=PL1234567890ABCDE"])

        async def _fake_playlist_extract(url: str, max_items: int = 200):
            return {
                "playlist_id": "PL1234567890ABCDE",
                "title": "Robots Course",
                "source_url": url,
                "entries": [
                    {
                        "video_id": "dQw4w9WgXcQ",
                        "title": "Intro",
                        "channel_name": "Robot Channel",
                        "channel_id": "UC123",
                        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                        "duration": 120,
                        "view_count": 99,
                        "is_short": False,
                    }
                ],
            }

        bot._extract_playlist_metadata = _fake_playlist_extract
        asyncio.run(bot._cmd_importplaylist(update, context))

        playlists = store.get_playlists(profile_id="default")
        items = store.get_playlist_items(playlists[0]["id"], profile_id="default")
        video = store.get_video("dQw4w9WgXcQ", profile_id="default")
        assert playlists[0]["name"] == "Robots Course"
        assert playlists[0]["category"] == "edu"
        assert [item["video_id"] for item in items] == ["dQw4w9WgXcQ"]
        assert video["category"] == "edu"
    finally:
        store.close()


def test_importplaylist_notifies_video_change_once(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/importplaylist https://www.youtube.com/playlist?list=PL1234567890ABCDE")
        context = _DummyContext(["https://www.youtube.com/playlist?list=PL1234567890ABCDE"])
        calls = []
        bot.on_video_change = lambda: calls.append("changed")

        async def _fake_playlist_extract(url: str, max_items: int = 200):
            return {
                "playlist_id": "PL1234567890ABCDE",
                "title": "Robots Course",
                "source_url": url,
                "entries": [
                    {
                        "video_id": "dQw4w9WgXcQ",
                        "title": "Intro",
                        "channel_name": "Robot Channel",
                        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                    },
                    {
                        "video_id": "jjpjjcMeujM",
                        "title": "Dance",
                        "channel_name": "Robot Channel",
                        "thumbnail_url": "https://i.ytimg.com/vi/jjpjjcMeujM/hqdefault.jpg",
                    },
                ],
            }

        bot._extract_playlist_metadata = _fake_playlist_extract
        asyncio.run(bot._cmd_importplaylist(update, context))

        assert calls == ["changed"]
    finally:
        store.close()


def test_importplaylist_reply_includes_child_url(tmp_path):
    bot, store = _make_bot(tmp_path, base_url="http://brg.local:8080")
    try:
        update = _DummyUpdate("/importplaylist https://www.youtube.com/playlist?list=PL1234567890ABCDE")
        context = _DummyContext(["https://www.youtube.com/playlist?list=PL1234567890ABCDE"])

        async def _fake_playlist_extract(url: str, max_items: int = 200):
            return {
                "playlist_id": "PL1234567890ABCDE",
                "title": "Robots Course",
                "source_url": url,
                "entries": [
                    {
                        "video_id": "dQw4w9WgXcQ",
                        "title": "Intro",
                        "channel_name": "Robot Channel",
                        "channel_id": "UC123",
                        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                        "duration": 120,
                        "view_count": 99,
                        "is_short": False,
                    }
                ],
            }

        bot._extract_playlist_metadata = _fake_playlist_extract
        asyncio.run(bot._cmd_importplaylist(update, context))

        playlist = store.get_playlists(profile_id="default")[0]
        assert f"http://brg.local:8080/playlists/{playlist['id']}" in update.message.replies[-1][0]
    finally:
        store.close()


def test_importplaylist_allows_fun_override(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/importplaylist https://www.youtube.com/playlist?list=PL1234567890ABCDE fun")
        context = _DummyContext(["https://www.youtube.com/playlist?list=PL1234567890ABCDE", "fun"])

        async def _fake_playlist_extract(url: str, max_items: int = 200):
            return {
                "playlist_id": "PL1234567890ABCDE",
                "title": "Fun Robots",
                "source_url": url,
                "entries": [
                    {
                        "video_id": "jjpjjcMeujM",
                        "title": "Dance",
                        "channel_name": "Robot Channel",
                        "channel_id": "UC123",
                        "thumbnail_url": "https://i.ytimg.com/vi/jjpjjcMeujM/hqdefault.jpg",
                        "duration": 60,
                        "view_count": 50,
                        "is_short": False,
                    }
                ],
            }

        bot._extract_playlist_metadata = _fake_playlist_extract
        asyncio.run(bot._cmd_importplaylist(update, context))

        playlists = store.get_playlists(profile_id="default")
        video = store.get_video("jjpjjcMeujM", profile_id="default")
        assert playlists[0]["category"] == "fun"
        assert video["category"] == "fun"
    finally:
        store.close()


def test_importplaylist_reply_reports_skipped_entries(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/importplaylist https://www.youtube.com/playlist?list=PL1234567890ABCDE")
        context = _DummyContext(["https://www.youtube.com/playlist?list=PL1234567890ABCDE"])

        async def _fake_playlist_extract(url: str, max_items: int = 200):
            return {
                "playlist_id": "PL1234567890ABCDE",
                "title": "Robots Course",
                "source_url": url,
                "skipped_count": 2,
                "entries": [
                    {
                        "video_id": "dQw4w9WgXcQ",
                        "title": "Intro",
                        "channel_name": "Robot Channel",
                        "channel_id": "UC123",
                        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                        "duration": 120,
                        "view_count": 99,
                        "is_short": False,
                    }
                ],
            }

        bot._extract_playlist_metadata = _fake_playlist_extract
        asyncio.run(bot._cmd_importplaylist(update, context))

        assert update.message.replies
        assert "Skipped: 2" in update.message.replies[-1][0]
    finally:
        store.close()


def test_importplaylist_handles_unknown_playlist_title(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/importplaylist https://www.youtube.com/playlist?list=PL1234567890ABCDE")
        context = _DummyContext(["https://www.youtube.com/playlist?list=PL1234567890ABCDE"])

        async def _fake_playlist_extract(url: str, max_items: int = 200):
            return {
                "playlist_id": "PL1234567890ABCDE",
                "title": "Unknown Playlist",
                "source_url": url,
                "entries": [
                    {
                        "video_id": "dQw4w9WgXcQ",
                        "title": "Intro",
                        "channel_name": "Robot Channel",
                    }
                ],
                "skipped_count": 0,
            }

        bot._extract_playlist_metadata = _fake_playlist_extract
        asyncio.run(bot._cmd_importplaylist(update, context))

        playlists = store.get_playlists(profile_id="default")
        assert playlists[0]["name"] == "Unknown Playlist"
        assert store.get_video("dQw4w9WgXcQ", profile_id="default") is not None
    finally:
        store.close()


def test_importplaylist_handles_normalized_unknown_display_fields(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/importplaylist https://www.youtube.com/playlist?list=PL1234567890ABCDE")
        context = _DummyContext(["https://www.youtube.com/playlist?list=PL1234567890ABCDE"])

        async def _fake_playlist_extract(url: str, max_items: int = 200):
            return {
                "playlist_id": "PL1234567890ABCDE",
                "title": "Robots Course",
                "source_url": url,
                "entries": [
                    {
                        "video_id": "dQw4w9WgXcQ",
                        "title": "Unknown",
                        "channel_name": "Unknown",
                    }
                ],
                "skipped_count": 0,
            }

        bot._extract_playlist_metadata = _fake_playlist_extract
        asyncio.run(bot._cmd_importplaylist(update, context))

        video = store.get_video("dQw4w9WgXcQ", profile_id="default")
        assert video is not None
        assert video["title"] == "Unknown"
        assert video["channel_name"] == "Unknown"
    finally:
        store.close()
