"""Triage bridge service: push a request context, accept a verdict, reply.

Phase 1 behaviour (the only implemented mode): the notification goes out exactly
as before, the summary arrives afterwards as a threaded reply, and the video's
status is never touched. A missing, late, malformed, duplicate or unsigned
verdict degrades to "no reply" — never to an approval.
"""

import asyncio
import json
import logging
import time

import aiohttp

from .context import build_request_context
from .signing import sign

logger = logging.getLogger(__name__)

VERDICTS = ("allow", "uncertain", "deny")
MAX_SUMMARY = 1000
MAX_REASON = 300
MAX_REPLY = 3000
# How long a pending request is remembered past its deadline, so a verdict that
# arrives a moment late is still classified "late" rather than "unknown".
PENDING_TTL_S = 900
TIMEOUT_GRACE_S = 2.0
POST_TIMEOUT_S = 10

HIGH_MIN = 0.85
MEDIUM_MIN = 0.60


class VerdictError(ValueError):
    """The verdict payload does not satisfy the contract."""


def rank_for(confidence: float) -> str:
    """Map a raw confidence onto the rank the parent reads."""
    if confidence >= HIGH_MIN:
        return "HIGH"
    if confidence >= MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


def _clip(value: object, limit: int) -> str:
    text = "" if value is None else str(value).strip()
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def normalise_verdict(payload: object) -> dict:
    """Validate and canonicalise a verdict payload, or raise :class:`VerdictError`."""
    if not isinstance(payload, dict):
        raise VerdictError("payload must be a JSON object")

    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id or ":" not in request_id:
        raise VerdictError("request_id must be 'profile_id:video_id'")

    verdict = str(payload.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        raise VerdictError("verdict must be one of allow, uncertain, deny")

    try:
        confidence = float(payload.get("confidence", 0))
    except (TypeError, ValueError):
        raise VerdictError("confidence must be a number") from None
    if not 0.0 <= confidence <= 1.0:
        raise VerdictError("confidence must be between 0 and 1")

    # The rank is always derived from the number: a self-reported HIGH at 0.2
    # would let the agent mint the label stage 2 gates on. The payload's rank is
    # advisory only and is ignored.
    rank = rank_for(confidence)

    category = payload.get("category")
    category = str(category).strip().lower() if category else None
    if category not in (None, "edu", "fun"):
        raise VerdictError("category must be edu, fun or null")

    summary = _clip(payload.get("summary"), MAX_SUMMARY)
    if not summary:
        raise VerdictError("summary is required")

    return {
        "request_id": request_id,
        "verdict": verdict,
        "confidence": confidence,
        "rank": rank,
        "category": category,
        "summary": summary,
        "reason": _clip(payload.get("reason"), MAX_REASON),
        "signals": payload.get("signals") if isinstance(payload.get("signals"), dict) else {},
        "enrichment": payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else {},
    }


def render_reply(verdict: dict) -> str:
    """Render the parent-facing reply: what it is, what we suggest, why."""
    label = {"allow": "ALLOW", "uncertain": "UNCERTAIN", "deny": "DENY"}[verdict["verdict"]]
    lines = [
        "\U0001F9E0 Triage (shadow \u2014 no action)",
        f"What it is: {verdict['summary']}",
        f"Recommendation: {label} \u00b7 confidence {verdict['rank']} ({verdict['confidence']:.2f})",
    ]
    if verdict.get("reason"):
        lines.append(f"Why: {verdict['reason']}")
    text = "\n".join(lines)
    return text if len(text) <= MAX_REPLY else text[: MAX_REPLY - 1] + "\u2026"


class _Pending:
    __slots__ = ("chat_id", "message_id", "deadline", "started", "timer")

    def __init__(self, chat_id, message_id, deadline, started):
        self.chat_id = chat_id
        self.message_id = message_id
        self.deadline = deadline
        self.started = started
        self.timer: asyncio.Task | None = None


class TriageService:
    """Owns the outbound push, the pending map and the reply rendering."""

    def __init__(self, config, video_store, store, bot=None, *, poster=None):
        self.config = config
        self.video_store = video_store
        self.store = store
        self.bot = bot
        self._poster = poster
        self._pending: dict[str, _Pending] = {}
        self._tasks: set[asyncio.Task] = set()
        # Deadline timers live apart from `_tasks` (the in-flight pushes) so a
        # caller draining `_tasks` is never blocked by a pending deadline.
        self._timers: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config, "enabled", False))

    @property
    def mode(self) -> str:
        # Anything other than shadow is refused: phase 2 is not built.
        return "shadow"

    async def on_request(self, video: dict, profile_id: str, ref=None) -> None:
        """Called after the notification is sent. Never raises into the request path."""
        if not self.enabled:
            return
        try:
            request_id = f"{profile_id}:{video['video_id']}"
            if self.store.get(request_id):
                # Already triaged (the parent re-requested an existing video, or
                # tapped Resend). A second verdict would be dropped as a duplicate,
                # so don't spend an agent run on it.
                logger.info("Triage skipped for %s: already has a decision", request_id)
                return
            context = build_request_context(self.video_store, video, profile_id)
        except Exception as exc:  # context building must never break a request
            logger.error("Triage context build failed for %s: %s", profile_id, exc)
            return

        if ref is not None:
            now = time.monotonic()
            pending = _Pending(
                getattr(ref, "chat_id", None),
                getattr(ref, "message_id", None),
                now + max(1, int(self.config.deadline_s or 60)),
                now,
            )
            self._pending[request_id] = pending
            self._schedule_timeout(request_id, pending)

        task = asyncio.create_task(self._post(context))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _post(self, context: dict) -> bool:
        try:
            body = json.dumps(context, separators=(",", ":"), ensure_ascii=False).encode()
            if self._poster is not None:
                return bool(await self._poster(context, body))
            timestamp = str(int(time.time()))
            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Signature-V2": sign(self.config.secret, body, timestamp),
                "X-Request-ID": context["request_id"],
            }
            timeout = aiohttp.ClientTimeout(total=POST_TIMEOUT_S)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.config.url, data=body, headers=headers) as resp:
                    if resp.status >= 300:
                        logger.warning(
                            "Triage push rejected for %s: HTTP %s", context["request_id"], resp.status)
                        return False
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Triage push failed for %s: %s", context.get("request_id"), exc)
            return False

    async def handle_verdict(self, request_id: str, payload: object) -> dict:
        """Validate, persist and (when still useful) post the threaded reply."""
        verdict = normalise_verdict(payload)
        if verdict["request_id"] != request_id:
            raise VerdictError("request_id does not match the URL")

        if self.store.get(request_id):
            return {"status": "duplicate", "request_id": request_id}

        profile_id, _, video_id = request_id.partition(":")
        pending = self._pending.pop(request_id, None)
        if pending is not None and pending.timer is not None:
            pending.timer.cancel()
        now = time.monotonic()
        latency_ms = int((now - pending.started) * 1000) if pending else None

        if pending is None:
            outcome = "unknown_request"
        elif now > pending.deadline:
            outcome = "late"
        else:
            row = self.video_store.get_video(video_id, profile_id)
            if not row or row.get("status") != "pending":
                outcome = "skipped_decided"
            elif not self.config.reply_enabled or pending.message_id is None or self.bot is None:
                outcome = "logged"
            else:
                sent = await self._send_reply(pending, render_reply(verdict))
                outcome = "replied" if sent else "logged"

        recorded = self.store.record(
            request_id=request_id, profile_id=profile_id, video_id=video_id,
            verdict=verdict["verdict"], confidence=verdict["confidence"], rank=verdict["rank"],
            category=verdict["category"], summary=verdict["summary"], reason=verdict["reason"],
            mode=self.mode, outcome=outcome, latency_ms=latency_ms, raw=verdict,
        )
        if not recorded:
            return {"status": "duplicate", "request_id": request_id}
        logger.info(
            "Triage verdict %s: %s/%s outcome=%s latency=%sms",
            request_id, verdict["verdict"], verdict["rank"], outcome, latency_ms,
        )
        return {"status": "ok", "request_id": request_id, "outcome": outcome}

    async def _send_reply(self, pending: _Pending, text: str) -> bool:
        sender = getattr(self.bot, "send_triage_reply", None)
        if sender is None:
            return False
        try:
            return bool(await sender(pending.chat_id, pending.message_id, text))
        except Exception as exc:
            logger.warning("Triage reply failed: %s", exc)
            return False

    def _schedule_timeout(self, request_id: str, pending: "_Pending") -> None:
        """Record a timeout at the deadline, without waiting for another request."""
        timer = asyncio.create_task(self._expire_after(request_id, pending))
        pending.timer = timer
        self._timers.add(timer)
        timer.add_done_callback(self._timers.discard)

    async def _expire_after(self, request_id: str, pending: "_Pending") -> None:
        """Sleep until this request's deadline, then record the timeout.

        Identity check, not equality on ``request_id``: a newer notification for
        the same video replaces the map entry and owns its own timer.
        """
        delay = max(0.0, pending.deadline - time.monotonic()) + TIMEOUT_GRACE_S
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        if self._pending.get(request_id) is not pending:
            return
        self._pending.pop(request_id, None)
        profile_id, _, video_id = request_id.partition(":")
        try:
            self.store.record(
                request_id=request_id, profile_id=profile_id, video_id=video_id,
                verdict="none", mode=self.mode, outcome="timeout",
            )
            logger.info("Triage timeout recorded for %s", request_id)
        except Exception as exc:
            logger.debug("Triage timeout record failed for %s: %s", request_id, exc)
