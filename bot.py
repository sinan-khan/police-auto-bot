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

MIN_DURATION = 15
MAX_DURATION = 55
SPEED = 1.15
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
STATE_FILE = "upload_state.json"
UPLOAD_PER_RUN = 2

def get_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())

def edit_for_shorts(input_path, output_path, part_num):
    filters = (
        "crop=ih*9/16:ih,"
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
        "zoompan=z='min(zoom+0.002,1.15)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    )
    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-vf", filters,
        "-af", f"atempo={SPEED}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "30", "-y", str(output_path)
    ]
    subprocess.run(cmd, check=True)

def split_and_edit(input_path, output_dir):
    base = Path(input_path).stem
    duration = get_duration(input_path)
    output_dir.mkdir(exist_ok=True)
    clips = []
    
    current_pos = 0
    clip_index = 0
    
    while current_pos < duration - 10:
        remaining = duration - current_pos
        clip_len = min(random.randint(MIN_DURATION, MAX_DURATION), remaining)
        
        final_clip = output_dir / f"{base}_short_{clip_index:03d}.mp4"
        if final_clip.exists():
            clips.append(final_clip)
            current_pos += clip_len
            clip_index += 1
            continue
            
        temp_clip = output_dir / f"{base}_temp_{clip_index:03d}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(current_pos), "-t", str(clip_len),
            "-i", input_path, "-c", "copy", str(temp_clip)
        ], check=True)
        
        edit_for_shorts(temp_clip, final_clip, clip_index + 1)
        temp_clip.unlink()
        clips.append(final_clip)
        
        current_pos += clip_len
        clip_index += 1
    
    return clips

def generate_title(base_title, part_num):
    hooks = [
        "You WON'T BELIEVE This {} 😱 #shorts",
        "This {} Changed Everything 🔥 #shorts",
        "Nobody Expected This {} Part#{} #shorts",
        "Wait For It... {} Part#{} 😮 #shorts"
    ]
    hook = random.choice(hooks)
    title = hook.format(base_title, part_num) if "Part#{}" in hook else hook.format(base_title)
    return title[:100]

def upload_video(file_path, title):
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    youtube = build("youtube", "v3", credentials=creds)
    
    body = {
        "snippet": {
            "title": title,
            "description": f"{title}\n\n#shorts #viral #fyp",
            "tags": ["shorts", "viral", "fyp", "trending"],
            "categoryId": "24"
        },
        "status": {"privacyStatus": "public"}
    }
    
    media = MediaFileUpload(str(file_path), resumable=True)
    response = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    ).execute()
    print(f"Uploaded: https://youtube.com/shorts/{response['id']}")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"uploaded_files": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def download_with_gdown(link, output_file):
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', link)
    direct_link = f"https://drive.google.com/uc?id={match.group(1)}" if match else link
    subprocess.run(["gdown", "--fuzzy", direct_link, "-O", output_file], check=True)

def main():
    Path("clips").mkdir(exist_ok=True)
    state = load_state()
    
    with open("drive_links.txt") as f:
        line = f.readline().strip()
        if " | " in line:
            link, base_title = line.split(" | ", 1)
        else:
            link, base_title = line, "Video"
    
    input_file = "input.mp4"
    if not os.path.exists(input_file):
        download_with_gdown(link, input_file)
    
    clips = split_and_edit(input_file, Path("clips"))
    uploaded = 0
    
    for clip in clips:
        if clip.name in state["uploaded_files"]:
            continue
        if uploaded >= UPLOAD_PER_RUN:
            break
            
        part_num = int(clip.stem.split("_")[-1]) + 1
        title = generate_title(base_title, part_num)
        
        print(f"Uploading Short {title}...")
        upload_video(clip, title)
        
        state["uploaded_files"].append(clip.name)
        uploaded += 1
    
    save_state(state)
    print(f"Uploaded {uploaded} shorts this run.")

if __name__ == "__main__":
    main()
