# Troubleshooting

**The bot doesn't respond to commands**
- Make sure `BRG_BOT_TOKEN` is correct. You can verify by opening `https://api.telegram.org/botYOUR_TOKEN/getMe` in a browser — it should return your bot's info.
- Make sure `BRG_ADMIN_CHAT_ID` is correct. If you're using a parent group, that should be the group chat ID.
- If you use direct messages with multiple parents, set `BRG_ADMIN_USER_IDS` to the parents' numeric Telegram user IDs.
- Listed admins are accepted in direct messages and in the configured admin chat, but not in unrelated groups.

**Videos won't play on the tablet**
- If you set up DNS blocking, make sure `www.youtube.com` and `*.googlevideo.com` are allowlisted. These domains serve the actual video content.
- If you see "Sign in to confirm you're not a bot", sign into a Google account on the tablet's browser at `youtube.com`. The embed shares that session.
- Check the browser console for errors — some ad blockers interfere with embedded video playback.

**"Connection refused" when opening the web UI**
- Confirm the container is running: `docker compose ps`
- Check logs for errors: `docker compose logs`
- Make sure port 8080 isn't blocked by a firewall on the host machine.

**Search returns no results**
- yt-dlp may need updating. Rebuild the container: `docker compose up -d --build`
- YouTube occasionally changes their site, which temporarily breaks yt-dlp until they release an update.

**`/importplaylist` fails or imports fewer videos than expected**
- Confirm the URL is a real YouTube playlist URL with a `list=` parameter.
- Private or deleted playlist entries are skipped during import.
- If the bot reports skipped entries, those items were private, deleted, or did not resolve to valid YouTube video IDs.
- If yt-dlp can't read the playlist, rebuild the container to refresh yt-dlp.

**A QR code opens the login page instead of the video**
- That's expected when the child is not logged in yet. BrainRotGuard preserves the target and returns to the requested `/watch/...` or `/playlists/...` URL after a successful login.
- If it still drops the child at the homepage, verify you're on a current build with deep-link login support.
- If Telegram replies show relative links like `/watch/...` instead of full URLs, set `BRG_BASE_URL` to the LAN address the child device can open.

**The kid's tablet can still reach youtube.com**
- DNS changes can take a few minutes to propagate. Try clearing the tablet's DNS cache or restarting its WiFi.
- Make sure the DNS blocker is applied to the right device/network.
