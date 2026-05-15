#!/usr/bin/env python3
"""
Seattle PD YouTube Shorts Bot
Downloads police bodycam videos, creates shorts clips, and uploads to YouTube
"""

import os
import json
import time
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# YouTube API imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    GOOGLE_IMPORTS_AVAILABLE = True
except ImportError:
    GOOGLE_IMPORTS_AVAILABLE = False
    print("⚠️ Google API libraries not installed. Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")

# YouTube API scope
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Configuration
CONFIG = {
    "videos_per_download": 3,  # Number of videos to download per run
    "clips_per_video": 10,      # Number of clips to extract per video
    "min_clip_duration": 15,    # Minimum clip length in seconds
    "max_clip_duration": 60,    # Maximum clip length in seconds
    "output_dir": "temp_videos",
    "queue_file": "queue.json"
}

def setup_directories():
    """Create necessary directories"""
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    os.makedirs("output_clips", exist_ok=True)

def load_queue():
    """Load the upload queue from JSON file"""
    if os.path.exists(CONFIG["queue_file"]):
        with open(CONFIG["queue_file"], 'r') as f:
            return json.load(f)
    return {
        "pending_clips": [],
        "uploaded_clips": [],
        "next_part_number": 1
    }

def save_queue(queue):
    """Save the upload queue to JSON file"""
    with open(CONFIG["queue_file"], 'w') as f:
        json.dump(queue, f, indent=2)

def download_video(youtube_url, output_path):
    """Download a video using yt-dlp"""
    print(f"📥 Downloading: {youtube_url}")
    
    # Generate random filename if not provided
    if not output_path:
        import hashlib
        hash_id = hashlib.md5(youtube_url.encode()).hexdigest()[:16]
        output_path = os.path.join(CONFIG["output_dir"], f"video_{hash_id}.mp4")
    
    # yt-dlp command
    cmd = [
        "yt-dlp",
        "-f", "best[height<=720]",  # Max 720p to save space
        "-o", output_path,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        youtube_url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(output_path):
            print(f"✅ Downloaded: {output_path}")
            return output_path
        else:
            print(f"❌ Download failed: {result.stderr}")
            return None
    except Exception as e:
        print(f"❌ Download error: {e}")
        return None

def get_video_duration(video_path):
    """Get video duration in seconds using ffprobe"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception as e:
        print(f"❌ Error getting duration: {e}")
    return 0

def extract_clips(video_path, num_clips=10):
    """
    Extract interesting clips from video
    Returns list of clip info dicts
    """
    duration = get_video_duration(video_path)
    if duration == 0:
        print(f"❌ Cannot get duration for {video_path}")
        return []
    
    print(f"📹 Video duration: {duration:.2f} seconds")
    
    # Simple clip extraction - can be enhanced with motion detection or audio analysis
    clips = []
    segment_duration = duration / (num_clips + 1)
    
    for i in range(num_clips):
        start_time = (i + 0.5) * segment_duration  # Start in middle of each segment
        clip_duration = min(CONFIG["max_clip_duration"], duration - start_time)
        
        if clip_duration < CONFIG["min_clip_duration"]:
            continue
        
        clips.append({
            "start_time": start_time,
            "duration": clip_duration,
            "end_time": start_time + clip_duration
        })
    
    print(f"✂️ Generated {len(clips)} clips from video")
    return clips

def process_downloads():
    """Main download function - gets videos and creates clips"""
    print("\n" + "="*60)
    print("📥 DOWNLOAD MODE: Downloading videos and creating clips")
    print("="*60)
    
    setup_directories()
    queue = load_queue()
    
    # Get video URLs from user or config
    video_urls = get_video_urls()
    
    if not video_urls:
        print("❌ No video URLs provided")
        return
    
    new_clips = []
    
    for url in video_urls:
        print(f"\n🎬 Processing: {url}")
        
        # Generate unique hash for this video
        import hashlib
        video_hash = hashlib.md5(url.encode()).hexdigest()
        
        # Create folder for this video's clips
        video_folder = os.path.join(CONFIG["output_dir"], video_hash)
        os.makedirs(video_folder, exist_ok=True)
        
        # Download video
        video_path = os.path.join(video_folder, f"source_{video_hash}.mp4")
        downloaded_path = download_video(url, video_path)
        
        if not downloaded_path or not os.path.exists(downloaded_path):
            print(f"❌ Failed to download: {url}")
            continue
        
        # Extract clips
        clips = extract_clips(downloaded_path, CONFIG["clips_per_video"])
        
        for idx, clip in enumerate(clips):
            clip_info = {
                "source_video_hash": video_hash,
                "source_video_path": downloaded_path,
                "source_video_name": f"video_{video_hash}",
                "clip_index": idx + 1,
                "start_time": clip["start_time"],
                "duration": clip["duration"],
                "end_time": clip["end_time"]
            }
            new_clips.append(clip_info)
        
        print(f"✅ Created {len(clips)} clips from this video")
    
    # Add new clips to queue
    queue["pending_clips"].extend(new_clips)
    save_queue(queue)
    
    print(f"\n✅ Download complete!")
    print(f"📊 Total pending clips: {len(queue['pending_clips'])}")
    print(f"📊 Next part number: {queue['next_part_number']}")

def get_video_urls():
    """Get video URLs from user input or environment"""
    # Method 1: Environment variable
    urls_env = os.environ.get("VIDEO_URLS", "")
    if urls_env:
        return [url.strip() for url in urls_env.split(",") if url.strip()]
    
    # Method 2: From file
    urls_file = "video_urls.txt"
    if os.path.exists(urls_file):
        with open(urls_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            if urls:
                return urls
    
    # Method 3: Command line input (for manual runs)
    print("\n📝 Enter YouTube video URLs (one per line, empty line to finish):")
    urls = []
    while True:
        url = input().strip()
        if not url:
            break
        urls.append(url)
    
    return urls

def create_clip_video(clip_info, output_path):
    """Create a clip video using ffmpeg"""
    source = clip_info["source_video_path"]
    start = clip_info["start_time"]
    duration = clip_info["duration"]
    
    cmd = [
        "ffmpeg",
        "-i", source,
        "-ss", str(start),
        "-t", str(duration),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-movflags", "+faststart",
        "-y",  # Overwrite output
        output_path
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg error: {e.stderr}")
        return False

def upload_to_youtube(video_path, title, description, tags=None):
    """Upload a video to YouTube"""
    if not GOOGLE_IMPORTS_AVAILABLE:
        print("❌ Google API libraries not available")
        return False
    
    creds = None
    
    # Load credentials from environment variables
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    
    if client_id and client_secret and refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )
    
    # If no credentials, try to load from file
    if not creds and os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    # If still no credentials, try to create new
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("❌ No valid credentials. Please set up OAuth.")
            return False
    
    try:
        youtube = build("youtube", "v3", credentials=creds)
        
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags or [],
                "categoryId": "22"  # 22 = Blogging/Crime
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        response = request.execute()
        print(f"✅ Uploaded! Video ID: {response['id']}")
        print(f"🔗 https://www.youtube.com/watch?v={response['id']}")
        return True
        
    except HttpError as e:
        print(f"❌ YouTube API error: {e}")
        return False

def upload_clips(max_uploads=None):
    """Upload clips from queue, optionally limiting count"""
    print("\n" + "="*60)
    print("📤 UPLOAD MODE: Uploading videos to YouTube")
    print("="*60)
    
    queue = load_queue()
    pending = queue.get("pending_clips", [])
    
    if not pending:
        print("✅ No pending clips to upload")
        return 0
    
    # Determine how many to upload
    if max_uploads is None:
        upload_count = len(pending)
    else:
        upload_count = min(max_uploads, len(pending))
    
    print(f"📊 Total pending: {len(pending)}")
    print(f"📤 Will upload: {upload_count} video(s)")
    
    uploaded = 0
    failed = 0
    
    for i in range(upload_count):
        clip = pending[i]
        
        print(f"\n📹 Processing clip #{i+1}")
        
        # Check if source video exists
        if not os.path.exists(clip["source_video_path"]):
            print(f"❌ Source video missing: {clip['source_video_path']}")
            failed += 1
            continue
        
        # Create output clip
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clip_filename = f"clip_{clip['source_video_hash']}_{clip['clip_index']}_{timestamp}.mp4"
        clip_path = os.path.join("output_clips", clip_filename)
        
        print(f"✂️ Creating clip: {clip_path}")
        if not create_clip_video(clip, clip_path):
            print(f"❌ Failed to create clip")
            failed += 1
            continue
        
        # Generate title and description
        part_num = queue["next_part_number"]
        title = f"Seattle Police Bodycam - Part #{part_num}"
        description = f"""Seattle Police Department body camera footage.

Part #{part_num} of our ongoing series showing police interactions.

⚠️ Disclaimer: This footage is for educational purposes.
#SeattlePD #Bodycam #PoliceFootage"""
        
        tags = ["SeattlePD", "Bodycam", "Police", "Washington"]
        
        # Upload to YouTube
        print(f"📤 Uploading to YouTube...")
        if upload_to_youtube(clip_path, title, description, tags):
            uploaded += 1
            queue["uploaded_clips"].append(clip)
            queue["next_part_number"] += 1
        else:
            failed += 1
            continue
        
        # Clean up clip file
        try:
            os.remove(clip_path)
        except:
            pass
    
    # Remove uploaded clips from pending
    queue["pending_clips"] = pending[upload_count:]
    save_queue(queue)
    
    print("\n" + "="*60)
    print(f"✅ Upload complete!")
    print(f"📤 Uploaded: {uploaded}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Remaining in queue: {len(queue['pending_clips'])}")
    print(f"📊 Next part number: {queue['next_part_number']}")
    print("="*60)
    
    return uploaded

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Seattle PD YouTube Shorts Bot")
    parser.add_argument(
        "--mode", 
        choices=["download", "upload", "full", "download-only", "upload-only"],
        default="full",
        help="Run mode: download, upload, or full (both)"
    )
    parser.add_argument(
        "--limit", 
        type=int,
        help="Max videos to upload (upload mode only)"
    )
    
    args = parser.parse_args()
    
    print("\n" + "🎬"*15)
    print("SEATTLE PD YOUTUBE SHORTS BOT")
    print("🎬"*15)
    
    if args.mode in ["download", "full"]:
        process_downloads()
    
    if args.mode in ["upload", "full"]:
        upload_clips(max_uploads=args.limit)
    
    print("\n" + "="*60)
    print("✅ BOT FINISHED")
    print("="*60)

if __name__ == "__main__":
    main()
