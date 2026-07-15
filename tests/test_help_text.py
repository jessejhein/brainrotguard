"""Tests for the structured Telegram help text renderer."""

from bot.help_text import HELP_SECTIONS, build_help_text
from i18n import t
from i18n.locales.en import TRANSLATIONS as EN_TRANSLATIONS
from i18n.locales.nb import TRANSLATIONS as NB_TRANSLATIONS


def _tr_en(key, **kwargs):
    return t("en", key, **kwargs)


def _tr_nb(key, **kwargs):
    return t("nb", key, **kwargs)


def test_help_text_includes_current_command_inventory_in_english():
    text = build_help_text(_tr_en, "BrainRotGuard", "1.2.3")

    expected_commands = [
        "/help",
        "/pending",
        "/approved",
        "/stats",
        "/watch [yesterday|N]",
        "/logs [days|today]",
        "/changelog",
        "/addlink <url|id> [edu|fun]",
        "/approveurl <url|id> [edu|fun]",
        "/playlist",
        "/playlist create <name>",
        "/playlist add <id> <url|id> [edu|fun]",
        "/playlist delete <id>",
        "/importplaylist <url> [edu|fun]",
        "/import_playlist <url> [edu|fun]",
        "/channel",
        "/channel starter",
        "/channel allow|unallow @handle [edu|fun]",
        "/channel block|unblock @handle",
        "/channel cat <name> edu|fun",
        "/filter",
        "/filter add|remove <word>",
        "/search [days|today|all]",
        "/time",
        "/time setup",
        "/time <min|off>",
        "/time edu|fun <min|off>",
        "/time start|stop [time|off]",
        "/time add <min>",
        "/time <day> [start|stop|edu|fun|limit|off]",
        "/time <day> copy <days|weekdays|weekend|all>",
        "/shorts [on|off]",
        "/autoload [on|off]",
        "/child",
        "/child add <name> [pin]",
        "/child remove|rename|pin <name>",
        "/setup",
    ]
    for command in expected_commands:
        assert f"`{command}`" in text

    assert "**BrainRotGuard v1.2.3**" in text
    assert "**Commands:**" in text
    assert "**Channel:**" in text
    assert "**Filters & Search:**" in text
    assert "**Time & Schedule:**" in text
    assert "**Profiles:**" in text
    assert "**Setup:**" in text


def test_help_text_uses_small_norwegian_translation_keys():
    text = build_help_text(_tr_nb, "HjerneVakt", "1.2.3")

    assert "**Kommandoer:**" in text
    assert "Godkjenn en YouTube-lenke direkte" in text
    assert "Importer en YouTube-spilleliste" in text
    assert "/approveurl" in text
    assert "/import_playlist" in text


def test_help_command_inventory_has_no_duplicate_syntaxes():
    syntaxes = [
        syntax
        for _section_key, commands in HELP_SECTIONS
        for syntax, _description_key in commands
    ]
    assert len(syntaxes) == len(set(syntaxes))


def test_help_command_description_keys_exist_in_locales():
    keys = []
    for section_key, commands in HELP_SECTIONS:
        keys.append(section_key)
        keys.extend(description_key for _syntax, description_key in commands)

    for key in keys:
        assert key in EN_TRANSLATIONS
        assert key in NB_TRANSLATIONS


def test_nb_locale_does_not_store_rendered_help_bodies_as_keys():
    giant_help_keys = [
        key for key in NB_TRANSLATIONS
        if key.startswith("**{app_name} v{version}**")
    ]
    assert giant_help_keys == []
