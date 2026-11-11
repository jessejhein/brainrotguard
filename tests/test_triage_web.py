"""Tests for the internal verdict callback endpoint."""

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import TriageConfig
from triage.service import TriageService
from triage.signing import sign
from triage.store import TriageStore
from web.middleware import PinAuthMiddleware
from web.routers.triage import router

CB_SECRET = "cb-secret"
URL = "/internal/triage/default:abc123"


def _verdict(**over):
    payload = {
        "request_id": "default:abc123",
        "verdict": "uncertain",
        "confidence": 0.55,
        "summary": "A Roblox obby video.",
        "reason": "Topic never approved before.",
    }
    payload.update(over)
    return payload


def _service(video_store, tmp_path, *, enabled=True):
    cfg = TriageConfig(enabled=enabled, url="http://hermes/x", secret="out",
                       callback_secret=CB_SECRET)
    store = TriageStore(str(tmp_path / "triage.db"))
    return TriageService(cfg, video_store, store, bot=None)


def _client(service):
    app = FastAPI()
    app.include_router(router)
    app.state.triage = service
    return TestClient(app)


def _post(client, payload, *, secret=CB_SECRET, ts=None, sig=None):
    body = json.dumps(payload).encode()
    timestamp = ts if ts is not None else str(int(time.time()))
    signature = sig if sig is not None else sign(secret, body, timestamp)
    return client.post(URL, content=body, headers={
        "Content-Type": "application/json",
        "X-BRG-Timestamp": timestamp,
        "X-BRG-Signature": signature,
    })


def test_disabled_when_no_service(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.triage = None
    client = TestClient(app)
    assert client.post(URL, json={}).status_code == 404


def test_disabled_when_config_off(video_store, tmp_path):
    client = _client(_service(video_store, tmp_path, enabled=False))
    assert _post(client, _verdict()).status_code == 404


def test_valid_verdict_accepted(video_store, tmp_path):
    video_store.add_video("abc123", "Roblox obby", "SomeCreator", profile_id="default")
    service = _service(video_store, tmp_path)
    resp = _post(_client(service), _verdict())
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert service.store.get("default:abc123")["verdict"] == "uncertain"


def test_bad_signature_rejected(video_store, tmp_path):
    client = _client(_service(video_store, tmp_path))
    assert _post(client, _verdict(), sig="deadbeef").status_code == 401


def test_stale_timestamp_rejected(video_store, tmp_path):
    client = _client(_service(video_store, tmp_path))
    old = str(int(time.time()) - 3600)
    assert _post(client, _verdict(), ts=old).status_code == 401


def test_missing_headers_rejected(video_store, tmp_path):
    client = _client(_service(video_store, tmp_path))
    resp = client.post(URL, content=json.dumps(_verdict()).encode(),
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 401


def test_invalid_json_rejected(video_store, tmp_path):
    service = _service(video_store, tmp_path)
    client = _client(service)
    body = b"not json"
    ts = str(int(time.time()))
    resp = client.post(URL, content=body, headers={
        "X-BRG-Timestamp": ts,
        "X-BRG-Signature": sign(CB_SECRET, body, ts),
    })
    assert resp.status_code == 400


def test_request_id_mismatch_rejected(video_store, tmp_path):
    client = _client(_service(video_store, tmp_path))
    assert _post(client, _verdict(request_id="default:other")).status_code == 400


def test_malformed_verdict_rejected(video_store, tmp_path):
    client = _client(_service(video_store, tmp_path))
    assert _post(client, {"request_id": "default:abc123", "verdict": "maybe",
                          "summary": "x"}).status_code == 400


def test_duplicate_returns_duplicate(video_store, tmp_path):
    video_store.add_video("abc123", "Roblox obby", "SomeCreator", profile_id="default")
    client = _client(_service(video_store, tmp_path))
    assert _post(client, _verdict()).status_code == 200
    second = _post(client, _verdict(verdict="deny"))
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"


def test_internal_path_bypasses_pin_auth(video_store, tmp_path):
    """A PIN-protected install must not redirect the machine callback to /login."""
    app = FastAPI()
    app.include_router(router)
    app.state.video_store = video_store
    app.state.triage = _service(video_store, tmp_path)
    app.add_middleware(PinAuthMiddleware, pin="4321")
    client = TestClient(app, follow_redirects=False)
    resp = client.post(URL, content=b"{}", headers={})
    assert resp.status_code == 401  # reached the router, which rejected the signature


def test_pin_auth_enforced_except_on_the_triage_path(video_store, tmp_path):
    """The exemption is the triage path only — not the whole /internal/ prefix."""
    from starlette.middleware.sessions import SessionMiddleware

    video_store.create_profile("kid", "Kid", pin="1234")
    video_store.create_profile("kid2", "Kid 2", pin="5678")
    app = FastAPI()
    app.include_router(router)
    app.state.video_store = video_store
    app.state.triage = _service(video_store, tmp_path)
    # Same stack as main.py: PIN middleware inside, session middleware outside.
    app.add_middleware(PinAuthMiddleware, pin="4321")
    app.add_middleware(SessionMiddleware, secret_key="test", same_site="strict")
    client = TestClient(app, follow_redirects=False)

    assert client.post(URL, content=b"{}", headers={}).status_code == 401
    other = client.post("/internal/other", content=b"{}", headers={})
    assert 300 <= other.status_code < 400  # redirected to /login, middleware still applies


def test_oversized_body_is_rejected(video_store, tmp_path):
    client = _client(_service(video_store, tmp_path))
    resp = client.post(URL, content=b"x" * (20 * 1024),
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 413
    assert resp.json()["error"] == "payload too large"
