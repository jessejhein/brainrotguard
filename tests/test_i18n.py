"""Tests for locale and time formatting helpers."""

from i18n import app_name, format_time, format_time_compact, normalize_time_format, t
from i18n.locales.nb import TRANSLATIONS as NB_TRANSLATIONS


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

    def test_nb_help_uses_small_stable_translation_keys(self):
        assert t("nb", "help.section.commands") == "Kommandoer"
        assert t("nb", "help.command.addlink") == "Godkjenn en YouTube-lenke direkte"
        assert t("nb", "help.command.approveurl") == "Alias for /addlink"
        assert t("nb", "help.command.importplaylist") == "Importer en YouTube-spilleliste"
        assert t("nb", "help.command.import_playlist") == "Alias for /importplaylist"

    def test_nb_locale_does_not_store_rendered_help_bodies_as_keys(self):
        giant_help_keys = [
            key for key in NB_TRANSLATIONS
            if key.startswith("**{app_name} v{version}**")
        ]
        assert giant_help_keys == []
