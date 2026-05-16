import os
import json
import subprocess
import glob
import random
from datetime import datetime
from pathlib import Path
import gdown
import hashlib

# ============= CONFIGURATION =============
TEMP_DIR = "temp_videos"
OUTPUT_CLIPS_DIR = "output_clips"
SHORT_DURATION_RANGE = (15, 55)

# Create directories
for d in [TEMP_DIR, OUTPUT_CLIPS_DIR]:
    Path(d).mkdir(exist_ok=True)

QUEUE_FILE = "upload_queue.json"
PROCESSED_VIDEOS_FILE = "processed_videos.json"

def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r") as f:
            queue = json.load(f)
            if "pending_clips" not in queue:
                queue["pending_clips"] = []
            if "uploaded_clips" not in queue:
                queue["uploaded_clips"] = []
            if "next_part_number" not in queue:
                queue["next_part_number"] = 1
            return queue
    return {"pending_clips": [], "uploaded_clips": [], "next_part_number": 1}

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
        json.dump(list(processed_set), f, indent=2)

def get_video_hash(video_path):
    try:
        with open(video_path, 'rb') as f:
            f.seek(0)
            head = f.read(1024 * 1024)
            f.seek(-1024 * 1024, os.SEEK_END)
            tail = f.read(1024 * 1024)
            return hashlib.md5(head + tail).hexdigest()
    except:
        return hashlib.md5(str(datetime.now()).encode()).hexdigest()

def get_video_duration(video_path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())

def download_from_drive(link):
    print(f"📥 Downloading from: {link[:80]}...")
    temp_subdir = os.path.join(TEMP_DIR, str(int(datetime.now().timestamp())))
    Path(temp_subdir).mkdir(exist_ok=True)
    
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
    for ext in ['*.mp4', '*.mov', '*.avi', '*.mkv', '*.MP4', '*.webm']:
        video_files.extend(glob.glob(f"{temp_subdir}/**/{ext}", recursive=True))
        video_files.extend(glob.glob(f"{temp_subdir}/{ext}"))
    
    print(f"✅ Downloaded {len(video_files)} video files")
    return video_files

def split_video_to_clips(video_path, video_hash, drive_link):
    duration = get_video_duration(video_path)
    print(f"  📹 Duration: {duration:.1f}s")
    
    if duration < 15:
        print(f"  ⚠️ Too short, skipping")
        return []
    
    max_clips = min(20, int(duration / 15))
    num_clips = random.randint(3, min(10, max_clips))
    
    clips = []
    used_ranges = []
    video_name = Path(video_path).stem[:40]
    
    for i in range(num_clips):
        clip_duration = random.uniform(*SHORT_DURATION_RANGE)
        attempts = 0
        while attempts < 30:
            start_time = random.uniform(0, duration - clip_duration)
            overlap = False
            for used_start, used_end in used_ranges:
                if abs(start_time - used_start) < clip_duration / 1.5:
                    overlap = True
                    break
            if not overlap:
                break
            attempts += 1
        
        end_time = min(start_time + clip_duration, duration)
        used_ranges.append((start_time, end_time))
        
        clip_info = {
            "source_video_hash": video_hash,
            "source_video_path": video_path,
            "drive_link": drive_link,
            "source_video_name": video_name,
            "clip_index": i + 1,
            "start_time": start_time,
            "duration": clip_duration,
            "end_time": end_time
        }
        clips.append(clip_info)
        print(f"    ✂️  Clip {i+1}: {start_time:.1f}s-{end_time:.1f}s ({clip_duration:.1f}s)")
    
    return clips

def main():
    print("\n" + "=" * 60)
    print("📥 DOWNLOAD BOT - Download videos and create clips (NO uploads)")
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
    
    all_new_videos = []
    for link in drive_links:
        videos = download_from_drive(link)
        all_new_videos.extend(videos)
    
    if not all_new_videos:
        print("❌ No videos downloaded")
        return
    
    print(f"\n📦 Downloaded {len(all_new_videos)} video(s)")
    
    new_clips_added = 0
    
    for video_path in all_new_videos:
        video_hash = get_video_hash(video_path)
        
        if video_hash in processed_videos:
            print(f"\n⏭️ Skipping already processed: {Path(video_path).name}")
            continue
        
        print(f"\n🎬 NEW VIDEO: {Path(video_path).name}")
        
        drive_link = next((link for link in drive_links if video_path in str(link)), drive_links[0])
        clips = split_video_to_clips(video_path, video_hash, drive_link)
        
        if clips:
            for clip in clips:
                queue["pending_clips"].append(clip)
            new_clips_added += len(clips)
            processed_videos.add(video_hash)
            print(f"   ✅ Added {len(clips)} clips to upload queue")
        else:
            print(f"   ⚠️ No clips generated")
    
    save_queue(queue)
    save_processed_videos(processed_videos)
    
    print(f"\n📊 Total clips in queue: {len(queue['pending_clips'])}")
    print(f"📌 Next scheduled upload will start from Part #{queue['next_part_number']}")
    print("\n✅ DOWNLOAD COMPLETE! No uploads were performed.")

if __name__ == "__main__":
    main()
