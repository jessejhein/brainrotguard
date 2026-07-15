# Playlist Deployment Follow-Up Weak Points

## Context

Review of the current branch against `main` for:

- `plans/20260714_link_qr_playlist_plan.md`
- `plans/20260715_playlist_import_deployment_readiness_remediation_plan.md`

found no deployment-blocking defects. The branch passes the full suite.

Two weak points remain that are worth fixing after the help i18n maintainability cleanup. They are documented here to avoid losing them and to keep deployment debt explicit.

## Verification State At Review

Commands run during review:

```bash
.venv/bin/python -m pytest tests/test_extractor_pure.py tests/test_bot_playlists.py tests/test_video_store.py tests/test_config.py -q
git diff --check 8a7f79f04d98ead7edfa8bbbe91b891b5b80022a...HEAD
.venv/bin/python -m pytest -q
```

Observed result:

- Targeted remediation tests: `159 passed`
- Full suite: `382 passed`
- Whitespace check: clean
- Warnings: third-party `slowapi` deprecation warnings only

## Weak Point 1: `/importplaylist` Silently Ignores Invalid Category Arguments

### Current Behavior

`bot/link_playlists.py` defaults playlist imports to `edu`:

```python
category = "edu"
if len(args) > 1 and args[1].lower() in ("edu", "fun"):
    category = args[1].lower()
```

This means:

```text
/importplaylist PLAYLIST_URL fud
/importplaylist PLAYLIST_URL fun extra
```

can proceed without a clear validation error. The first example imports as `edu`; the second imports as `fun` while ignoring `extra`.

### Why This Matters

The command imports and approves many videos at once. Silent argument mistakes are more expensive here than for a single-video command.

The current behavior is not a security bug because the admin must already be authorized, and the category still resolves to a known value. It is still a correctness and operator-experience issue.

### Recommended Fix

Reject unexpected category or extra arguments before fetching playlist metadata.

Required behavior:

- `/importplaylist URL` imports as `edu`.
- `/importplaylist URL edu` imports as `edu`.
- `/importplaylist URL fun` imports as `fun`.
- `/importplaylist URL fud` replies with `Usage: /importplaylist <playlist_url> [edu|fun]`.
- `/importplaylist URL fun extra` replies with `Usage: /importplaylist <playlist_url> [edu|fun]`.
- Invalid argument commands do not call `_extract_playlist_metadata`.
- Invalid argument commands do not create a playlist.
- Invalid argument commands do not add or approve videos.

Suggested implementation in `bot/link_playlists.py`:

```python
if len(args) > 2:
    await update.effective_message.reply_text(
        self.tr("Usage: /importplaylist <playlist_url> [edu|fun]")
    )
    return

category = "edu"
if len(args) == 2:
    if args[1].lower() not in ("edu", "fun"):
        await update.effective_message.reply_text(
            self.tr("Usage: /importplaylist <playlist_url> [edu|fun]")
        )
        return
    category = args[1].lower()
```

### Tests To Add

Update `tests/test_bot_playlists.py`.

Add:

```python
def test_importplaylist_rejects_invalid_category(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/importplaylist https://www.youtube.com/playlist?list=PL1234567890ABCDE fud")
        context = _DummyContext([
            "https://www.youtube.com/playlist?list=PL1234567890ABCDE",
            "fud",
        ])

        async def _fake_playlist_extract(url: str, max_items: int = 200):
            raise AssertionError("invalid category should be rejected before extraction")

        bot._extract_playlist_metadata = _fake_playlist_extract
        asyncio.run(bot._cmd_importplaylist(update, context))

        assert update.message.replies
        assert "Usage: /importplaylist" in update.message.replies[0][0]
        assert store.get_playlists(profile_id="default") == []
    finally:
        store.close()
```

Add:

```python
def test_importplaylist_rejects_extra_arguments(tmp_path):
    bot, store = _make_bot(tmp_path)
    try:
        update = _DummyUpdate("/importplaylist https://www.youtube.com/playlist?list=PL1234567890ABCDE fun extra")
        context = _DummyContext([
            "https://www.youtube.com/playlist?list=PL1234567890ABCDE",
            "fun",
            "extra",
        ])

        async def _fake_playlist_extract(url: str, max_items: int = 200):
            raise AssertionError("extra args should be rejected before extraction")

        bot._extract_playlist_metadata = _fake_playlist_extract
        asyncio.run(bot._cmd_importplaylist(update, context))

        assert update.message.replies
        assert "Usage: /importplaylist" in update.message.replies[0][0]
        assert store.get_playlists(profile_id="default") == []
    finally:
        store.close()
```

Targeted verification:

```bash
.venv/bin/python -m pytest tests/test_bot_playlists.py -q
```

## Weak Point 2: First-Profile Default Data Migration Does Not Include Playlists

### Current Behavior

`VideoStore.create_profile()` migrates existing default-profile rows to the first created profile for these tables:

```python
tables = ["videos", "channels", "watch_log", "search_log"]
```

It does not migrate `playlists`.

### Why This Matters

Production risk is low:

- The application bootstraps a `default` profile on startup.
- Playlists did not exist in released databases before this feature branch.
- Normal usage should not create playlist rows before profiles exist.

Still, the omission makes profile migration incomplete and can surprise tests, scripts, or future imports that create playlist rows before creating the first profile.

### Recommended Fix

Include `playlists` in first-profile migration.

Do not directly update `playlist_items`; playlist items are linked through `playlist_id`, and the owning playlist row's `profile_id` is enough for profile-scoped reads.

Update the docstring to mention playlists:

```python
If this is the first profile and 'default' data exists, migrates all
default videos/channels/watch_log/search_log/playlists to the new profile.
```

Update:

```python
tables = ["videos", "channels", "watch_log", "search_log"]
```

to:

```python
tables = ["videos", "channels", "watch_log", "search_log", "playlists"]
```

### Tests To Add

Update `tests/test_video_store.py`.

Add under `TestVideoStoreProfiles`:

```python
def test_first_profile_migrates_default_playlists(self, video_store):
    playlist = video_store.create_playlist("Default Playlist", profile_id="default")
    video_store.add_playlist_item(playlist["id"], {
        "video_id": "item1234567",
        "title": "First",
        "channel_name": "Channel A",
    }, profile_id="default")

    video_store.create_profile("child1", "Child One")

    migrated = video_store.get_playlists(profile_id="child1")
    assert [p["name"] for p in migrated] == ["Default Playlist"]
    assert video_store.get_playlists(profile_id="default") == []
    assert [item["video_id"] for item in video_store.get_playlist_items(playlist["id"], profile_id="child1")] == ["item1234567"]
```

Add a non-migration guard if desired:

```python
def test_second_profile_does_not_migrate_default_playlists(self, video_store):
    video_store.create_profile("first", "First")
    video_store.create_playlist("Stray Default Playlist", profile_id="default")

    video_store.create_profile("second", "Second")

    assert [p["name"] for p in video_store.get_playlists(profile_id="default")] == ["Stray Default Playlist"]
    assert video_store.get_playlists(profile_id="second") == []
```

Targeted verification:

```bash
.venv/bin/python -m pytest tests/test_video_store.py -q
```

## Suggested Execution Order

1. Fix help i18n maintainability using `plans/20260715_help_i18n_maintainability_plan.md`.
2. Fix `/importplaylist` invalid category validation.
3. Fix first-profile playlist migration.
4. Run full verification.

## Final Verification For This Follow-Up

Run:

```bash
.venv/bin/python -m pytest tests/test_bot_playlists.py tests/test_video_store.py -q
.venv/bin/python -m pytest -q
git diff --check main...HEAD
```

## Done Criteria

This follow-up is complete when:

- `/importplaylist` rejects invalid category arguments.
- `/importplaylist` rejects extra arguments.
- Invalid import commands do not fetch playlist metadata.
- First-profile migration moves default playlists to the first child profile.
- Playlist item visibility remains correct after first-profile playlist migration.
- Targeted tests pass.
- Full suite passes.
- `git diff --check main...HEAD` passes.
