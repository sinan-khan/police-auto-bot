import os
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import gdown

# ============= CONFIGURATION =============
OUTPUT_CLIPS_DIR = "output_clips"
PROCESSED_DIR = "shorts_ready"
VIDEOS_PER_DAY = 1
QUEUE_FILE = "upload_queue.json"

# Create directories
for d in [OUTPUT_CLIPS_DIR, PROCESSED_DIR]:
    Path(d).mkdir(exist_ok=True)

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

def download_from_drive(link):
    print(f"  📥 Downloading from drive...")
    temp_dir = "temp_download"
    Path(temp_dir).mkdir(exist_ok=True)
    
    try:
        if "file/d/" in link:
            file_id = link.split("file/d/")[1].split("/")[0].split("?")[0]
            output_path = os.path.join(temp_dir, f"video_{file_id}.mp4")
            gdown.download(id=file_id, output=output_path, quiet=False)
            return output_path
    except Exception as e:
        print(f"  ⚠️ Download error: {e}")
        return None
    return None

def generate_clip_file(clip_info, part_number):
    output_path = os.path.join(OUTPUT_CLIPS_DIR, f"clip_{part_number}.mp4")
    
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
        print(f"    ✅ Clip created")
        return output_path
    except subprocess.CalledProcessError:
        print(f"    ❌ Failed to create clip")
        return None

def convert_to_shorts(input_video, output_video):
    """Convert any video to YouTube Shorts format (9:16 vertical)"""
    
    # Get video info
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "default=noprint_wrappers=1", input_video]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    width = height = None
    for line in result.stdout.split('\n'):
        if 'width=' in line:
            width = int(line.split('=')[1])
        if 'height=' in line:
            height = int(line.split('=')[1])
    
    if not width or not height:
        width, height = 1920, 1080
    
    print(f"    📐 Original: {width}x{height}")
    
    # Target Shorts size
    target_w, target_h = 1080, 1920
    
    # Complex filter: Scale to fit, then pad to 9:16
    filter_complex = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=1,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black"
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
        print(f"    ✅ Converted to Shorts (9:16)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"    ❌ Conversion failed: {e.stderr if e.stderr else str(e)}")
        return False

def generate_metadata(part_number):
    title = f"USA Police Bodycam - PART #{part_number} #Shorts"
    description = f"""USA Police BODYCAM FOOTAGE - PART #{part_number}

Real body camera footage from Seattle Police Department (SPD)

🔔 SUBSCRIBE for more bodycam content daily!

#SeattlePolice #Bodycam #PoliceBodycam #SPD #Shorts"""
    tags = ["Seattle Police", "Bodycam", "SPD", "Police Bodycam", "Seattle PD", "Shorts"]
    return title, description, tags

def get_authenticated_service():
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None
    
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        else:
            print("  ❌ No valid token found")
            return None
    
    return build("youtube", "v3", credentials=creds)

def upload_to_youtube(video_path, title, description, tags):
    if not os.path.exists(video_path):
        print(f"  ❌ Video not found")
        return None
    
    file_size = os.path.getsize(video_path)
    print(f"  📹 File size: {file_size/1024/1024:.2f} MB")
    
    youtube = get_authenticated_service()
    if not youtube:
        return None
    
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    
    media = MediaFileUpload(video_path, chunksize=1024*1024, resumable=True)
    print(f"  📤 Uploading...")
    
    try:
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
        video_id = response.get('id')
        
        if video_id:
            print(f"  ✅ UPLOADED! Shorts ID: {video_id}")
            print(f"  🔗 https://youtube.com/shorts/{video_id}")
            return video_id
        else:
            print(f"  ❌ No video ID")
            return None
    except HttpError as e:
        print(f"  ❌ YouTube API Error: {e}")
        return None

def main():
    print("\n" + "=" * 60)
    print("📤 UPLOAD BOT - YouTube Shorts Uploader")
    print("=" * 60)
    
    queue = load_queue()
    
    if not queue["pending_clips"]:
        print("✅ No pending clips to upload!")
        return
    
    next_part = queue["next_part_number"]
    print(f"📊 Next Part: #{next_part}")
    print(f"📊 Pending clips: {len(queue['pending_clips'])}")
    
    today_uploads = min(VIDEOS_PER_DAY, len(queue["pending_clips"]))
    print(f"\n🚀 Uploading {today_uploads} Short(s)...")
    
    for i in range(today_uploads):
        part_num = next_part + i
        clip_info = queue["pending_clips"][i]
        
        print(f"\n📹 Processing Part #{part_num}")
        
        source_path = clip_info.get("source_video_path")
        if not source_path or not os.path.exists(source_path):
            drive_link = clip_info.get("drive_link")
            if drive_link:
                source_path = download_from_drive(drive_link)
                if source_path:
                    clip_info["source_video_path"] = source_path
                else:
                    continue
            else:
                continue
        
        # Create raw clip
        raw_clip = generate_clip_file(clip_info, part_num)
        if not raw_clip:
            continue
        
        # Convert to Shorts format (9:16)
        shorts_video = os.path.join(PROCESSED_DIR, f"shorts_{part_num}.mp4")
        if not convert_to_shorts(raw_clip, shorts_video):
            print(f"  ⚠️ Skipping upload - conversion failed")
            continue
        
        title, description, tags = generate_metadata(part_num)
        print(f"   Title: {title}")
        
        video_id = upload_to_youtube(shorts_video, title, description, tags)
        
        if video_id:
            queue["uploaded_clips"].append({
                "part_number": part_num,
                "video_id": video_id,
                "uploaded_at": datetime.now().isoformat()
            })
            
            # Cleanup
            for f in [raw_clip, shorts_video]:
                if os.path.exists(f):
                    os.remove(f)
    
    queue["pending_clips"] = queue["pending_clips"][today_uploads:]
    queue["next_part_number"] = next_part + today_uploads
    save_queue(queue)
    
    print("\n" + "=" * 60)
    print(f"✅ Uploaded {today_uploads} Short(s)")
    print(f"📊 Next Part: #{queue['next_part_number']}")
    print(f"📊 Remaining: {len(queue['pending_clips'])}")
    print("=" * 60)

if __name__ == "__main__":
    main()
