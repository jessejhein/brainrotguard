"""Internal verdict callback used by the triage bridge (not for browsers).

Authenticated by HMAC over ``<timestamp>.<raw body>`` with the callback secret —
never by the PIN/session cookie. Disabled (404) whenever the bridge is off, so
the endpoint does not exist as an attack surface in a default install.
"""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from triage.service import VerdictError
from triage.signing import verify

logger = logging.getLogger(__name__)

router = APIRouter()

# A verdict is a few hundred bytes. Bound the read so an unauthenticated caller
# cannot make the process buffer an arbitrary body before the HMAC is checked.
MAX_BODY_BYTES = 16 * 1024


async def _read_body(request: Request) -> bytes | None:
    """Read the request body up to ``MAX_BODY_BYTES``; ``None`` when over the cap."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return None
    return bytes(body)


@router.post("/internal/triage/{request_id}")
async def triage_verdict(request: Request, request_id: str):
    service = getattr(request.app.state, "triage", None)
    if service is None or not service.enabled:
        return JSONResponse({"error": "disabled"}, status_code=404)

    raw = await _read_body(request)
    if raw is None:
        logger.warning("Triage callback rejected for %s: body too large", request_id)
        return JSONResponse({"error": "payload too large"}, status_code=413)

    timestamp = request.headers.get("X-BRG-Timestamp", "")
    signature = request.headers.get("X-BRG-Signature", "")
    if not verify(service.config.callback_secret, raw, timestamp, signature):
        logger.warning("Triage callback rejected for %s: bad signature", request_id)
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    try:
        result = await service.handle_verdict(request_id, payload)
    except VerdictError as exc:
        logger.info("Triage verdict rejected for %s: %s", request_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse(result)
