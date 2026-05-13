import os
import subprocess
import random
import re
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Settings
CLIP_DURATION = 59
SPEED = 1.15
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())

def edit_for_copyright(input_path, output_path, part_num):
    filters = (
        "hflip,"
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
        "drawtext=text='Part\\#{}':fontcolor=white:fontsize=48:"
        "box=1:boxcolor=black@0.5:boxborderw=10:x=50:y=50:x=(w-text_w)/2:y=h-100"
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
        temp_clip = output_dir / f"{base}_temp_{i:03d}.mp4"
        final_clip = output_dir / f"{base}_edit_{i:03d}.mp4"
        
        # Cut clip
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(start), "-to", str(end),
            "-i", input_path, "-c", "copy", str(temp_clip)
        ], check=True)
        
        # Edit for copyright + add Part#
        part_num = i + 1
        edit_for_copyright(temp_clip, final_clip, part_num)
        clips.append(final_clip)
        temp_clip.unlink()
    
    return clips

def generate_viral_title(base_title, part_num):
    hooks = [
        "You WON'T BELIEVE This {} 😱",
        "This {} Changed Everything 🔥",
        "Nobody Expected This {} Part#{}",
        "Wait For It... {} Part#{} 😮",
        "The CRAZIEST {} You'll See Today"
    ]
    hook = random.choice(hooks)
    if "Part#{}" in hook:
        title = hook.format(base_title, part_num)
    else:
        title = hook.format(base_title)
    return title[:100]

def generate_description(base_title, part_num):
    return f"""{base_title} - Part#{part_num}

🔔 Subscribe for more! New parts daily at 6PM & 3AM PKT
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

def main():
    Path("clips").mkdir(exist_ok=True)
    Path("temp").mkdir(exist_ok=True)
    
    # Read link and title from drive_links.txt
    with open("drive_links.txt") as f:
        line = f.readline().strip()
        if " | " in line:
            link, base_title = line.split(" | ", 1)
        else:
            link = line
            base_title = "Video"
    
    # Download video with gdown
    input_file = "input.mp4"
    print(f"Downloading {link}...")
    subprocess.run(["gdown", link, "-O", input_file], check=True)
    
    # Split, edit, and upload
    clips = split_and_edit(input_file, Path("clips"))
    
    for i, clip in enumerate(clips):
        part_num = i + 1
        title = generate_viral_title(base_title, part_num)
        description = generate_description(base_title, part_num)
        tags = generate_tags(base_title)
        print(f"Uploading {title}...")
        upload_video(clip, title, description, tags)

if __name__ == "__main__":
    main()
