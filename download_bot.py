import os
import glob
import random
import shutil
from datetime import datetime
from pathlib import Path
import gdown

from bot_common import (
    load_queue, save_queue, load_processed_videos, save_processed_videos,
    get_video_hash, get_video_duration,
    ensure_release_exists, upload_clip_asset,
)
from clip_tools import cut_and_convert_clip

# ============= CONFIGURATION =============
TEMP_DIR = "temp_videos"
SHORT_DURATION_RANGE = (15, 55)

VIDEO_EXTENSIONS = ("mp4", "mov", "avi", "mkv", "webm")


def download_from_drive(link, temp_subdir):
    print(f"📥 Downloading from: {link[:80]}...")
    Path(temp_subdir).mkdir(parents=True, exist_ok=True)

    try:
        if "file/d/" in link:
            file_id = link.split("file/d/")[1].split("/")[0].split("?")[0]
            output_path = os.path.join(temp_subdir, f"video_{file_id}.mp4")
            gdown.download(id=file_id, output=output_path, quiet=False)
        elif "folders" in link:
            folder_id = link.split("folders/")[1].split("?")[0]
            gdown.download_folder(id=folder_id, output=temp_subdir, quiet=False)
        else:
            print(f"⚠️ Could not parse link: {link}")
            return []
    except Exception as e:
        print(f"⚠️ Download error: {e}")
        return []

    video_files = []
    for ext in VIDEO_EXTENSIONS:
        # case-insensitive: glob doesn't support [Mm][Pp]4 easily across all exts,
        # so just check both cases explicitly.
        video_files.extend(glob.glob(f"{temp_subdir}/**/*.{ext}", recursive=True))
        video_files.extend(glob.glob(f"{temp_subdir}/**/*.{ext.upper()}", recursive=True))

    video_files = sorted(set(video_files))
    print(f"✅ Downloaded {len(video_files)} video file(s)")
    return video_files


def plan_clips(duration):
    """Pick random (start, duration) windows for this source video."""
    if duration < 15:
        return []

    max_clips = min(20, int(duration / 15))
    num_clips = random.randint(3, min(10, max_clips))

    windows = []
    for _ in range(num_clips):
        clip_duration = random.uniform(*SHORT_DURATION_RANGE)
        clip_duration = min(clip_duration, duration)
        attempts = 0
        while attempts < 30:
            start_time = random.uniform(0, max(0, duration - clip_duration))
            overlap = any(abs(start_time - s) < clip_duration / 1.5 for s, _ in windows)
            if not overlap:
                break
            attempts += 1
        windows.append((start_time, clip_duration))
    return windows


def process_video(video_path, video_hash, queue):
    """Cut every planned clip for this video, upload each as a release asset,
    and enqueue a reference to it. No local path or drive_link is stored in
    the queue — the release asset is now the single source of truth."""
    duration = get_video_duration(video_path)
    print(f"  📹 Duration: {duration:.1f}s")

    windows = plan_clips(duration)
    if not windows:
        print("  ⚠️ Too short, skipping")
        return 0

    video_tag = video_hash[:10]
    added = 0
    for i, (start_time, clip_duration) in enumerate(windows, start=1):
        end_time = min(start_time + clip_duration, duration)
        local_clip = f"clip_{video_tag}_{i}.mp4"
        print(f"    ✂️  Clip {i}: {start_time:.1f}s-{end_time:.1f}s ({clip_duration:.1f}s)")

        try:
            cut_and_convert_clip(video_path, start_time, clip_duration, local_clip)
        except Exception as e:
            print(f"    ❌ Failed to cut/convert clip {i}: {e}")
            continue

        try:
            asset_name = upload_clip_asset(local_clip)
        except Exception as e:
            print(f"    ❌ Failed to upload clip {i} to release storage: {e}")
            os.remove(local_clip)
            continue

        os.remove(local_clip)
        queue["pending_clips"].append({
            "asset_name": asset_name,
            "video_hash": video_hash,
        })
        added += 1
        print(f"    ✅ Clip {i} stored as release asset: {asset_name}")

    return added


def main():
    print("\n" + "=" * 60)
    print("📥 DOWNLOAD BOT - Download, cut, and stage clips for upload")
    print("=" * 60)

    queue = load_queue()
    processed_videos = load_processed_videos()

    drive_links = []
    if os.path.exists("drive_links.txt"):
        with open("drive_links.txt", "r") as f:
            drive_links = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if not drive_links:
        print("❌ No links found in drive_links.txt")
        return

    print(f"📁 Found {len(drive_links)} Drive link(s)")
    ensure_release_exists()

    total_new_clips = 0
    for idx, link in enumerate(drive_links):
        temp_subdir = os.path.join(TEMP_DIR, f"{idx}_{int(datetime.now().timestamp())}")
        # Each video is downloaded and processed against the link that
        # actually produced it — no more guessing/mismatching afterward.
        for video_path in download_from_drive(link, temp_subdir):
            video_hash = get_video_hash(video_path)

            if video_hash in processed_videos:
                print(f"\n⏭️ Skipping already processed: {Path(video_path).name}")
                continue

            print(f"\n🎬 NEW VIDEO: {Path(video_path).name}  (from {link[:60]}...)")
            added = process_video(video_path, video_hash, queue)
            if added:
                processed_videos.add(video_hash)
                total_new_clips += added
                print(f"   ✅ Added {added} clip(s) to upload queue")
            else:
                print("   ⚠️ No clips generated")

        shutil.rmtree(temp_subdir, ignore_errors=True)

    save_queue(queue)
    save_processed_videos(processed_videos)

    print(f"\n📊 Total clips staged this run: {total_new_clips}")
    print(f"📊 Total clips in queue: {len(queue['pending_clips'])}")
    print(f"📌 Next scheduled upload will start from Part #{queue['next_part_number']}")
    print("\n✅ DOWNLOAD COMPLETE!")


if __name__ == "__main__":
    main()
