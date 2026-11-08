"""Tests for the deterministic request context sent to the triage agent."""

import pytest

from triage.context import build_request_context


@pytest.fixture
def video(video_store):
    return video_store.add_video(
        "abc123", "Minecraft build tutorial", "SomeCreator",
        duration=412, channel_id="UC123", profile_id="default",
    )


def test_request_id_and_basics(video_store, video):
    ctx = build_request_context(video_store, video, "default")
    assert ctx["request_id"] == "default:abc123"
    assert ctx["video_id"] == "abc123"
    assert ctx["title"] == "Minecraft build tutorial"
    assert ctx["duration_s"] == 412
    assert ctx["channel_id"] == "UC123"
    assert ctx["child"]["profile_id"] == "default"


def test_unknown_channel_is_none(video_store, video):
    ctx = build_request_context(video_store, video, "default")
    assert ctx["channel_state"] == "none"
    assert ctx["channel_category"] is None
    assert ctx["channel_history"]["approved_count"] == 0


def test_allowed_channel_and_category(video_store, video):
    video_store.add_channel("SomeCreator", "allowed", channel_id="UC123", category="fun")
    ctx = build_request_context(video_store, video, "default")
    assert ctx["channel_state"] == "allowed"
    assert ctx["channel_category"] == "fun"


def test_blocked_channel(video_store, video):
    video_store.add_channel("SomeCreator", "blocked", channel_id="UC123")
    ctx = build_request_context(video_store, video, "default")
    assert ctx["channel_state"] == "blocked"


def test_word_filter_hits_are_case_insensitive(video_store, video):
    video_store.add_word_filter("Minecraft")
    ctx = build_request_context(video_store, video, "default")
    assert ctx["word_filter_hits"] == ["minecraft"]


def test_denied_before_flag(video_store, video):
    video_store.update_status("abc123", "denied", profile_id="default")
    ctx = build_request_context(video_store, video, "default")
    assert ctx["denied_before"] is True


def test_channel_history_and_taste(video_store, video):
    video_store.add_video("old1", "Minecraft castle", "SomeCreator",
                          channel_id="UC123", profile_id="default")
    video_store.update_status("old1", "approved", profile_id="default")
    ctx = build_request_context(video_store, video, "default")
    assert ctx["channel_history"]["approved_count"] == 1
    assert [row["title"] for row in ctx["channel_history"]["recent"]] == ["Minecraft castle"]
    assert "Minecraft castle" in [row["title"] for row in ctx["taste"]]


def test_previously_approved_for_other_child(video_store, video):
    video_store.create_profile("kid2", "Second Kid")
    other = video_store.add_video("abc123", "Minecraft build tutorial", "SomeCreator",
                                  channel_id="UC123", profile_id="kid2")
    video_store.update_status(other["video_id"], "approved", profile_id="kid2")
    ctx = build_request_context(video_store, video, "default")
    assert ctx["previously_approved_for_other_child"] is True
    assert ctx["other_child_name"] == "Second Kid"
