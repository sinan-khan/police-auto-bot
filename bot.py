import os
import json
import subprocess
import random
import re
from pathlib import Path
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

CLIP_DURATION = 59
SPEED = 1.15
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
STATE_FILE = "upload_state.json"
UPLOAD_PER_DAY = 2

def get_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        raise ValueError(f"ffprobe failed. File might be empty: {path}")
    return float(result.stdout.strip())

def edit_for_copyright(input_path, output_path, part_num):
    filters = (
        "hflip,"
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
        "drawtext=text='Part\\#{}':fontcolor=white:fontsize=48:"
        "box=1:boxcolor=black@0.5:boxborderw=10:x=50:y=h-100"
    ).format(part_num)

    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-vf", filters,
        "-af", f"atempo={SPEED}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-y", str(output_path)
    ]
    subprocess.run(cmd, check=True)

def split_and_edit(input_path, output_dir):
    base = Path(input_path).stem
    duration = get_duration(input_path)
    segments = [(i, min(i+CLIP_DURATION, duration)) for i in range(0, int(duration), CLIP_DURATION)]
    
    output_dir.mkdir(exist_ok=True)
    clips = []
    
    for i, (start, end) in enumerate(segments):
        final_clip = output_dir / f"{base}_edit_{i:03d}.mp4"
        if final_clip.exists():
            clips.append(final_clip)
            continue
            
        temp_clip = output_dir / f"{base}_temp_{i:03d}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(start), "-to", str(end),
            "-i", input_path, "-c", "copy", str(temp_clip)
        ], check=True)
        
        part_num = i + 1
        edit_for_copyright(temp_clip, final_clip, part_num)
        temp_clip.unlink()
        clips.append(final_clip)
    
    return clips

def generate_viral_title(base_title, part_num):
    hooks = [
        "You WON'T BELIEVE This {} 😱",
        "This {} Changed Everything 🔥",
        "Nobody Expected This {} Part#{}",
        "Wait For It... {} Part#{} 😮"
    ]
    hook = random.choice(hooks)
    title = hook.format(base_title, part_num) if "Part#{}" in hook else hook.format(base_title)
    return title[:100]

def generate_description(base_title, part_num):
    return f"""{base_title} - Part#{part_num}

🔔 Subscribe for more! New parts daily at 5AM PKT
👍 Like if you enjoyed this part
💬 Comment what you want to see next

#shorts #viral #fyp
"""

def generate_tags(base_title):
    base_tags = ["shorts", "viral", "fyp", "trending"]
    words = [w for w in base_title.split() if len(w) > 3]
    return base_tags + words[:8]

def upload_video(file_path, title, description, tags):
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    youtube = build("youtube", "v3", credentials=creds)
    
    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "24"
        },
        "status": {"privacyStatus": "public"}
    }
    
    media = MediaFileUpload(str(file_path), resumable=True)
    response = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media
    ).execute()
    print(f"Uploaded: https://youtu.be/{response['id']}")
    return response['id']

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"uploaded_count": 0, "last_run_date": "", "uploaded_files": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def download_with_gdown(link, output_file):
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', link)
    if match:
        file_id = match.group(1)
        direct_link = f"https://drive.google.com/uc?id={file_id}"
    else:
        direct_link = link
    
    print(f"Downloading from: {direct_link}")
    subprocess.run(["gdown", "--fuzzy", direct_link, "-O", output_file], check=True)
    
    if os.path.getsize(output_file) < 1000000:
        raise Exception("Downloaded file too small. Check if Drive link is public.")

def main():
    Path("clips").mkdir(exist_ok=True)
    
    state = load_state()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    
    # Reset counter if it's a new UTC day
    if state["last_run_date"] != today:
        state["uploaded_count"] = 0
        state["last_run_date"] = today
    
    # Stop if we already uploaded 2 today
    if state["uploaded_count"] >= UPLOAD_PER_DAY:
        print(f"Already uploaded {state['uploaded_count']} videos today. Stopping.")
        return
    
    with open("drive_links.txt") as f:
        line = f.readline().strip()
        if not line:
            print("drive_links.txt is empty")
            return
        if " | " in line:
            link, base_title = line.split(" | ", 1)
        else:
            link = line
            base_title = "Video"
    
    input_file = "input.mp4"
    if not os.path.exists(input_file):
        download_with_gdown(link, input_file)
    
    clips = split_and_edit(input_file, Path("clips"))
    
    uploaded_today = 0
    for clip in clips:
        if state["uploaded_count"] + uploaded_today >= UPLOAD_PER_DAY:
            print(f"Reached daily limit of {UPLOAD_PER_DAY} uploads. Stopping.")
            break
            
        if clip.name in state["uploaded_files"]:
            continue
            
        part_num = int(clip.stem.split("_")[-1]) + 1
        title = generate_viral_title(base_title, part_num)
        description = generate_description(base_title, part_num)
        tags = generate_tags(base_title)
        
        print(f"Uploading {title}...")
        upload_video(clip, title, description, tags)
        
        state["uploaded_files"].append(clip.name)
        uploaded_today += 1
    
    state["uploaded_count"] += uploaded_today
    save_state(state)
    print(f"Uploaded {uploaded_today} videos today. Total today: {state['uploaded_count']}")

if __name__ == "__main__":
    main()
