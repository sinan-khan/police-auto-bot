# police-auto-bot (seattlePD-Youtube-bot)

Fully automated pipeline: pulls source bodycam footage from Google Drive,
cuts random vertical clips, and uploads them to YouTube as Shorts on a
schedule — all on free GitHub Actions compute.

## ⚠️ Security notice (read before pushing this update)

This repo's git history contains real YouTube session cookies, committed
under `cookies.txt` / `www.youtube.com_cookies.txt` early in the project
and later deleted (deletion does not remove them from history). Now that
the repo is public, anyone can pull those old commits and read them. If
you haven't already: revoke that Google account's sessions / change its
password, and consider deleting and recreating this repo rather than
relying on history rewriting to fully scrub it.

## Architecture

Two independent GitHub Actions workflows:

- **`download.yml`** (manual trigger) — downloads new source videos from
  the links in `drive_links.txt`, skips any whose content-hash is already
  in `processed_videos.json`, picks several random clip windows per video,
  cuts + converts each straight to 9:16 Shorts format, and uploads the
  finished small clip files as assets on a single persistent GitHub
  Release (`clip-queue`). Only a small JSON reference (`asset_name`,
  `video_hash`) is added to `upload_queue.json` — no video ever touches git.

- **`upload.yml`** (cron, twice daily) — pulls the next queued clip
  straight from the `clip-queue` release, uploads it to YouTube, and
  deletes the asset once the upload is confirmed successful.

This means the daily upload job never talks to Google Drive at all — it
only touches the GitHub Release and the YouTube API.

## What was fixed

- **Wrong-video bug**: the old code tried to match a downloaded video back
  to its Drive link by checking whether the local file path was a
  substring of the URL, which never matched — so every clip got tagged
  with `drive_links[0]`, regardless of its real source. Combined with the
  next bug, this meant re-downloads (which happened constantly, see below)
  fetched the wrong source video for every clip except the first link's.
- **Every upload re-downloaded the wrong full source video**: GitHub
  Actions runners are ephemeral, so the local path saved in the queue by
  the download job never existed on the upload job's runner. The old
  upload bot's fallback then re-downloaded from Drive — but because of the
  bug above, always the same (wrong) video. The new design cuts clips once
  in the download job and stores the finished file, so no re-download ever
  happens on the upload path.
- **Failed uploads silently vanished from the queue**: the old code
  removed clips from `pending_clips` unconditionally after each run,
  success or failure. Now a clip only leaves the queue once its YouTube
  upload is confirmed; a failed run (e.g. YouTube quota exceeded) leaves
  it in place for the next scheduled run.
- **Inaccurate clip cuts**: cutting used `-c copy`, which can only cut on
  keyframe boundaries, so clips didn't reliably start where the queue said
  they would. Cutting and the 9:16 conversion are now done in a single
  frame-accurate ffmpeg pass.
- **Unused dependencies**: `moviepy`, `pillow`, and `numpy` were listed in
  `requirements.txt` but never imported anywhere — removed.
- **Dead credential step**: the upload workflow wrote a `client_secrets.json`
  that `upload_bot.py` never read — removed (see Setup below for when you
  actually need it).
- **No `.gitignore`**: local temp/credential files had no protection from
  being committed by accident — added.

## Setup

Secrets needed (Settings → Secrets and variables → Actions):

- `YT_TOKEN_JSON` — contents of a `token.json` generated once locally via
  the standard Google OAuth installed-app flow, granting the
  `youtube.upload` scope. You only need `client_secrets.json` locally for
  that one-time generation step — it's never needed inside the workflow.

No other secrets are required — release storage uses the automatically
provided `GITHUB_TOKEN`.

## Running

- Add Drive links (one per line) to `drive_links.txt`.
- Trigger `Download & Clip Videos` manually (Actions tab → workflow_dispatch)
  whenever you add new source footage.
- `Upload YouTube Shorts` runs automatically twice a day and drains the
  queue one clip per run (`VIDEOS_PER_RUN` in `upload_bot.py`).
