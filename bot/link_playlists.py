"""Telegram link approval and native playlist commands."""

from telegram import Update
from telegram.ext import ContextTypes

from bot.helpers import _md, MD2
from youtube.extractor import extract_video_ids


class LinkPlaylistMixin:
    """Bot commands for direct video links and native playlists."""

    @staticmethod
    def _split_link_args(args: list[str], default_category: str) -> tuple[str, str]:
        """Split command args into a raw link payload and trailing category."""
        category = default_category
        link_args = list(args)
        if link_args and link_args[-1].lower() in ("edu", "fun"):
            category = link_args.pop().lower()
        return " ".join(link_args).strip(), category

    def _store_approved_video_for_child(self, cs, metadata: dict, category: str) -> dict:
        """Store extracted metadata as an approved child video."""
        cs.add_video(
            video_id=metadata["video_id"],
            title=metadata["title"],
            channel_name=metadata["channel_name"],
            thumbnail_url=metadata.get("thumbnail_url"),
            duration=metadata.get("duration"),
            channel_id=metadata.get("channel_id"),
            is_short=metadata.get("is_short", False),
            yt_view_count=metadata.get("view_count"),
        )
        cs.update_status(metadata["video_id"], "approved")
        cs.set_video_category(metadata["video_id"], category)
        return cs.get_video(metadata["video_id"])

    async def _approve_video_for_child(self, cs, video_id: str, category: str,
                                       notify_change: bool = True) -> dict | None:
        """Fetch metadata, upsert the video, and mark it approved for one child."""
        metadata = await self._extract_video_metadata(video_id)
        if not metadata:
            return None
        video = self._store_approved_video_for_child(cs, metadata, category)
        if notify_change and self.on_video_change:
            self.on_video_change()
        return video

    async def _approve_link_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                    raw: str, category: str = "fun") -> bool:
        """Approve one YouTube link/ID through child selection flow."""
        video_ids = extract_video_ids(raw.strip())
        if not video_ids:
            return False
        if len(video_ids) > 1:
            await update.effective_message.reply_text(
                self.tr("Please send one YouTube video link at a time.")
            )
            return True
        video_id = video_ids[0]

        async def _inner(update, context, cs, profile):
            video = await self._approve_video_for_child(cs, video_id, category)
            if not video:
                await update.effective_message.reply_text(
                    self.tr("Couldn't fetch that YouTube video. Try again in a moment.")
                )
                return

            await update.effective_message.reply_text(
                self.tr(
                    "Approved: {title}\nCategory: {category}\nChild link: {url}",
                    title=video["title"],
                    category=self.cat_label(category),
                    url=self.child_url(f"/watch/{video_id}"),
                )
            )

        await self._with_child_context(update, context, _inner)
        return True

    async def _cmd_addlink(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Approve a single YouTube link or video ID for a child."""
        if not await self._require_admin(update):
            return
        args = context.args or []
        if not args:
            await update.effective_message.reply_text(
                self.tr("Usage: /addlink <YouTube URL or ID> [edu|fun]")
            )
            return

        raw, category = self._split_link_args(args, "fun")
        if not raw:
            await update.effective_message.reply_text(
                self.tr("Usage: /addlink <YouTube URL or ID> [edu|fun]")
            )
            return
        if not await self._approve_link_request(update, context, raw, category=category):
            await update.effective_message.reply_text(
                self.tr("Please send a valid YouTube video URL or video ID.")
            )

    async def _cmd_playlist(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Manage native playlists for a child."""
        if not await self._require_admin(update):
            return

        async def _inner(update, context, cs, profile):
            args = context.args or []
            if not args:
                await self._playlist_list(update, cs)
                return

            sub = args[0].lower()
            if sub == "create":
                await self._playlist_create(update, cs, args[1:])
                return
            if sub == "delete":
                await self._playlist_delete(update, cs, args[1:])
                return
            if sub == "add":
                await self._playlist_add(update, cs, args[1:])
                return

            await update.effective_message.reply_text(
                self.tr("Usage: /playlist [create|add|delete] ...")
            )

        await self._with_child_context(update, context, _inner)

    async def _playlist_list(self, update: Update, cs) -> None:
        """Reply with all playlists for the selected child."""
        playlists = cs.get_playlists()
        if not playlists:
            await update.effective_message.reply_text(
                self.tr("No playlists yet. Use /playlist create <name> to start one.")
            )
            return
        lines = [f"**{self.tr('Playlists')}**", ""]
        for playlist in playlists:
            lines.append(
                self.tr(
                    "{id}. {name} ({count} videos)\n{url}",
                    id=playlist["id"],
                    name=playlist["name"],
                    count=playlist.get("item_count", 0),
                    url=self.child_url(f"/playlists/{playlist['id']}"),
                )
            )
        await update.effective_message.reply_text(_md("\n".join(lines)), parse_mode=MD2)

    async def _playlist_create(self, update: Update, cs, args: list[str]) -> None:
        """Create an empty native playlist."""
        name = " ".join(args).strip()
        if not name:
            await update.effective_message.reply_text(self.tr("Usage: /playlist create <name>"))
            return
        playlist = cs.create_playlist(name)
        await update.effective_message.reply_text(
            self.tr(
                "Created playlist {id}: {name}\nChild link: {url}",
                id=playlist["id"],
                name=playlist["name"],
                url=self.child_url(f"/playlists/{playlist['id']}"),
            )
        )

    async def _playlist_delete(self, update: Update, cs, args: list[str]) -> None:
        """Delete a native playlist."""
        if len(args) < 1 or not args[0].isdigit():
            await update.effective_message.reply_text(self.tr("Usage: /playlist delete <playlist_id>"))
            return
        playlist_id = int(args[0])
        if not cs.delete_playlist(playlist_id):
            await update.effective_message.reply_text(self.tr("Playlist not found."))
            return
        await update.effective_message.reply_text(self.tr("Deleted playlist {id}.", id=playlist_id))

    async def _playlist_add(self, update: Update, cs, args: list[str]) -> None:
        """Approve one video and append it to a native playlist."""
        if len(args) < 2 or not args[0].isdigit():
            await update.effective_message.reply_text(
                self.tr("Usage: /playlist add <playlist_id> <YouTube URL or ID> [edu|fun]")
            )
            return
        playlist_id = int(args[0])
        playlist = cs.get_playlist(playlist_id)
        if not playlist:
            await update.effective_message.reply_text(self.tr("Playlist not found."))
            return

        raw, category = self._split_link_args(args[1:], playlist.get("category") or "fun")
        video_ids = extract_video_ids(raw)
        if not video_ids:
            await update.effective_message.reply_text(
                self.tr("Please send a valid YouTube video URL or video ID.")
            )
            return
        if len(video_ids) > 1:
            await update.effective_message.reply_text(
                self.tr("Please send one YouTube video link at a time.")
            )
            return
        video_id = video_ids[0]
        video = await self._approve_video_for_child(cs, video_id, category)
        if not video:
            await update.effective_message.reply_text(
                self.tr("Couldn't fetch that YouTube video. Try again in a moment.")
            )
            return
        cs.add_playlist_item(playlist_id, video)
        await update.effective_message.reply_text(
            self.tr(
                "Added to playlist {id}: {title}\nPlaylist: {playlist_url}\nVideo: {watch_url}",
                id=playlist_id,
                title=video["title"],
                playlist_url=self.child_url(f"/playlists/{playlist_id}"),
                watch_url=self.child_url(f"/watch/{video['video_id']}"),
            )
        )

    async def _cmd_importplaylist(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Import a YouTube playlist into a native BRG playlist."""
        if not await self._require_admin(update):
            return

        async def _inner(update, context, cs, profile):
            args = context.args or []
            if not args:
                await update.effective_message.reply_text(
                    self.tr("Usage: /importplaylist <playlist_url> [edu|fun]")
                )
                return

            category = "edu"
            if len(args) > 1 and args[1].lower() in ("edu", "fun"):
                category = args[1].lower()

            playlist_data = await self._extract_playlist_metadata(args[0])
            if not playlist_data:
                await update.effective_message.reply_text(
                    self.tr("Couldn't fetch that YouTube playlist. Check the URL and try again.")
                )
                return

            playlist = cs.create_playlist(
                playlist_data["title"],
                source_url=playlist_data.get("source_url", args[0]),
                source_playlist_id=playlist_data.get("playlist_id", ""),
                category=category,
            )

            for entry in playlist_data.get("entries", []):
                video = self._store_approved_video_for_child(cs, entry, category)
                cs.add_playlist_item(playlist["id"], video)

            if self.on_video_change:
                self.on_video_change()

            skipped_count = playlist_data.get("skipped_count", 0)
            skipped_line = ""
            if skipped_count:
                skipped_line = f"\n{self.tr('Skipped: {count}', count=skipped_count)}"
            await update.effective_message.reply_text(
                self.tr(
                    "Imported playlist {id}: {title} ({count} videos){skipped}\nChild link: {url}",
                    id=playlist["id"],
                    title=playlist["name"],
                    count=len(playlist_data.get("entries", [])),
                    skipped=skipped_line,
                    url=self.child_url(f"/playlists/{playlist['id']}"),
                )
            )

        await self._with_child_context(update, context, _inner)
