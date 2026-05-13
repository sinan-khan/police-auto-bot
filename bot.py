import os
import json
import subprocess
import glob
import random
from datetime import datetime
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import gdown
import hashlib
import sys

# ============= CONFIGURATION =============
TEMP_DIR = "temp_videos"
PROCESSED_DIR = "processed_clips"
OUTPUT_DIR = "final_shorts"
SHORT_DURATION_RANGE = (15, 55)
VIDEOS_PER_DAY = 2
SHORTS_RESOLUTION = (1080, 1920)
BACKGROUND_BLUR = True
CHANNEL_HANDLE = "@SeattlePDBodycam"

# Create directories
for d in [TEMP_DIR, PROCESSED_DIR, OUTPUT_DIR]:
    Path(d).mkdir(exist_ok=True)

# Queue files
QUEUE_FILE = "upload_queue.json"
PROCESSED_VIDEOS_FILE = "processed_videos.json"

def load_queue():
    """Load the upload queue"""
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
    return {
        "pending_clips": [],
        "uploaded_clips": [],
        "next_part_number": 1
    }

def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)

def load_processed_videos():
    if os.path.exists(PROCESSED_VIDEOS_FILE):
        with open(PROCESSED_VIDEOS_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(data)
            return set()
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

def get_video_resolution(video_path):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "default=noprint_wrappers=1", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    width = height = None
    for line in result.stdout.split('\n'):
        if 'width=' in line:
            width = int(line.split('=')[1])
        if 'height=' in line:
            height = int(line.split('=')[1])
    return width, height

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

def split_video_to_clips(video_path, video_hash):
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
            "source_video_name": video_name,
            "clip_index": i + 1,
            "start_time": start_time,
            "duration": clip_duration,
            "end_time": end_time
        }
        clips.append(clip_info)
        print(f"    ✂️  Clip {i+1}: {start_time:.1f}s-{end_time:.1f}s ({clip_duration:.1f}s)")
    
    return clips

def generate_clip_file(clip_info, part_number):
    output_path = f"{PROCESSED_DIR}/clip_{part_number}.mp4"
    cmd = [
        "ffmpeg", "-i", clip_info["source_video_path"],
        "-ss", str(clip_info["start_time"]),
        "-t", str(clip_info["duration"]),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-y", output_path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"    ❌ Failed to generate clip: {e}")
        return None

def convert_to_shorts_format(input_video, output_video, part_number, clip_duration):
    width, height = get_video_resolution(input_video)
    if not width or not height:
        width, height = 1920, 1080
    
    target_width, target_height = SHORTS_RESOLUTION
    scale_factor = min(target_width / width, target_height / height)
    scaled_width = int(width * scale_factor)
    scaled_height = int(height * scale_factor)
    
    if BACKGROUND_BLUR:
        filter_complex = (
            f"[0:v]scale={target_width}:{target_height},boxblur=luma_radius=min(h\\,w)/40:luma_power=3[bg];"
            f"[0:v]scale={scaled_width}:{scaled_height}[fg];"
            f"[bg][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2,"
            f"drawtext=text='SEATTLE PD BODYCAM  |  PART #{part_number}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=50:box=1:boxcolor=black@0.7:boxborderw=10,"
            f"drawtext=text='PART {part_number}':fontcolor=yellow:fontsize=36:x=w-text_w-30:y=30:box=1:boxcolor=black@0.8:boxborderw=8,"
            f"drawtext=text='{CHANNEL_HANDLE}':fontcolor=white@0.6:fontsize=24:x=30:y=H-50,"
            f"drawbox=x=0:y=H-10:w=w*(t/{clip_duration}):h=5:color=yellow@0.8"
        )
    else:
        filter_complex = (
            f"scale={scaled_width}:{scaled_height},pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"drawtext=text='SEATTLE PD BODYCAM  |  PART #{part_number}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=50:box=1:boxcolor=black@0.7:boxborderw=10,"
            f"drawtext=text='PART {part_number}':fontcolor=yellow:fontsize=36:x=w-text_w-30:y=30:box=1:boxcolor=black@0.8:boxborderw=8,"
            f"drawtext=text='{CHANNEL_HANDLE}':fontcolor=white@0.6:fontsize=24:x=30:y=H-50"
        )
    
    cmd = [
        "ffmpeg", "-i", input_video,
        "-vf", filter_complex,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", output_video
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError:
        return False

def generate_metadata(part_number):
    title = f"🚨 Seattle PD Bodycam - PART #{part_number} #Shorts"
    description = f"""🔴 SEATTLE POLICE BODYCAM FOOTAGE - PART #{part_number}

Real body camera footage from Seattle Police Department (SPD)

⚠️ DISCLAIMER: This footage is for informational purposes only.

🔔 SUBSCRIBE for more bodycam content daily!

#SeattlePolice #Bodycam #PoliceBodycam #SPD #RealPolice #Shorts"""
    tags = ["Seattle Police", "Bodycam", "SPD", "Police Bodycam", "Seattle PD", "Real Police", "Law Enforcement", "Shorts"]
    return title, description, tags

def get_authenticated_service():
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("client_secrets.json"):
                print("⚠️ WARNING: client_secrets.json not found! YouTube upload will fail.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def upload_to_youtube(video_path, title, description, tags):
    youtube = get_authenticated_service()
    if not youtube:
        return None
    
    body = {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:500], "categoryId": "22"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    print(f"  📤 Uploading...")
    try:
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
        video_id = response['id']
        print(f"  ✅ Uploaded! https://youtube.com/shorts/{video_id}")
        return video_id
    except HttpError as e:
        print(f"  ❌ Failed: {e}")
        return None

def download_only_mode():
    """ONLY download new videos and create clips - NO uploads"""
    print("\n" + "=" * 60)
    print("📥 DOWNLOAD MODE: Processing new videos (NO uploads)")
    print("=" * 60)
    
    queue = load_queue()
    processed_videos = load_processed_videos()
    
    # Read drive links
    drive_links = []
    if os.path.exists("drive_links.txt"):
        with open("drive_links.txt", "r") as f:
            drive_links = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    if not drive_links:
        print("❌ No links found in drive_links.txt")
        return False
    
    print(f"📁 Found {len(drive_links)} Drive link(s)")
    
    all_new_videos = []
    for link in drive_links:
        videos = download_from_drive(link)
        all_new_videos.extend(videos)
    
    if not all_new_videos:
        print("❌ No videos downloaded")
        return False
    
    print(f"\n📦 Downloaded {len(all_new_videos)} video(s)")
    
    new_clips_added = 0
    
    for video_path in all_new_videos:
        video_hash = get_video_hash(video_path)
        
        if video_hash in processed_videos:
            print(f"\n⏭️  Skipping already processed: {Path(video_path).name}")
            continue
        
        print(f"\n🎬 NEW VIDEO: {Path(video_path).name}")
        clips = split_video_to_clips(video_path, video_hash)
        
        if clips:
            for clip in clips:
                queue["pending_clips"].append(clip)
            new_clips_added += len(clips)
            processed_videos.add(video_hash)
            print(f"   ✅ Added {len(clips)} clips to upload queue (will upload on schedule)")
        else:
            print(f"   ⚠️ No clips generated")
    
    save_queue(queue)
    save_processed_videos(processed_videos)
    
    print(f"\n📊 Total clips in queue: {len(queue['pending_clips'])}")
    print(f"📊 Clips waiting to upload: {len(queue['pending_clips'])}")
    print(f"\n✅ DOWNLOAD MODE COMPLETE!")
    print(f"📌 Next scheduled upload will start from Part #{queue['next_part_number']}")
    
    return new_clips_added > 0

def upload_only_mode():
    """ONLY upload from queue - NO downloading"""
    print("\n" + "=" * 60)
    print("📤 UPLOAD MODE: Uploading scheduled videos (NO downloads)")
    print("=" * 60)
    
    queue = load_queue()
    
    if not queue["pending_clips"]:
        print("✅ No pending clips to upload!")
        return False
    
    next_part = queue["next_part_number"]
    print(f"📊 Next Part number: #{next_part}")
    print(f"📊 Pending clips: {len(queue['pending_clips'])}")
    
    today_uploads = min(VIDEOS_PER_DAY, len(queue["pending_clips"]))
    print(f"\n🚀 Uploading {today_uploads} Short(s) today...")
    
    for i in range(today_uploads):
        part_num = next_part + i
        clip_info = queue["pending_clips"][i]
        
        print(f"\n📹 Processing Part #{part_num}")
        
        source_path = clip_info.get("source_video_path")
        if not source_path or not os.path.exists(source_path):
            print(f"  ❌ Source video missing: {source_path}")
            continue
        
        raw_clip = generate_clip_file(clip_info, part_num)
        if not raw_clip:
            continue
        
        final_video = f"{OUTPUT_DIR}/shorts_part_{part_num}.mp4"
        clip_duration = clip_info["duration"]
        
        if not convert_to_shorts_format(raw_clip, final_video, part_num, clip_duration):
            continue
        
        title, description, tags = generate_metadata(part_num)
        print(f"   Title: {title}")
        
        video_id = upload_to_youtube(final_video, title, description, tags)
        
        if video_id:
            queue["uploaded_clips"].append({
                "part_number": part_num,
                "video_id": video_id,
                "source_clip": clip_info,
                "uploaded_at": datetime.now().isoformat()
            })
            
            if os.path.exists(raw_clip):
                os.remove(raw_clip)
    
    queue["pending_clips"] = queue["pending_clips"][today_uploads:]
    queue["next_part_number"] = next_part + today_uploads
    save_queue(queue)
    
    print("\n" + "=" * 60)
    print(f"✅ Uploaded {today_uploads} Short(s)")
    print(f"📊 Next Part: #{queue['next_part_number']}")
    print(f"📊 Remaining in queue: {len(queue['pending_clips'])}")
    print("=" * 60)
    
    return True

def main():
    # Check if this is a manual run (workflow_dispatch) or scheduled run
    # GitHub Actions sets GITHUB_EVENT_NAME environment variable
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    
    print("\n" + "🎬" * 30)
    print("SEATTLE PD YOUTUBE SHORTS BOT")
    print("🎬" * 30)
    
    if event_name == "workflow_dispatch":
        # MANUAL RUN: Only download and clip, NO upload
        print("\n🔧 MANUAL TRIGGER DETECTED: Download mode only")
        download_only_mode()
    else:
        # SCHEDULED RUN: Only upload, NO download
        print("\n⏰ SCHEDULED TRIGGER DETECTED: Upload mode only")
        upload_only_mode()
    
    print("\n" + "=" * 60)
    print("✅ BOT FINISHED")
    print("=" * 60)

if __name__ == "__main__":
    main()
