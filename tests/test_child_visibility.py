"""Child-facing triage text on the waiting page and the requests list."""

from types import SimpleNamespace

from data.child_store import ChildStore
from tests.test_web_integration import AppClient, _create_test_app, _login
from triage.store import TriageStore


def _client(store, triage_store):
    app = _create_test_app(store)
    app.state.triage = SimpleNamespace(store=triage_store)
    client = AppClient(app, raise_server_exceptions=True)
    _login(client, "1234")
    return client


def _store_with_profile(video_store):
    video_store.create_profile("default", "Test Child", pin="1234")
    return video_store


def test_pending_page_shows_summary_and_hides_reason(video_store, tmp_path):
    store = _store_with_profile(video_store)
    cs = ChildStore(store, "default")
    cs.add_video("pendvid1234", "Pend Title", "Chan", duration=10)
    triage = TriageStore(str(tmp_path / "triage.db"))
    triage.record(
        request_id="default:pendvid1234", profile_id="default", video_id="pendvid1234",
        verdict="allow", summary="A quiet drawing lesson.", reason="DO_NOT_SHOW",
        confidence=0.97, rank="HIGH", outcome="hold_released",
    )
    # Another child's row must not leak onto this profile.
    triage.record(
        request_id="other:pendvid1234", profile_id="other", video_id="pendvid1234",
        verdict="deny", summary="OTHER CHILD", reason="OTHER REASON",
        outcome="hold_released",
    )
    client = _client(store, triage)
    resp = client.get("/pending/pendvid1234")
    assert resp.status_code == 200
    assert "Reviewed: looks fine" in resp.text
    assert "A quiet drawing lesson." in resp.text
    assert "DO_NOT_SHOW" not in resp.text
    assert "OTHER CHILD" not in resp.text
    assert "HIGH" not in resp.text
    assert "0.97" not in resp.text
    assert "flagged" not in resp.text.lower()


def test_pending_without_verdict_has_no_summary(video_store, tmp_path):
    store = _store_with_profile(video_store)
    cs = ChildStore(store, "default")
    cs.add_video("waitvid1234", "Wait Title", "Chan", duration=10)
    triage = TriageStore(str(tmp_path / "triage.db"))
    triage.record(
        request_id="default:waitvid1234", profile_id="default", video_id="waitvid1234",
        verdict="none", summary="should stay hidden", outcome="hold_timeout",
    )
    client = _client(store, triage)
    resp = client.get("/pending/waitvid1234")
    assert resp.status_code == 200
    assert "Waiting for approval..." in resp.text
    assert "should stay hidden" not in resp.text
    assert "Reviewed:" not in resp.text


def test_requests_includes_denied_with_label(video_store, tmp_path):
    store = _store_with_profile(video_store)
    cs = ChildStore(store, "default")
    cs.add_video("denyvid1234", "Denied Title", "Chan", duration=10)
    cs.update_status("denyvid1234", "denied")
    cs.add_video("pendvid2234", "Still Waiting", "Chan", duration=10)
    triage = TriageStore(str(tmp_path / "triage.db"))
    triage.record(
        request_id="default:denyvid1234", profile_id="default", video_id="denyvid1234",
        verdict="deny", summary="A loud cartoon.", reason="DO_NOT_SHOW",
        confidence=0.99, rank="HIGH", outcome="hold_released",
    )
    client = _client(store, triage)
    resp = client.get("/requests")
    assert resp.status_code == 200
    assert "Denied Title" in resp.text
    assert "Not approved" in resp.text
    assert "Still Waiting" in resp.text
    assert "Waiting" in resp.text
    assert "A loud cartoon." in resp.text
    assert "Reviewed: a parent is deciding" in resp.text
    assert "DO_NOT_SHOW" not in resp.text
    assert "HIGH" not in resp.text
    assert "0.99" not in resp.text
