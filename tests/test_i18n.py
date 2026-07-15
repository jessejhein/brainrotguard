"""Tests for locale and time formatting helpers."""

from i18n import app_name, format_time, format_time_compact, normalize_time_format, t


class TestAppName:
    def test_defaults_to_brainrotguard_in_english(self):
        assert app_name("en") == "BrainRotGuard"

    def test_uses_hjernevakt_in_norwegian(self):
        assert app_name("nb") == "HjerneVakt"


class TestNormalizeTimeFormat:
    def test_defaults_to_locale(self):
        assert normalize_time_format(None) == "locale"
        assert normalize_time_format("garbage") == "locale"

    def test_normalizes_aliases(self):
        assert normalize_time_format("24hour") == "24h"
        assert normalize_time_format("12hr") == "12h"


class TestFormatTime:
    def test_en_locale_defaults_to_12h(self):
        assert format_time("20:00", "en") == "8 PM"

    def test_nb_locale_defaults_to_24h(self):
        assert format_time("20:00", "nb") == "20:00"

    def test_forced_24h_overrides_locale(self):
        assert format_time("20:00", "en", time_format="24h") == "20:00"

    def test_forced_12h_overrides_locale(self):
        assert format_time("20:00", "nb", time_format="12h") == "8 PM"


class TestFormatTimeCompact:
    def test_compact_12h(self):
        assert format_time_compact("20:00", "en") == "8p"

    def test_compact_24h(self):
        assert format_time_compact("20:00", "en", time_format="24h") == "20"


class TestPlaylistTranslations:
    def test_nb_playlist_strings_are_translated(self):
        assert t("nb", "Playlists") != "Playlists"
        assert t("nb", "No playlists yet") != "No playlists yet"
        assert (
            t("nb", "Usage: /addlink <YouTube URL or ID> [edu|fun]")
            != "Usage: /addlink <YouTube URL or ID> [edu|fun]"
        )
        assert t("nb", "Skipped: {count}", count=2) != "Skipped: 2"

    def test_nb_help_mentions_link_and_playlist_commands(self):
        help_text = t("nb", "**{app_name} v{version}**\n\n"
                     "**Commands:**\n"
                     "`/help` - Show this message\n"
                     "`/pending` - List pending requests\n"
                     "`/approved` - List approved videos\n"
                     "`/stats` - Usage statistics\n"
                     "`/watch [yesterday|N]` - Watch activity & time budget\n"
                     "`/logs [days|today]` - Activity report\n"
                     "`/changelog` - Latest changes\n\n"
                     "`/addlink <url|id> [edu|fun]` - Approve a YouTube link directly\n"
                     "`/approveurl <url|id> [edu|fun]` - Alias for /addlink\n\n"
                     "`/playlist` - List playlists\n"
                     "`/playlist create <name>` - Create a playlist\n"
                     "`/playlist add <id> <url|id> [edu|fun]` - Add video to playlist\n"
                     "`/playlist delete <id>` - Delete a playlist\n\n"
                     "`/importplaylist <url> [edu|fun]` - Import a YouTube playlist\n"
                     "`/import_playlist <url> [edu|fun]` - Alias for /importplaylist\n\n"
                     "**Channel:**\n"
                     "`/channel` - List all channels\n"
                     "`/channel starter` - Kid-friendly starter list\n"
                     "`/channel allow|unallow @handle [edu|fun]`\n"
                     "`/channel block|unblock @handle`\n"
                     "`/channel cat <name> edu|fun`\n\n"
                     "**Filters & Search:**\n"
                     "`/filter` - List word filters\n"
                     "`/filter add|remove <word>`\n"
                     "`/search [days|today|all]` - Search history\n\n"
                     "**Time & Schedule:**\n"
                     "`/time` - Show status & weekly view\n"
                     "`/time setup` - Guided limit wizard\n"
                     "`/time <min|off>` - Simple watch limit\n"
                     "`/time edu|fun <min|off>` - Category limits\n"
                     "`/time start|stop [time|off]` - Schedule\n"
                     "`/time add <min>` - Bonus for today\n"
                     "`/time <day> [start|stop|edu|fun|limit|off]`\n"
                     "`/time <day> copy <days|weekdays|weekend|all>`\n"
                     "`/shorts [on|off]` - Toggle Shorts row\n"
                     "`/autoload [on|off]` - Toggle scroll loading\n\n"
                     "**Profiles:**\n"
                     "`/child` - List child profiles\n"
                     "`/child add <name> [pin]`\n"
                     "`/child remove|rename|pin <name>`\n\n"
                     "**Setup:**\n"
                     "`/setup` - Interactive setup hub\n\n")

        assert "/addlink" in help_text
        assert "/approveurl" in help_text
        assert "/importplaylist" in help_text
        assert "/import_playlist" in help_text
        assert "Godkjenn" in help_text
