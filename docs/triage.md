# Triage bridge (optional)

Sends each new video request to an external triage agent (Hermes by default).
With `hold_notification` (the default) the parent notification waits until the
verdict arrives or `hold_timeout_s` (default 240s) expires, then the
notification and the summary reply go out together. `mode: shadow` never
changes a video's status. `mode: auto` applies a confident allow or deny and
keeps a one-tap override on the same message.

`mode: shadow` is the one-line rollback: set it and restart. No deploy is
required, and a held notification still goes out.

## Flow

```
kid requests a video
  -> BRG commits the pending row
  -> if triage is off, or hold_notification is false:
       notification sent now (buttons live)               [message_id kept]
       background POST of the request context (HMAC)
       later reply threaded under that notification
  -> if hold_notification is true:
       notification is NOT sent yet; a triage_holds row is written
       background POST of the request context (HMAC)
       on verdict: send notification, then the summary reply
       on hold_timeout_s: send the notification alone
       on push failure: send the notification immediately
```

Requests are pushed, not polled: Telegram's Bot API does not deliver messages
authored by another bot, so an agent bot cannot "watch" the request chat.

## Configuration

YAML (`config.yaml`):

```yaml
triage:
  enabled: true
  mode: shadow                # "shadow" (advice only) or "auto"
  url: http://dug.lan:8644/p/brgtriage/webhooks/brg-request
  secret: ${BRG_TRIAGE_SECRET}
  callback_secret: ${BRG_TRIAGE_CALLBACK_SECRET}
  deadline_s: 60              # reply-only path: skip the reply after this
  reply_enabled: true
  hold_notification: true     # bundle notification + verdict
  hold_timeout_s: 240
  auto_min_confidence: 0.85
  auto_approve: true
  auto_deny: true
```

Environment: `BRG_TRIAGE_ENABLED`, `BRG_TRIAGE_MODE`, `BRG_TRIAGE_URL`,
`BRG_TRIAGE_SECRET`, `BRG_TRIAGE_CALLBACK_SECRET`, `BRG_TRIAGE_DEADLINE_S`,
`BRG_TRIAGE_REPLY_ENABLED`, `BRG_TRIAGE_HOLD_NOTIFICATION`,
`BRG_TRIAGE_HOLD_TIMEOUT_S`, `BRG_TRIAGE_AUTO_MIN_CONFIDENCE`,
`BRG_TRIAGE_AUTO_APPROVE`, `BRG_TRIAGE_AUTO_DENY`.

Startup refuses to enable the bridge when `url`, `secret` or `callback_secret`
is missing. A mode other than `shadow` or `auto` is forced back to `shadow`.
A warning is logged when `hold_timeout_s` is below `deadline_s`, because the
verdict would not arrive before the hold releases.

## Hold

`triage_holds` stores the video payload for each in-flight notification. A
restart releases rows older than `hold_timeout_s` at once and re-arms the
rest, so a request is not swallowed and a row that was already released is
not sent twice. The child's request path never waits on this and never sees
an exception from it: any failure sends the notification immediately
(`outcome = push_failed`).

`hold_notification: false` is today's behaviour: send first, reply later.
That path still records `timeout` at `deadline_s`. The hold path records
`hold_released` or `hold_timeout` instead.

## Auto-apply

When `mode` is `auto`, a verdict is applied only if all of these hold:

- verdict is `allow` or `deny` (never `uncertain`)
- rank is `HIGH` and `confidence >= auto_min_confidence` (default 0.85)
- the video is still `pending`
- `word_filter_hits` is empty
- the matching switch is on (`auto_approve` / `auto_deny`)

A deny is applied when the verdict is deny. An allow uses the verdict
category, then the channel category, then `fun`. The notification is a
receipt: a header states the automatic decision, the summary follows, and
the keyboard is the override. Revoke on an automatic approval sets the video
to `denied` (revoke means "not approved", not "back to waiting"). An
automatic denial offers `undeny:<profile>:<video>:edu` and `:fun`, which
approve with that category. Either override stamps `overridden_at`.
`applied` is `auto_approved`, `auto_denied`, or empty.

`mode: shadow` writes no status.

## What the child sees

The waiting page and `/requests` may show a neutral line and the summary:
"Reviewed: looks fine" for allow, "Reviewed: a parent is deciding" otherwise.
They never show `reason`, confidence, rank, or the words "flagged" / "denied".
Outcomes `timeout`, `hold_timeout` and `late` show no summary. `/requests`
lists denied videos as "Not approved". A child only sees rows for their own
profile.

### Addresses

The reviewer runs on this same host (Hermes profile `brgtriage`), but address it
by `dug.lan`, never `localhost` or `127.0.0.1`: inside the container, loopback is
the container, so a loopback URL reaches nothing. `dug.lan` resolves through the
router's DNS to the host address the webhook listener is bound to. Confirm from
inside the container before enabling:

```bash
podman exec brainrotguard getent hosts dug.lan
```

## Enrichment (agent side)

The agent fetches the video's metadata **and its captions** before judging:
`yt-dlp -J` for description/tags/chapters, then a caption scan that returns exact
profanity counts (strong/mild, with context) and a bounded transcript excerpt.
A title alone cannot tell a science demonstration from actual harm, and the parent
is reading the title in a hurry — that is the agent's job. When no caption track
exists the verdict is still produced but `enrichment.transcript` is `false`, so the
parent can tell "checked" from "could not check".

## Wire contract

Outbound body (JSON, signed): the deterministic context only — `request_id`
(`profile_id:video_id`), title, channel name/id, duration, `is_short`,
`requested_at`, child profile, `channel_state` (`allowed`/`blocked`/`none`),
`channel_category`, `channel_history` (counts + recent decisions),
`previously_approved_for_other_child`, `denied_before`, `word_filter_hits`,
`taste` (recent approved titles).

Signature: `X-Webhook-Timestamp` + `X-Webhook-Signature-V2` = hex HMAC-SHA256 of
`<timestamp>.<raw body>`, which is what Hermes' webhook platform verifies.
`X-Request-ID` carries the `request_id` for dedupe.

Verdict body (`POST /internal/triage/{request_id}`):

```json
{
  "request_id": "default:dQw4w9WgXcQ",
  "verdict": "allow | uncertain | deny",
  "confidence": 0.0,
  "rank": "HIGH | MEDIUM | LOW",
  "category": "edu | fun | null",
  "summary": "2-3 sentences on what the video actually is",
  "reason": "one line on why"
}
```

Signed with `X-BRG-Timestamp` + `X-BRG-Signature` (same scheme, callback
secret). `rank` is **ignored if present** — the server always derives it from
`confidence` (`HIGH ≥ 0.85`, `MEDIUM ≥ 0.60`, else `LOW`), so an overconfident
model cannot mint the label phase 2 gates on. `summary` is required; everything
else is validated and malformed payloads are refused with 400.

## Failure behaviour

| Situation | Result |
|-----------|--------|
| Bridge disabled (default) | Endpoint 404, nothing is sent |
| Hermes unreachable / 5xx | Hold path: notification sent immediately, `outcome = push_failed`. Reply-only path: warning logged; notification already stands alone |
| Verdict after `deadline_s` (reply-only) | Recorded as `late`; no reply |
| Verdict never arrives (reply-only) | Recorded as `timeout` at `deadline_s` + ~2s, without waiting for another request |
| Verdict inside the hold window | One notification, then one reply; `outcome = hold_released` |
| Hold expires with no verdict | One notification; `outcome = hold_timeout` |
| Restart during a hold | Younger holds are re-armed; older ones are released once |
| Request already decided by a human | Recorded as `skipped_decided`; no reply. A held notification is still sent |
| Duplicate verdict | `{"status": "duplicate"}`, original row untouched |
| Video re-requested after a decision | No second push (it would only be dropped as a duplicate) |
| Bad signature / stale timestamp | 401, nothing recorded |
| Body over 16 KiB | 413, nothing recorded |
| Reply target deleted | Reply is retried unthreaded, then logged as failure |
| Process restart between push and verdict (reply-only, no hold row) | Verdict recorded as `unknown_request`; no reply (that pending map is in-memory) |

## Storage and measurement

Every verdict lands in `triage_decisions` in the same SQLite file as the videos
(`request_id` is the primary key). `outcome` distinguishes `replied`, `logged`,
`skipped_decided`, `late`, `unknown_request`, `timeout`, `hold_released`,
`hold_timeout` and `push_failed`. `applied` is `auto_approved`, `auto_denied`
or empty, and `overridden_at` is set when a parent reverses an automatic
decision. `latency_ms` records how long the verdict took. `triage_holds` is
only the in-flight notification window and is deleted on release.

## Security notes

- `/internal/triage/` is exempt from the PIN middleware *because* the callback
  authenticates with HMAC. Keep the exemption narrow: any new unauthenticated
  endpoint needs its own authentication, not a wider prefix.
- Both secrets are per-installation; rotate by updating both sides together.
- In `shadow`, a verdict cannot change a video's status. In `auto`, only the
  rules above can, and every automatic decision has an override button.
  Allowlist, blocklist and word filters still run before triage is asked.

## Manual check

```bash
TS=$(date +%s); BODY='{"request_id":"default:test","verdict":"uncertain","confidence":0.5,"summary":"Manual test"}'
SIG=$(printf '%s' "$TS.$BODY" | openssl dgst -sha256 -hmac "$BRG_TRIAGE_CALLBACK_SECRET" -r | cut -d' ' -f1)
curl -sS -X POST "http://localhost:8080/internal/triage/default:test" \
  -H 'Content-Type: application/json' -H "X-BRG-Timestamp: $TS" -H "X-BRG-Signature: $SIG" \
  --data-binary "$BODY"
```
