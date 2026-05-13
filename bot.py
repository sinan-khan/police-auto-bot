import os
import json
import subprocess
import glob
import random
import re
from datetime import datetime
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import gdown

# ============= CONFIGURATION =============
TEMP_DIR = "temp_videos"
PROCESSED_DIR = "processed_clips"
OUTPUT_DIR = "final_shorts"
SHORT_DURATION_RANGE = (15, 55)
VIDEOS_PER_DAY = 2

# YouTube Shorts settings
SHORTS_RESOLUTION = (1080, 1920)
BACKGROUND_BLUR = True
ADD_SUBTITLES = False  # Set to True if you want auto-captions
ADD_WATERMARK = True
ADD_PROGRESS_BAR = True

CHANNEL_NAME = "Seattle PD Bodycam"
CHANNEL_HANDLE = "@SeattlePDBodycam"

# Create directories
for d in [TEMP_DIR, PROCESSED_DIR, OUTPUT_DIR]:
    Path(d).mkdir(exist_ok=True)

TRACKER_FILE = "queue.json"

def load_tracker():
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r") as f:
            return json.load(f)
    return {"next_part_number": 1, "uploaded_clips": [], "source_videos_processed": []}

def save_tracker(tracker):
    with open(TRACKER_FILE, "w") as f:
        json.dump(tracker, f, indent=2)

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
        if "folder" in link or "drive/folders" in link:
            gdown.download_folder(link, output=temp_subdir, quiet=False, use_cookies=False)
        else:
            gdown.download(link, output=temp_subdir, fuzzy=True, quiet=False, use_cookies=False)
    except Exception as e:
        print(f"⚠️ Download error: {e}")
        return []
    video_files = []
    for ext in ['*.mp4', '*.mov', '*.avi', '*.mkv', '*.MP4']:
        video_files.extend(glob.glob(f"{temp_subdir}/**/{ext}", recursive=True))
        video_files.extend(glob.glob(f"{temp_subdir}/{ext}"))
    print(f"✅ Downloaded {len(video_files)} video files")
    return video_files

def split_video_to_random_clips(video_path, source_index):
    duration = get_video_duration(video_path)
    print(f"  📹 Duration: {duration:.1f}s")
    if duration < 15:
        print(f"  ⚠️ Too short, skipping")
        return []
    max_clips = min(15, int(duration / 15))
    num_clips = random.randint(2, min(8, max_clips))
    clips = []
    used_ranges = []
    base_name = Path(video_path).stem
    source_name = f"{source_index}_{base_name[:30]}"
    for i in range(num_clips):
        clip_duration = random.uniform(*SHORT_DURATION_RANGE)
        attempts = 0
        while attempts < 20:
            start_time = random.uniform(0, duration - clip_duration)
            overlap = False
            for used_start, used_end in used_ranges:
                if abs(start_time - used_start) < clip_duration / 2:
                    overlap = True
                    break
            if not overlap:
                break
            attempts += 1
        end_time = min(start_time + clip_duration, duration)
        used_ranges.append((start_time, end_time))
        output_path = f"{PROCESSED_DIR}/clip_{source_name}_{i+1}.mp4"
        cmd = ["ffmpeg", "-i", video_path, "-ss", str(start_time), "-t", str(clip_duration), "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", output_path]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            clips.append(output_path)
            print(f"    ✂️  Clip {i+1}: {start_time:.1f}s-{end_time:.1f}s ({clip_duration:.1f}s)")
        except subprocess.CalledProcessError as e:
            print(f"    ❌ Error: {e}")
    return clips

def convert_to_shorts_format(input_video, output_video, part_number, clip_duration):
    """Convert ANY video to YouTube Shorts 9:16 with blurred background"""
    width, height = get_video_resolution(input_video)
    if not width or not height:
        width, height = 1920, 1080
    
    target_width, target_height = SHORTS_RESOLUTION
    scale_factor = min(target_width / width, target_height / height)
    scaled_width = int(width * scale_factor)
    scaled_height = int(height * scale_factor)
    
    # Build complex filter for Shorts
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
    
    cmd = ["ffmpeg", "-i", input_video, "-vf", filter_complex, "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-y", output_video]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"  ✅ Converted to Shorts (9:16)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ❌ Conversion failed")
        return False

def add_copyright_free_music(video_path):
    """Add copyright-free background music at low volume (15%)"""
    music_dir = "copyright_free_music"
    music_files = []
    if os.path.exists(music_dir):
        music_files = glob.glob(f"{music_dir}/*.mp3") + glob.glob(f"{music_dir}/*.wav") + glob.glob(f"{music_dir}/*.m4a")
    
    output_path = video_path.replace(".mp4", "_with_music.mp4")
    
    if music_files:
        music = random.choice(music_files)
        print(f"  🎵 Adding music: {Path(music).name}")
        cmd = [
            "ffmpeg", "-i", video_path, "-i", music,
            "-filter_complex", "[0:a]volume=1.0[a];[1:a]volume=0.15[b];[a][b]amix=inputs=2:duration=first",
            "-c:v", "copy", "-c:a", "aac", "-y", output_path
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            os.remove(video_path)
            print(f"  ✅ Copyright-free music added")
            return output_path
        except Exception as e:
            print(f"  ⚠️ Could not add music: {e}")
            return video_path
    else:
        print(f"  ⚠️ No music found in '{music_dir}/' - skipping")
        return video_path

def edit_for_youtube_shorts(clip_path, part_number):
    """Complete editing pipeline for copyright-free Shorts"""
    print(f"\n  🎨 Editing Part #{part_number} for YouTube Shorts...")
    
    clip_duration = get_video_duration(clip_path)
    temp_shorts = clip_path.replace(".mp4", "_temp.mp4")
    final_path = f"{OUTPUT_DIR}/shorts_part_{part_number}.mp4"
    
    # Convert to 9:16 vertical format
    if not convert_to_shorts_format(clip_path, temp_shorts, part_number, clip_duration):
        return clip_path
    
    # Add copyright-free background music
    with_music = add_copyright_free_music(temp_shorts)
    
    # Move to final location
    if with_music != final_path:
        os.rename(with_music, final_path)
    
    # Cleanup
    if os.path.exists(temp_shorts) and temp_shorts != final_path:
        os.remove(temp_shorts)
    
    print(f"  ✅ Shorts ready for upload")
    return final_path

def generate_metadata(part_number):
    """Generate SEO-friendly title, description, tags"""
    title = f"🚨 Seattle PD Bodycam - PART #{part_number} #Shorts"
    description = f"""🔴 SEATTLE POLICE BODYCAM FOOTAGE - PART #{part_number}

Real body camera footage from Seattle Police Department (SPD)

⚠️ DISCLAIMER: For informational purposes only.

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
                raise Exception("client_secrets.json not found! Add YT_CLIENT_SECRETS secret.")
            flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def upload_to_youtube(video_path, title, description, tags):
    youtube = get_authenticated_service()
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

def main():
    print("\n" + "=" * 60)
    print("📱 SEATTLE PD YOUTUBE SHORTS BOT")
    print("🎬 Format: 9:16 Vertical with Copyright-Free Music")
    print("=" * 60 + "\n")
    
    tracker = load_tracker()
    next_part = tracker["next_part_number"]
    print(f"📊 Next Part: #{next_part}")
    
    # Read drive links
    drive_links = []
    if os.path.exists("drive_links.txt"):
        with open("drive_links.txt", "r") as f:
            drive_links = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    if not drive_links:
        print("❌ No links found in drive_links.txt")
        return
    
    print(f"📁 Found {len(drive_links)} Drive link(s)")
    
    # Download all videos
    all_videos = []
    for link in drive_links:
        videos = download_from_drive(link)
        all_videos.extend(videos)
    
    if not all_videos:
        print("❌ No videos downloaded")
        return
    
    print(f"\n📦 Downloaded {len(all_videos)} video(s)")
    
    # Generate clips
    all_clips = []
    for idx, video in enumerate(all_videos, 1):
        print(f"\n🎬 Processing video {idx}/{len(all_videos)}: {Path(video).name}")
        clips = split_video_to_random_clips(video, idx)
        all_clips.extend(clips)
    
    print(f"\n🎯 Total clips generated: {len(all_clips)}")
    
    # Check queue
    uploaded_count = len(tracker["uploaded_clips"])
    remaining = all_clips[uploaded_count:]
    
    print(f"📋 Already uploaded: {uploaded_count}")
    print(f"📋 In queue: {len(remaining)}")
    
    if not remaining:
        print("🎉 All clips done! Add more videos to drive_links.txt")
        return
    
    # Upload today's videos
    today_uploads = min(VIDEOS_PER_DAY, len(remaining))
    print(f"\n🚀 Uploading {today_uploads} Short(s) today...")
    
    for i in range(today_uploads):
        part_num = next_part + i
        print(f"\n📹 Part #{part_num}")
        
        # Edit for Shorts (adds copyright-free music + vertical format)
        shorts_video = edit_for_youtube_shorts(remaining[i], part_num)
        
        # Generate metadata
        title, description, tags = generate_metadata(part_num)
        print(f"   Title: {title[:50]}...")
        
        # Upload
        video_id = upload_to_youtube(shorts_video, title, description, tags)
        
        if video_id:
            tracker["uploaded_clips"].append({
                "part_number": part_num,
                "video_id": video_id,
                "uploaded_at": datetime.now().isoformat()
            })
    
    tracker["next_part_number"] = next_part + today_uploads
    save_tracker(tracker)
    
    print("\n" + "=" * 60)
    print(f"✅ Done! Uploaded {today_uploads} Short(s)")
    print(f"📊 Next Part: #{tracker['next_part_number']}")
    print(f"📋 Remaining: {len(remaining) - today_uploads}")
    print("=" * 60)

if __name__ == "__main__":
    main()
