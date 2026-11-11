# Triage bridge (optional)

Sends each new video request to an external triage agent (Hermes by default) and
renders its verdict as a threaded reply under the request notification.

**Phase 1 is describe-only.** The bridge never approves, denies, or otherwise
changes a video's status. The approval buttons keep working exactly as they do
without it, and the notification itself is unchanged.

## Flow

```
kid requests a video
  -> BRG commits the pending row
  -> notification sent now, unchanged (buttons live)      [message_id kept]
  -> background POST of the request context (HMAC)         -> Hermes webhook route
  <- POST /internal/triage/{request_id} with a verdict     <- triage agent
  -> reply threaded under the notification (shadow wording, no action)
```

Requests are pushed, not polled: Telegram's Bot API does not deliver messages
authored by another bot, so an agent bot cannot "watch" the request chat.

## Configuration

YAML (`config.yaml`):

```yaml
triage:
  enabled: true
  mode: shadow                # only "shadow" is implemented
  url: http://dug.lan:8644/p/brgtriage/webhooks/brg-request
  secret: ${BRG_TRIAGE_SECRET}
  callback_secret: ${BRG_TRIAGE_CALLBACK_SECRET}
  deadline_s: 60
  reply_enabled: true
```

Environment: `BRG_TRIAGE_ENABLED`, `BRG_TRIAGE_MODE`, `BRG_TRIAGE_URL`,
`BRG_TRIAGE_SECRET`, `BRG_TRIAGE_CALLBACK_SECRET`, `BRG_TRIAGE_DEADLINE_S`,
`BRG_TRIAGE_REPLY_ENABLED`.

Startup refuses to enable the bridge when `url`, `secret` or `callback_secret`
is missing, and logs a warning if `mode` is anything other than `shadow`.

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
| Hermes unreachable / 5xx | Warning logged; notification stands alone |
| Verdict after `deadline_s` | Recorded as `late`; no reply |
| Verdict never arrives | Recorded as `timeout` at `deadline_s` + ~2s, without waiting for another request |
| Request already decided by a human | Recorded as `skipped_decided`; no reply |
| Duplicate verdict | `{"status": "duplicate"}`, original row untouched |
| Video re-requested after a decision | No second push (it would only be dropped as a duplicate) |
| Bad signature / stale timestamp | 401, nothing recorded |
| Body over 16 KiB | 413, nothing recorded |
| Reply target deleted | Reply is retried unthreaded, then logged as failure |
| Process restart between push and verdict | Verdict recorded as `unknown_request`; no reply (the pending map is in-memory) |

## Storage and measurement

Every verdict lands in `triage_decisions` in the same SQLite file as the videos
(`request_id` is the primary key). `outcome` distinguishes `replied`, `logged`,
`skipped_decided`, `late`, `unknown_request` and `timeout`, and `latency_ms`
records how long the verdict took. Joined against the video's final status this
is the data that decides whether phase 2 (auto-apply) is ever enabled.

## Security notes

- `/internal/triage/` is exempt from the PIN middleware *because* the callback
  authenticates with HMAC. Keep the exemption narrow: any new unauthenticated
  endpoint needs its own authentication, not a wider prefix.
- Both secrets are per-installation; rotate by updating both sides together.
- A verdict is data, not authority: in phase 1 nothing in the reply path can
  change a video's status. Phase 2 must keep the deterministic rules
  (allowlist/blocklist/word filters) authoritative and add an override action
  for every automatic decision.

## Manual check

```bash
TS=$(date +%s); BODY='{"request_id":"default:test","verdict":"uncertain","confidence":0.5,"summary":"Manual test"}'
SIG=$(printf '%s' "$TS.$BODY" | openssl dgst -sha256 -hmac "$BRG_TRIAGE_CALLBACK_SECRET" -r | cut -d' ' -f1)
curl -sS -X POST "http://localhost:8080/internal/triage/default:test" \
  -H 'Content-Type: application/json' -H "X-BRG-Timestamp: $TS" -H "X-BRG-Signature: $SIG" \
  --data-binary "$BODY"
```
