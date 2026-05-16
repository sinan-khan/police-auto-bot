import os
import json
import subprocess
import glob
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
PROCESSED_DIR = "processed_clips"
OUTPUT_DIR = "final_shorts"
OUTPUT_CLIPS_DIR = "output_clips"
SHORTS_RESOLUTION = (1080, 1920)
BACKGROUND_BLUR = True
CHANNEL_HANDLE = "@SeattlePDBodycam"
VIDEOS_PER_DAY = 1

# Create directories
for d in [PROCESSED_DIR, OUTPUT_DIR, OUTPUT_CLIPS_DIR]:
    Path(d).mkdir(exist_ok=True)

QUEUE_FILE = "upload_queue.json"

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
    print(f"  📥 Re-downloading from drive...")
    temp_subdir = os.path.join("temp_download", str(int(datetime.now().timestamp())))
    Path(temp_subdir).mkdir(exist_ok=True, parents=True)
    
    try:
        if "file/d/" in link:
            file_id = link.split("file/d/")[1].split("/")[0].split("?")[0]
            output_path = os.path.join(temp_subdir, f"video_{file_id}.mp4")
            gdown.download(id=file_id, output=output_path, quiet=False)
            return output_path
    except Exception as e:
        print(f"  ⚠️ Download error: {e}")
        return None
    return None

def generate_clip_file(clip_info, part_number):
    os.makedirs(OUTPUT_CLIPS_DIR, exist_ok=True)
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
    except subprocess.CalledProcessError as e:
        print(f"    ❌ Failed to generate clip")
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
        print(f"    ✅ Converted to Shorts (9:16)")
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
                print("⚠️ client_secrets.json not found!")
                return None
            flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def upload_to_youtube(video_path, title, description, tags):
    if not os.path.exists(video_path):
        print(f"  ❌ Video file not found")
        return None
    
    file_size = os.path.getsize(video_path)
    print(f"  📹 File size: {file_size/1024/1024:.2f} MB")
    
    youtube = get_authenticated_service()
    if not youtube:
        return None
    
    body = {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:500], "categoryId": "22"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    }
    
    media = MediaFileUpload(video_path, chunksize=1024*1024, resumable=True)
    print(f"  📤 Uploading...")
    
    try:
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
        video_id = response.get('id')
        if video_id:
            print(f"  ✅ Uploaded! https://youtube.com/shorts/{video_id}")
            return video_id
    except HttpError as e:
        print(f"  ❌ YouTube API Error: {e}")
    return None

def main():
    print("\n" + "=" * 60)
    print("📤 UPLOAD BOT - Upload videos from queue (NO downloads)")
    print("=" * 60)
    
    queue = load_queue()
    
    if not queue["pending_clips"]:
        print("✅ No pending clips to upload!")
        return
    
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
            print(f"  ⚠️ Source video missing, checking drive link...")
            drive_link = clip_info.get("drive_link")
            if drive_link:
                source_path = download_from_drive(drive_link)
                if source_path:
                    clip_info["source_video_path"] = source_path
                    print(f"  ✅ Re-downloaded successfully")
                else:
                    print(f"  ❌ Failed to re-download")
                    continue
            else:
                print(f"  ❌ No drive link available")
                continue
        
        raw_clip = generate_clip_file(clip_info, part_num)
        if not raw_clip:
            continue
        
        final_video = os.path.join(OUTPUT_DIR, f"shorts_part_{part_num}.mp4")
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
                "uploaded_at": datetime.now().isoformat()
            })
            
            for f in [raw_clip, final_video]:
                if os.path.exists(f):
                    os.remove(f)
    
    queue["pending_clips"] = queue["pending_clips"][today_uploads:]
    queue["next_part_number"] = next_part + today_uploads
    save_queue(queue)
    
    print("\n" + "=" * 60)
    print(f"✅ Uploaded {today_uploads} Short(s)")
    print(f"📊 Next Part: #{queue['next_part_number']}")
    print(f"📊 Remaining in queue: {len(queue['pending_clips'])}")
    print("=" * 60)

if __name__ == "__main__":
    main()
