# QR Link Guide

Use BrainRotGuard's direct child links for QR codes, not the original YouTube
URL.

## Video Links

For a YouTube URL like:

```text
https://www.youtube.com/watch?v=mcj0iAwb910&t=3s
```

the part BrainRotGuard cares about is the video ID:

```text
mcj0iAwb910
```

The matching BrainRotGuard child link is:

```text
http://dug:8080/watch/mcj0iAwb910
```

If the child device cannot resolve `dug` on your LAN, use the server IP
instead, for example:

```text
http://192.168.1.50:8080/watch/mcj0iAwb910
```

The `t=3s` part from YouTube is not carried over. BrainRotGuard's direct watch
route only uses the video ID.

## Playlist Links

Playlist QR codes work the same way, but with the BrainRotGuard playlist ID:

```text
http://dug:8080/playlists/12
```

## Important Behavior

- The video usually needs to already exist in BrainRotGuard as approved content,
  or belong to an allowlisted channel that BrainRotGuard can auto-approve when
  `/watch/<video_id>` is opened.
- If the child is not logged in yet, the QR code may open the login page first.
  After login, BrainRotGuard returns to the requested `/watch/...` or
  `/playlists/...` URL.
- For QR workflows, `BRG_BASE_URL` should match a LAN address the child device
  can actually open.

## Practical Rule

To turn a YouTube watch link into a QR target:

1. Extract the `v=` video ID from the YouTube URL.
2. Build `http://YOUR-BRG-HOST:8080/watch/VIDEO_ID`.
3. Turn that final BrainRotGuard URL into a QR code with any QR generator.

For the example above, the QR target is:

```text
http://dug:8080/watch/mcj0iAwb910
```
