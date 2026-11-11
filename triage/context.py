"""Build the deterministic request context handed to the triage agent.

Everything here is a fact the database already owns: channel allow/block state,
prior decisions for the channel, exact-duplicate approvals, word-filter hits and
the child's approved-taste list. The agent judges the residual — it does not
re-derive these rules, and it cannot override them.
"""

from datetime import datetime, timezone
import re

TITLE_LIMIT = 300
HISTORY_LIMIT = 10
TASTE_LIMIT = 25


def _short(value, limit: int = TITLE_LIMIT) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _history_row(row: dict) -> dict:
    return {
        "title": _short(row.get("title")),
        "status": row.get("status", ""),
        "category": row.get("category") or None,
        "requested_at": row.get("requested_at", ""),
    }


def build_request_context(store, video: dict, profile_id: str = "default", *,
                          now: datetime | None = None) -> dict:
    """Return the JSON-serialisable context for one new request."""
    video_id = video["video_id"]
    channel_name = video.get("channel_name") or ""
    channel_id = video.get("channel_id") or ""

    def status_list(status: str) -> list[dict]:
        if channel_id:
            return store.get_by_status(status, channel_id=channel_id, profile_id=profile_id)
        return store.get_by_status(status, channel_name=channel_name, profile_id=profile_id)

    allowed = bool(store.is_channel_allowed(channel_name, channel_id, profile_id=profile_id))
    blocked = bool(store.is_channel_blocked(channel_name, channel_id, profile_id=profile_id))
    approved_rows = status_list("approved")
    denied_rows = status_list("denied")
    if allowed:
        channel_state = "allowed"
    elif blocked:
        channel_state = "blocked"
    else:
        channel_state = "none"

    other = store.find_video_approved_for_others(video_id, profile_id)
    other_profile = None
    if other:
        row = store.get_profile(other.get("profile_id") or "")
        other_profile = (row or {}).get("display_name") or other.get("profile_id")

    filters = store.get_word_filters_set()
    title = video.get("title") or ""
    # Same semantics as the app's own filter (web/cache.py: \b…\b, case-insensitive).
    # Substring matching here would report hits the deterministic layer never fires on.
    hits = sorted(
        word for word in filters
        if word and re.search(r"\b" + re.escape(word) + r"\b", title, re.IGNORECASE)
    )

    profiles = store.get_profiles()
    profile_row = store.get_profile(profile_id) or {}

    requested_at = video.get("requested_at") or ""
    if not requested_at:
        requested_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")

    return {
        "request_id": f"{profile_id}:{video_id}",
        "video_id": video_id,
        "title": _short(video.get("title")),
        "channel_name": _short(channel_name, 160),
        "channel_id": channel_id or None,
        "duration_s": video.get("duration"),
        "is_short": bool(video.get("is_short")),
        "thumbnail_url": video.get("thumbnail_url") or None,
        "requested_at": requested_at,
        "child": {
            "profile_id": profile_id,
            "display_name": profile_row.get("display_name") or profile_id,
            "profile_count": len(profiles),
        },
        "channel_state": channel_state,
        "channel_category": store.get_channel_category(channel_name, profile_id=profile_id),
        "channel_history": {
            "approved_count": len(approved_rows),
            "denied_count": len(denied_rows),
            "recent": [_history_row(row) for row in approved_rows[:HISTORY_LIMIT]],
            "recent_denied": [_history_row(row) for row in denied_rows[:HISTORY_LIMIT]],
        },
        "previously_approved_for_other_child": bool(other),
        "other_child_name": other_profile,
        "denied_before": video_id in store.get_denied_video_ids(profile_id),
        "word_filter_hits": hits,
        "taste": [
            {
                "title": _short(row.get("title")),
                "category": row.get("category") or None,
            }
            for row in store.get_requested_approved(limit=TASTE_LIMIT, profile_id=profile_id)
        ],
    }
