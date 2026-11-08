"""Tests for the triage bridge HMAC helpers."""

import time

from triage.signing import sign, verify

SECRET = "s3cret"
BODY = b'{"request_id":"default:abc"}'


def test_roundtrip():
    ts = str(int(time.time()))
    assert verify(SECRET, BODY, ts, sign(SECRET, BODY, ts))


def test_accepts_sha256_prefix():
    ts = str(int(time.time()))
    assert verify(SECRET, BODY, ts, "sha256=" + sign(SECRET, BODY, ts))


def test_rejects_tampered_body():
    ts = str(int(time.time()))
    sig = sign(SECRET, BODY, ts)
    assert not verify(SECRET, BODY + b" ", ts, sig)


def test_rejects_stale_timestamp():
    ts = str(int(time.time()) - 3600)
    assert not verify(SECRET, BODY, ts, sign(SECRET, BODY, ts))


def test_rejects_wrong_secret():
    ts = str(int(time.time()))
    assert not verify("other", BODY, ts, sign(SECRET, BODY, ts))


def test_rejects_missing_parts():
    ts = str(int(time.time()))
    sig = sign(SECRET, BODY, ts)
    assert not verify("", BODY, ts, sig)
    assert not verify(SECRET, BODY, "", sig)
    assert not verify(SECRET, BODY, ts, "")


def test_rejects_non_numeric_timestamp():
    assert not verify(SECRET, BODY, "yesterday", sign(SECRET, BODY, "yesterday"))


def test_sign_requires_secret():
    try:
        sign("", BODY, "1")
    except ValueError:
        return
    raise AssertionError("sign() should refuse an empty secret")
