"""Telegram /help text renderer."""

HELP_SECTIONS = (
    (
        "help.section.commands",
        (
            ("/help", "help.command.help"),
            ("/pending", "help.command.pending"),
            ("/approved", "help.command.approved"),
            ("/stats", "help.command.stats"),
            ("/watch [yesterday|N]", "help.command.watch"),
            ("/logs [days|today]", "help.command.logs"),
            ("/changelog", "help.command.changelog"),
            ("/addlink <url|id> [edu|fun]", "help.command.addlink"),
            ("/approveurl <url|id> [edu|fun]", "help.command.approveurl"),
            ("/playlist", "help.command.playlist"),
            ("/playlist create <name>", "help.command.playlist_create"),
            ("/playlist add <id> <url|id> [edu|fun]", "help.command.playlist_add"),
            ("/playlist delete <id>", "help.command.playlist_delete"),
            ("/importplaylist <url> [edu|fun]", "help.command.importplaylist"),
            ("/import_playlist <url> [edu|fun]", "help.command.import_playlist"),
        ),
    ),
    (
        "help.section.channel",
        (
            ("/channel", "help.command.channel"),
            ("/channel starter", "help.command.channel_starter"),
            ("/channel allow|unallow @handle [edu|fun]", "help.command.channel_allow"),
            ("/channel block|unblock @handle", "help.command.channel_block"),
            ("/channel cat <name> edu|fun", "help.command.channel_cat"),
        ),
    ),
    (
        "help.section.filters_search",
        (
            ("/filter", "help.command.filter"),
            ("/filter add|remove <word>", "help.command.filter_modify"),
            ("/search [days|today|all]", "help.command.search"),
        ),
    ),
    (
        "help.section.time_schedule",
        (
            ("/time", "help.command.time"),
            ("/time setup", "help.command.time_setup"),
            ("/time <min|off>", "help.command.time_simple"),
            ("/time edu|fun <min|off>", "help.command.time_category"),
            ("/time start|stop [time|off]", "help.command.time_schedule"),
            ("/time add <min>", "help.command.time_bonus"),
            ("/time <day> [start|stop|edu|fun|limit|off]", "help.command.time_day"),
            ("/time <day> copy <days|weekdays|weekend|all>", "help.command.time_copy"),
            ("/shorts [on|off]", "help.command.shorts"),
            ("/autoload [on|off]", "help.command.autoload"),
        ),
    ),
    (
        "help.section.profiles",
        (
            ("/child", "help.command.child"),
            ("/child add <name> [pin]", "help.command.child_add"),
            ("/child remove|rename|pin <name>", "help.command.child_manage"),
        ),
    ),
    (
        "help.section.setup",
        (
            ("/setup", "help.command.setup"),
        ),
    ),
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
