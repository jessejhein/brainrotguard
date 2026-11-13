"""Triage bridge service: push a request context, accept a verdict, reply.

Phase 1 behaviour (the only implemented mode): the notification goes out exactly
as before, the summary arrives afterwards as a threaded reply, and the video's
status is never touched. A missing, late, malformed, duplicate or unsigned
verdict degrades to "no reply" — never to an approval.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone

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
# How long a sent notification is remembered so a late verdict can thread under it.
RELEASED_TTL_S = 1800
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


def render_reply(verdict: dict, *, applied: str = "", mode: str = "shadow") -> str:
    """Render the parent-facing reply: what it is, what we suggest, why."""
    label = {"allow": "ALLOW", "uncertain": "UNCERTAIN", "deny": "DENY"}[verdict["verdict"]]
    if applied == "auto_approved":
        head = "\U0001F9E0 Triage (auto-approved)"
    elif applied == "auto_denied":
        head = "\U0001F9E0 Triage (auto-denied)"
    elif mode == "auto":
        head = "\U0001F9E0 Triage (auto \u2014 no action)"
    else:
        head = "\U0001F9E0 Triage (shadow \u2014 no action)"
    lines = [
        head,
        f"What it is: {verdict['summary']}",
        f"Recommendation: {label} \u00b7 confidence {verdict['rank']} ({verdict['confidence']:.2f})",
    ]
    if verdict.get("reason"):
        lines.append(f"Why: {verdict['reason']}")
    text = "\n".join(lines)
    return text if len(text) <= MAX_REPLY else text[: MAX_REPLY - 1] + "\u2026"


class _Pending:
    __slots__ = (
        "chat_id", "message_id", "deadline", "started", "timer",
        "video", "profile_id", "released", "holding",
    )

    def __init__(self, chat_id, message_id, deadline, started, *,
                 video=None, profile_id="", holding=False):
        self.chat_id = chat_id
        self.message_id = message_id
        self.deadline = deadline
        self.started = started
        self.timer: asyncio.Task | None = None
        self.video = video
        self.profile_id = profile_id
        self.released = False
        self.holding = holding


class _Released:
    """Where an already-sent notification landed, so a late verdict can thread under it."""

    __slots__ = ("chat_id", "message_id", "expires_at")

    def __init__(self, chat_id, message_id, expires_at):
        self.chat_id = chat_id
        self.message_id = message_id
        self.expires_at = expires_at


class TriageService:
    """Owns the outbound push, the pending map and the reply rendering."""

    def __init__(self, config, video_store, store, bot=None, *, poster=None):
        self.config = config
        self.video_store = video_store
        self.store = store
        self.bot = bot
        self._poster = poster
        self._pending: dict[str, _Pending] = {}
        # Sent notifications, kept for a while so a verdict that arrives after the
        # hold released can still be posted as a threaded reply.
        self._released: dict[str, _Released] = {}
        self._tasks: set[asyncio.Task] = set()
        # Deadline timers live apart from `_tasks` (the in-flight pushes) so a
        # caller draining `_tasks` is never blocked by a pending deadline.
        self._timers: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config, "enabled", False))

    @property
    def mode(self) -> str:
        mode = str(getattr(self.config, "mode", "shadow") or "shadow").strip().lower()
        return mode if mode in ("shadow", "auto") else "shadow"

    def _holding_enabled(self, ref) -> bool:
        """Hold only when configured and the caller has not already notified."""
        return bool(getattr(self.config, "hold_notification", False)) and ref is None

    async def on_request(self, video: dict, profile_id: str, ref=None) -> None:
        """Push context for a new request. Never raises into the request path.

        When the caller passes a NotifyRef, the notification is already in the
        chat and this only posts a later reply (``hold_notification: false``).
        When ``ref`` is None and holding is on, the notification stays unsent
        until a verdict or the hold timeout, and a failed push sends it now.
        """
        if not self.enabled:
            return
        holding = self._holding_enabled(ref)
        request_id = ""
        try:
            request_id = f"{profile_id}:{video['video_id']}"
            existing = self.store.get(request_id)
            if existing and existing.get("verdict") in VERDICTS:
                # Already triaged (the parent re-requested an existing video, or
                # tapped Resend). A second verdict would be dropped as a duplicate,
                # so don't spend an agent run on it.
                logger.info("Triage skipped for %s: already has a decision", request_id)
                if holding:
                    await self._notify_now(video, profile_id)
                return
            if existing:
                # push_failed (and any other row with no verdict) must not block
                # a later request from reaching the agent.
                logger.info("Triage retrying %s after outcome=%s", request_id, existing.get("outcome"))
                self.store.delete(request_id)
            context = build_request_context(self.video_store, video, profile_id)
        except Exception as exc:  # context building must never break a request
            logger.error("Triage context build failed for %s: %s", profile_id, exc)
            if holding:
                await self._notify_now(video, profile_id)
            return

        if holding:
            if not self._arm_hold(request_id, video, profile_id):
                await self._notify_now(video, profile_id)
                return
        elif ref is not None:
            now = time.monotonic()
            pending = _Pending(
                getattr(ref, "chat_id", None),
                getattr(ref, "message_id", None),
                now + max(1, int(self.config.deadline_s or 60)),
                now,
                video=video,
                profile_id=profile_id,
                holding=False,
            )
            self._pending[request_id] = pending
            self._schedule_timeout(request_id, pending)

        task = asyncio.create_task(self._post_then_failopen(context, request_id if holding else None))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _arm_hold(self, request_id: str, video: dict, profile_id: str) -> bool:
        """Register an in-memory hold and its durable row. False means fail-open."""
        try:
            now = time.monotonic()
            timeout_s = max(1, int(getattr(self.config, "hold_timeout_s", 240) or 240))
            pending = _Pending(
                None, None, now + timeout_s, now,
                video=video, profile_id=profile_id, holding=True,
            )
            self.store.save_hold(request_id, profile_id, video["video_id"], video)
            self._pending[request_id] = pending
            self._schedule_timeout(request_id, pending)
            return True
        except Exception as exc:
            logger.error("Triage hold failed to register for %s: %s", request_id, exc)
            self._pending.pop(request_id, None)
            return False

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

    async def _post_then_failopen(self, context: dict, held_request_id: str | None) -> bool:
        """Push, and if a held notification cannot be triaged, send it now."""
        ok = await self._post(context)
        if held_request_id and not ok:
            pending = self._pending.get(held_request_id)
            if pending is not None and pending.holding and not pending.released:
                logger.warning("Triage push failed for %s; releasing notification", held_request_id)
                await self._release(held_request_id, verdict=None)
                self._record_outcome_if_absent(held_request_id, "push_failed")
        return ok

    async def handle_verdict(self, request_id: str, payload: object) -> dict:
        """Validate, persist and (when still useful) post the threaded reply."""
        verdict = normalise_verdict(payload)
        if verdict["request_id"] != request_id:
            raise VerdictError("request_id does not match the URL")

        existing = self.store.get(request_id)
        if existing and existing.get("verdict") in VERDICTS:
            return {"status": "duplicate", "request_id": request_id}
        if existing:
            # A row with no verdict (timeout, hold_timeout, push_failed) must not
            # swallow a review that arrives later: clear it, record the real one.
            logger.info("Triage late verdict for %s (was %s)", request_id, existing.get("outcome"))
            self.store.delete(request_id)

        profile_id, _, video_id = request_id.partition(":")
        pending = self._pending.get(request_id)
        if pending is not None and pending.timer is not None:
            pending.timer.cancel()
        now = time.monotonic()
        latency_ms = int((now - pending.started) * 1000) if pending else None

        applied = ""
        if pending is not None and pending.holding and not pending.released:
            row = self.video_store.get_video(video_id, profile_id)
            if not row or row.get("status") != "pending":
                outcome = "skipped_decided"
                await self._release(request_id, verdict=None)
                # The parent already decided: the notification still goes out, and
                # the review follows under it so it is not silently lost.
                if await self._reply_late(request_id, verdict, "already decided by a parent"):
                    outcome = "decided_reply"
            else:
                applied = self._auto_decision(verdict, row, profile_id, video_id)
                receipt = None
                if applied:
                    receipt = {"applied": applied, "summary": verdict["summary"],
                               "category": verdict.get("category")}
                await self._release(request_id, verdict, receipt=receipt, applied=applied)
                outcome = "hold_released"
        elif pending is None:
            outcome = "late_reply" if await self._reply_late(
                request_id, verdict, "the request message had already gone out") else "unknown_request"
        elif now > pending.deadline:
            self._pending.pop(request_id, None)
            if pending.message_id is not None and await self._reply_late(
                    request_id, verdict, "the request message had already gone out"):
                outcome = "late_reply"
            else:
                outcome = "late"
        else:
            self._pending.pop(request_id, None)
            row = self.video_store.get_video(video_id, profile_id)
            if not row or row.get("status") != "pending":
                outcome = "skipped_decided"
            else:
                applied = self._auto_decision(verdict, row, profile_id, video_id)
                if not self.config.reply_enabled or pending.message_id is None or self.bot is None:
                    outcome = "logged"
                else:
                    sent = await self._send_reply(
                        pending, render_reply(verdict, applied=applied, mode=self.mode))
                    outcome = "replied" if sent else "logged"

        recorded = self.store.record(
            request_id=request_id, profile_id=profile_id, video_id=video_id,
            verdict=verdict["verdict"], confidence=verdict["confidence"], rank=verdict["rank"],
            category=verdict["category"], summary=verdict["summary"], reason=verdict["reason"],
            mode=self.mode, outcome=outcome, latency_ms=latency_ms, raw=verdict,
            applied=applied,
        )
        if not recorded:
            return {"status": "duplicate", "request_id": request_id}
        logger.info(
            "Triage verdict %s: %s/%s outcome=%s latency=%sms",
            request_id, verdict["verdict"], verdict["rank"], outcome, latency_ms,
        )
        return {"status": "ok", "request_id": request_id, "outcome": outcome}

    async def _notify_now(self, video: dict | None, profile_id: str, receipt=None):
        """Send the parent notification. Returns a NotifyRef or None. Never raises."""
        if not video or self.bot is None:
            return None
        sender = getattr(self.bot, "notify_new_request", None)
        if sender is None:
            return None
        try:
            if receipt is not None:
                return await sender(video, profile_id=profile_id, receipt=receipt)
            return await sender(video, profile_id=profile_id)
        except TypeError:
            try:
                return await sender(video, profile_id=profile_id)
            except Exception as exc:
                logger.error("Triage notification failed: %s", exc)
                return None
        except Exception as exc:
            logger.error("Triage notification failed: %s", exc)
            return None

    def _word_hits(self, title: str) -> list[str]:
        try:
            filters = self.video_store.get_word_filters_set()
        except Exception:
            return []
        return sorted(
            word for word in filters
            if word and re.search(r"\b" + re.escape(word) + r"\b", title or "", re.IGNORECASE)
        )

    def _auto_decision(self, verdict: dict, row: dict, profile_id: str, video_id: str) -> str:
        """Return ``auto_approved`` / ``auto_denied`` or ``''``. Never raises."""
        try:
            if self.mode != "auto":
                return ""
            kind = verdict.get("verdict")
            if kind not in ("allow", "deny") or verdict.get("rank") != "HIGH":
                return ""
            minimum = float(getattr(self.config, "auto_min_confidence", 0.85) or 0.85)
            if float(verdict.get("confidence") or 0) < minimum:
                return ""
            if row.get("status") != "pending":
                return ""
            if self._word_hits(row.get("title") or ""):
                return ""
            # One verdict has one direction. Deny is preferred when both switches
            # are on and the verdict itself is deny.
            if kind == "deny":
                if not getattr(self.config, "auto_deny", True):
                    return ""
                self.video_store.update_status(video_id, "denied", profile_id=profile_id)
                return "auto_denied"
            if not getattr(self.config, "auto_approve", True):
                return ""
            category = verdict.get("category")
            if category not in ("edu", "fun"):
                category = self.video_store.get_channel_category(
                    row.get("channel_name") or "", profile_id=profile_id)
            if category not in ("edu", "fun"):
                category = "fun"
            self.video_store.update_status(video_id, "approved", profile_id=profile_id)
            self.video_store.set_video_category(video_id, category, profile_id=profile_id)
            return "auto_approved"
        except Exception as exc:
            logger.error("Triage auto-apply failed for %s: %s", video_id, exc)
            return ""

    async def _release(self, request_id: str, verdict: dict | None = None, receipt=None, applied: str = ""):
        """Send a held notification once, then the summary reply when we have one."""
        pending = self._pending.get(request_id)
        if pending is None or pending.released:
            return None
        pending.released = True
        if pending.timer is not None and pending.timer is not asyncio.current_task():
            pending.timer.cancel()
        self._pending.pop(request_id, None)
        try:
            self.store.delete_hold(request_id)
        except Exception as exc:
            logger.debug("Triage hold delete failed for %s: %s", request_id, exc)
        ref = await self._notify_now(pending.video, pending.profile_id or "", receipt=receipt)
        if ref is not None:
            self._released[request_id] = _Released(
                getattr(ref, "chat_id", None), getattr(ref, "message_id", None),
                time.monotonic() + RELEASED_TTL_S,
            )
            self._prune_released()
        if (
            verdict is not None
            and ref is not None
            and getattr(self.config, "reply_enabled", True)
        ):
            target = _Pending(
                getattr(ref, "chat_id", None),
                getattr(ref, "message_id", None),
                pending.deadline,
                pending.started,
            )
            await self._send_reply(target, render_reply(verdict, applied=applied, mode=self.mode))
        return ref

    def _record_outcome_if_absent(self, request_id: str, outcome: str) -> None:
        if self.store.get(request_id):
            return
        profile_id, _, video_id = request_id.partition(":")
        try:
            self.store.record(
                request_id=request_id, profile_id=profile_id, video_id=video_id,
                verdict="none", mode=self.mode, outcome=outcome,
            )
            logger.info("Triage %s recorded for %s", outcome, request_id)
        except Exception as exc:
            logger.debug("Triage %s record failed for %s: %s", outcome, request_id, exc)

    async def restore_holds(self) -> None:
        """Deliver or re-arm holds left behind by a restart. Never raises."""
        try:
            holds = self.store.list_holds()
        except Exception as exc:
            logger.error("Triage hold restore failed: %s", exc)
            return
        timeout_s = max(1, int(getattr(self.config, "hold_timeout_s", 240) or 240))
        for hold in holds:
            request_id = hold["request_id"]
            try:
                if self.store.get(request_id) or request_id in self._pending:
                    # A decision or a live timer already owns this request.
                    if self.store.get(request_id):
                        self.store.delete_hold(request_id)
                    continue
                video = hold.get("video") or {}
                profile_id = hold.get("profile_id") or ""
                age = _hold_age_s(hold.get("created_at"))
                now = time.monotonic()
                if age >= timeout_s or not getattr(self.config, "hold_notification", False):
                    pending = _Pending(
                        None, None, now, now - age,
                        video=video, profile_id=profile_id, holding=True,
                    )
                    self._pending[request_id] = pending
                    await self._release(request_id, verdict=None)
                    self._record_outcome_if_absent(request_id, "hold_timeout")
                else:
                    pending = _Pending(
                        None, None, now + (timeout_s - age), now - age,
                        video=video, profile_id=profile_id, holding=True,
                    )
                    self._pending[request_id] = pending
                    self._schedule_timeout(request_id, pending)
            except Exception as exc:
                logger.error("Triage hold restore failed for %s: %s", request_id, exc)

    async def _reply_late(self, request_id: str, verdict: dict, note: str) -> bool:
        """Post a verdict under a notification that already went out. False if none."""
        released = self._released.pop(request_id, None)
        if released is None or released.message_id is None:
            return False
        if time.monotonic() > released.expires_at:
            return False
        if not getattr(self.config, "reply_enabled", True) or self.bot is None:
            return False
        text = f"{render_reply(verdict, mode=self.mode)}\n({note})"
        return await self._send_reply(released, text)

    def _prune_released(self) -> None:
        cutoff = time.monotonic()
        for key in [k for k, v in self._released.items() if v.expires_at < cutoff]:
            self._released.pop(key, None)

    async def _send_reply(self, pending: "_Pending | _Released", text: str) -> bool:
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
        if self._pending.get(request_id) is not pending or pending.released:
            return
        if pending.holding:
            await self._release(request_id, verdict=None)
            self._record_outcome_if_absent(request_id, "hold_timeout")
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


def _hold_age_s(created_at: str | None) -> float:
    """Age of a SQLite ``datetime('now')`` timestamp, in seconds."""
    if not created_at:
        return 0.0
    try:
        stamp = datetime.strptime(created_at[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())
