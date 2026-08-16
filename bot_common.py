"""
Shared utilities for download_bot.py and upload_bot.py.

Storage model
-------------
Finished, ready-to-upload Shorts clips are stored as assets on a single
persistent GitHub Release (tag RELEASE_TAG) in this repo. This replaces
the old design where upload_bot.py tried to re-download the *original*
source video from Google Drive on every run:
  - it removes the Drive re-download entirely from the daily upload path
    (no more Google Drive quota risk on the critical path)
  - it removes the bug where every re-download used the wrong source
    video (see README "What was fixed")
  - clips are cut once, in download_bot.py, while the source video is
    still on local disk in that same job

Requires the `gh` CLI (preinstalled on GitHub-hosted runners) authenticated
via the GH_TOKEN env var, and the workflow needs `permissions: contents: write`.
No extra secrets are needed — GITHUB_TOKEN is provided automatically.
"""

import os
import json
import subprocess
import hashlib
from pathlib import Path

QUEUE_FILE = "upload_queue.json"
PROCESSED_VIDEOS_FILE = "processed_videos.json"
RELEASE_TAG = "clip-queue"


# ---------- queue / processed-video bookkeeping ----------

def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r") as f:
            queue = json.load(f)
    else:
        queue = {}
    queue.setdefault("pending_clips", [])
    queue.setdefault("uploaded_clips", [])
    queue.setdefault("next_part_number", 1)
    return queue


def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def load_processed_videos():
    if os.path.exists(PROCESSED_VIDEOS_FILE):
        with open(PROCESSED_VIDEOS_FILE, "r") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    return set()


def save_processed_videos(processed_set):
    with open(PROCESSED_VIDEOS_FILE, "w") as f:
        json.dump(sorted(processed_set), f, indent=2)


def get_video_hash(video_path):
    """Hash the first+last 1MB so we can dedupe without hashing huge files fully."""
    try:
        with open(video_path, "rb") as f:
            head = f.read(1024 * 1024)
            f.seek(-min(1024 * 1024, os.path.getsize(video_path)), os.SEEK_END)
            tail = f.read(1024 * 1024)
            return hashlib.md5(head + tail).hexdigest()
    except OSError as e:
        # Fail loudly instead of silently hashing the current timestamp
        # (the old fallback made hash collisions/misses undetectable).
        raise RuntimeError(f"Could not hash video at {video_path}: {e}") from e


def get_video_duration(video_path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


# ---------- GitHub Release used as free clip storage ----------

def _run_gh(args, **kwargs):
    return subprocess.run(["gh"] + args, capture_output=True, text=True, **kwargs)


def ensure_release_exists():
    check = _run_gh(["release", "view", RELEASE_TAG])
    if check.returncode != 0:
        create = _run_gh([
            "release", "create", RELEASE_TAG,
            "--title", "Clip Queue (auto-managed)",
            "--notes", "Auto-managed storage for ready-to-upload clips. Do not edit manually.",
        ])
        if create.returncode != 0:
            raise RuntimeError(f"Could not create release {RELEASE_TAG}: {create.stderr}")


def upload_clip_asset(local_path):
    """Upload a finished clip file as a release asset. Returns the asset name."""
    asset_name = Path(local_path).name
    result = _run_gh(["release", "upload", RELEASE_TAG, local_path, "--clobber"])
    if result.returncode != 0:
        raise RuntimeError(f"Could not upload asset {asset_name}: {result.stderr}")
    return asset_name


def download_clip_asset(asset_name, dest_dir):
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    result = _run_gh(["release", "download", RELEASE_TAG, "-p", asset_name, "-D", dest_dir, "--clobber"])
    if result.returncode != 0:
        return None
    return os.path.join(dest_dir, asset_name)


def delete_clip_asset(asset_name):
    # Best-effort cleanup; don't fail the run if this doesn't succeed.
    _run_gh(["release", "delete-asset", RELEASE_TAG, asset_name, "--yes"])
