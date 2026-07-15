# Telegram Help i18n Maintainability Plan

## Context

The current branch added new Telegram link and playlist commands to `/help`.
The implementation works, but the localized help text is hard to maintain:

- `bot/commands.py` renders the entire help body by passing one very large English string to `self.tr(...)`.
- `i18n/locales/nb.py` now contains two huge help-message keys: the old help body and the new help body.
- Any future command change requires editing a giant exact English key in at least one locale file.
- Missing or stale locale entries are difficult to detect because the key is the rendered help text itself.

This is not a deployment blocker, but it is technical debt in an area that changes often.

## Goal

Refactor Telegram `/help` so command inventory and translation strings are maintainable:

- Command syntax is defined once as structured data.
- Translatable text uses stable, small keys.
- Norwegian translations do not need giant full-help keys.
- The generated English help output remains behaviorally equivalent.
- The generated Norwegian help remains translated and includes all current commands.
- Tests protect command coverage and prevent reintroducing giant help translation keys.

## Non-Goals

- Do not change command behavior.
- Do not add new commands.
- Do not change Telegram handler registration.
- Do not change docs in `docs/telegram-commands.md` unless the implementation exposes an inconsistency.
- Do not refactor unrelated bot command rendering.
- Do not change the coffee link or full command reference link behavior.

## Target Design

Add a small renderer module:

```text
bot/help_text.py
```

The module should contain:

```python
HELP_SECTIONS = (
    (
        "help.section.commands",
        (
            ("/help", "help.command.help"),
            ("/pending", "help.command.pending"),
            ...
        ),
    ),
    ...
)

def build_help_text(tr, app_name: str, version: str) -> str:
    ...
```

`tr` is a callable compatible with `self.tr(key, **kwargs)`.

The renderer must produce this shape:

```text
**{app_name} v{version}**

**Commands:**
`/help` - Show this message
...

**Setup:**
`/setup` - Interactive setup hub

```

Then `_cmd_help()` in `bot/commands.py` should become:

```python
from bot.help_text import build_help_text

...
body = build_help_text(self.tr, self.tr("App Name"), __version__)
await update.effective_message.reply_text(_md(
    body
    + help_link
    + self.tr("☕ [Buy me a coffee]({url})", url="https://ko-fi.com/coffee4jj")
), parse_mode=MD2, disable_web_page_preview=True)
```

Keep `help_link` in `_cmd_help()` unless moving it to the renderer makes the code simpler without changing behavior.

## Exact Command Inventory

The renderer must include exactly these sections and commands, in this order.

### Commands

```text
/help - help.command.help
/pending - help.command.pending
/approved - help.command.approved
/stats - help.command.stats
/watch [yesterday|N] - help.command.watch
/logs [days|today] - help.command.logs
/changelog - help.command.changelog
/addlink <url|id> [edu|fun] - help.command.addlink
/approveurl <url|id> [edu|fun] - help.command.approveurl
/playlist - help.command.playlist
/playlist create <name> - help.command.playlist_create
/playlist add <id> <url|id> [edu|fun] - help.command.playlist_add
/playlist delete <id> - help.command.playlist_delete
/importplaylist <url> [edu|fun] - help.command.importplaylist
/import_playlist <url> [edu|fun] - help.command.import_playlist
```

### Channel

```text
/channel - help.command.channel
/channel starter - help.command.channel_starter
/channel allow|unallow @handle [edu|fun] - help.command.channel_allow
/channel block|unblock @handle - help.command.channel_block
/channel cat <name> edu|fun - help.command.channel_cat
```

### Filters & Search

```text
/filter - help.command.filter
/filter add|remove <word> - help.command.filter_modify
/search [days|today|all] - help.command.search
```

### Time & Schedule

```text
/time - help.command.time
/time setup - help.command.time_setup
/time <min|off> - help.command.time_simple
/time edu|fun <min|off> - help.command.time_category
/time start|stop [time|off] - help.command.time_schedule
/time add <min> - help.command.time_bonus
/time <day> [start|stop|edu|fun|limit|off] - help.command.time_day
/time <day> copy <days|weekdays|weekend|all> - help.command.time_copy
/shorts [on|off] - help.command.shorts
/autoload [on|off] - help.command.autoload
```

### Profiles

```text
/child - help.command.child
/child add <name> [pin] - help.command.child_add
/child remove|rename|pin <name> - help.command.child_manage
```

### Setup

```text
/setup - help.command.setup
```

## Translation Keys

Add these keys to `i18n/locales/en.py` and `i18n/locales/nb.py`.

Section keys:

```text
help.section.commands
help.section.channel
help.section.filters_search
help.section.time_schedule
help.section.profiles
help.section.setup
```

Command description keys:

```text
help.command.help
help.command.pending
help.command.approved
help.command.stats
help.command.watch
help.command.logs
help.command.changelog
help.command.addlink
help.command.approveurl
help.command.playlist
help.command.playlist_create
help.command.playlist_add
help.command.playlist_delete
help.command.importplaylist
help.command.import_playlist
help.command.channel
help.command.channel_starter
help.command.channel_allow
help.command.channel_block
help.command.channel_cat
help.command.filter
help.command.filter_modify
help.command.search
help.command.time
help.command.time_setup
help.command.time_simple
help.command.time_category
help.command.time_schedule
help.command.time_bonus
help.command.time_day
help.command.time_copy
help.command.shorts
help.command.autoload
help.command.child
help.command.child_add
help.command.child_manage
help.command.setup
```

Use the current English help descriptions as English values.

Use the current Norwegian help translations as Norwegian values.

After adding these stable keys, remove both giant full-help translation entries from `i18n/locales/nb.py`.

Do not remove unrelated translation keys.

## TDD Rules

For every slice:

1. Add or update the smallest test that proves the current design is wrong or incomplete.
2. Run the targeted test and confirm it fails for the expected reason.
3. Make the smallest production/i18n change needed to pass.
4. Run the targeted test and confirm it passes.
5. Run nearby tests.
6. After all slices, run the full suite.

## Slice 1: Add Pure Help Renderer Tests

Create:

```text
tests/test_help_text.py
```

Add tests before creating `bot/help_text.py`.

### Test: English Renderer Includes Current Commands

```python
from bot.help_text import build_help_text
from i18n import t


def _tr_en(key, **kwargs):
    return t("en", key, **kwargs)


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
```

Expected failure before implementation:

```text
ModuleNotFoundError: No module named 'bot.help_text'
```

Run:

```bash
.venv/bin/python -m pytest tests/test_help_text.py -q
```

## Slice 2: Implement `bot/help_text.py`

Create `bot/help_text.py`.

Implementation requirements:

- Use a module-level tuple named `HELP_SECTIONS`.
- Keep command syntax strings literal and untranslated.
- Translate only section titles and command descriptions.
- Use `-` as the separator between command syntax and description.
- Return a single string ending with exactly two newlines so `_cmd_help()` can append the reference link without changing spacing.
- Do not import Telegram libraries from this module.
- Do not import `i18n` from this module. The caller provides `tr`.

Suggested implementation:

```python
"""Telegram /help text renderer."""

HELP_SECTIONS = (
    ("help.section.commands", (...)),
    ...
)


def build_help_text(tr, app_name: str, version: str) -> str:
    """Build Telegram /help text from structured command metadata."""
    lines = [f"**{app_name} v{version}**", ""]
    for section_key, commands in HELP_SECTIONS:
        lines.append(f"**{tr(section_key)}:**")
        for syntax, description_key in commands:
            lines.append(f"`{syntax}` - {tr(description_key)}")
        lines.append("")
    return "\n".join(lines) + "\n"
```

Add English translation keys first so English test passes.

Run:

```bash
.venv/bin/python -m pytest tests/test_help_text.py -q
```

## Slice 3: Wire `_cmd_help()` To Renderer

Update `bot/commands.py`.

Required changes:

- Add `from bot.help_text import build_help_text` near the existing imports.
- Replace the giant `self.tr("...")` help body with `build_help_text(...)`.
- Preserve `_md(...)`.
- Preserve `parse_mode=MD2`.
- Preserve `disable_web_page_preview=True`.
- Preserve the full command reference link and Ko-fi link.

Add or update an existing bot help test if one already covers `_cmd_help()`.

If no direct `_cmd_help()` test exists, add one to a new or existing bot test file:

```python
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
        assert "Full command reference" in reply
        assert "Buy me a coffee" in reply
    finally:
        store.close()
```

Use the same dummy update/context style already used in `tests/test_bot_links.py` and `tests/test_bot_playlists.py`.

Run:

```bash
.venv/bin/python -m pytest tests/test_help_text.py tests/test_bot_links.py tests/test_bot_playlists.py tests/test_i18n.py -q
```

If the new `_cmd_help()` test is placed in a different file, include that file in the command.

## Slice 4: Add Norwegian Stable Keys

Update `i18n/locales/nb.py` with stable help section and command description keys.

Use translations from the current giant help text. Required examples:

```python
"help.section.commands": "Kommandoer",
"help.section.channel": "Kanal",
"help.section.filters_search": "Filtre og søk",
"help.section.time_schedule": "Tid og tidsplan",
"help.section.profiles": "Profiler",
"help.section.setup": "Oppsett",
"help.command.addlink": "Godkjenn en YouTube-lenke direkte",
"help.command.approveurl": "Alias for /addlink",
"help.command.importplaylist": "Importer en YouTube-spilleliste",
"help.command.import_playlist": "Alias for /importplaylist",
```

Add a test to `tests/test_help_text.py`:

```python
def _tr_nb(key, **kwargs):
    return t("nb", key, **kwargs)


def test_help_text_uses_small_norwegian_translation_keys():
    text = build_help_text(_tr_nb, "HjerneVakt", "1.2.3")

    assert "**Kommandoer:**" in text
    assert "Godkjenn en YouTube-lenke direkte" in text
    assert "Importer en YouTube-spilleliste" in text
    assert "/approveurl" in text
    assert "/import_playlist" in text
```

Run:

```bash
.venv/bin/python -m pytest tests/test_help_text.py tests/test_i18n.py -q
```

## Slice 5: Remove Giant Help Translation Keys

Remove both giant full-help translation keys from `i18n/locales/nb.py`.

Do not remove the small stable help keys added in Slice 4.

Add a regression test to `tests/test_i18n.py` or `tests/test_help_text.py`:

```python
from i18n.locales.nb import TRANSLATIONS as NB_TRANSLATIONS


def test_nb_locale_does_not_store_rendered_help_bodies_as_keys():
    giant_help_keys = [
        key for key in NB_TRANSLATIONS
        if key.startswith("**{app_name} v{version}**")
    ]
    assert giant_help_keys == []
```

Run:

```bash
.venv/bin/python -m pytest tests/test_help_text.py tests/test_i18n.py -q
```

## Slice 6: Guard Against Command Drift

Add a test to `tests/test_help_text.py` that protects the command inventory from accidental removal.

```python
from bot.help_text import HELP_SECTIONS


def test_help_command_inventory_has_no_duplicate_syntaxes():
    syntaxes = [
        syntax
        for _section_key, commands in HELP_SECTIONS
        for syntax, _description_key in commands
    ]
    assert len(syntaxes) == len(set(syntaxes))


def test_help_command_description_keys_exist_in_locales():
    from i18n.locales.en import TRANSLATIONS as EN_TRANSLATIONS
    from i18n.locales.nb import TRANSLATIONS as NB_TRANSLATIONS

    keys = [
        key
        for section_key, commands in HELP_SECTIONS
        for key in [section_key, *(description_key for _syntax, description_key in commands)]
    ]
    for key in keys:
        assert key in EN_TRANSLATIONS
        assert key in NB_TRANSLATIONS
```

Run:

```bash
.venv/bin/python -m pytest tests/test_help_text.py tests/test_i18n.py -q
```

## Final Verification

Run targeted tests:

```bash
.venv/bin/python -m pytest tests/test_help_text.py -q
.venv/bin/python -m pytest tests/test_i18n.py -q
.venv/bin/python -m pytest tests/test_bot_links.py tests/test_bot_playlists.py -q
```

Run the full suite:

```bash
.venv/bin/python -m pytest -q
```

Run whitespace validation:

```bash
git diff --check main...HEAD
```

## Manual Review Checklist

- `/help` still includes the full command reference link.
- `/help` still includes the Ko-fi link.
- `/help` still renders markdown correctly in Telegram MarkdownV2.
- English `/help` contains all commands listed in this plan.
- Norwegian `/help` contains all commands listed in this plan.
- `i18n/locales/nb.py` no longer has any key beginning with `**{app_name} v{version}**`.
- The new renderer module has no Telegram dependency.
- Adding a future command should require editing only:
  - `HELP_SECTIONS`,
  - English stable key,
  - Norwegian stable key,
  - tests if the new command is part of expected inventory.

## Done Criteria

This plan is complete only when:

- `bot/help_text.py` exists and owns the structured help command inventory.
- `bot/commands.py` no longer contains the giant help body literal.
- `i18n/locales/en.py` and `i18n/locales/nb.py` use stable help keys.
- `i18n/locales/nb.py` contains no rendered full-help translation keys.
- Tests cover English command inventory, Norwegian translated output, no duplicate command syntax, all translation keys present, and no giant Norwegian help keys.
- Targeted tests pass.
- Full suite passes.
- `git diff --check main...HEAD` passes.
