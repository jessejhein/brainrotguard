"""HMAC helpers for the triage bridge (both directions).

Scheme: hex HMAC-SHA256 over ``b"<timestamp>.<raw body>"``. The timestamp is
authenticated, so a captured request cannot be replayed outside the skew
window. Hermes' webhook platform accepts exactly this as
``X-Webhook-Signature-V2`` + ``X-Webhook-Timestamp``; the verdict callback uses
the same computation under ``X-BRG-Signature`` + ``X-BRG-Timestamp``.
"""

import hashlib
import hmac
import time

DEFAULT_MAX_SKEW_S = 300


def sign(secret: str, body: bytes, timestamp: str | int) -> str:
    """Return the hex HMAC-SHA256 of ``"<timestamp>.<body>"``."""
    if not secret:
        raise ValueError("signing requires a non-empty secret")
    ts = str(timestamp).encode()
    return hmac.new(secret.encode(), ts + b"." + body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, timestamp: str, signature: str,
           *, max_skew_s: int = DEFAULT_MAX_SKEW_S, now: float | None = None) -> bool:
    """Constant-time verification of a signed body; rejects stale timestamps."""
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(str(timestamp).strip())
    except (TypeError, ValueError):
        return False
    current = int(time.time() if now is None else now)
    if abs(current - ts) > max_skew_s:
        return False
    expected = sign(secret, body, ts)
    provided = str(signature).strip().lower()
    if provided.startswith("sha256="):
        provided = provided[len("sha256="):]
    return hmac.compare_digest(expected, provided)
