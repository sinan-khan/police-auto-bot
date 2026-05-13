import os, json, subprocess, gdown
from pathlib import Path
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
import pytz

VIDEOS_DIR = Path("videos")
CLIPS_DIR = Path("clips")
QUEUE_FILE = Path("queue.json")
DRIVE_LINKS_FILE = Path("drive_links.txt")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
PK_TZ = pytz.timezone("Asia/Karachi")
POST_TIMES_PK = ["18:00", "03:00"] # 6PM PKT = 9AM EST, 3AM PKT = 6PM EST

def get_youtube_service():
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    return build("youtube", "v3", credentials=creds)

def download_from_drive():
    if not DRIVE_LINKS_FILE.exists():
        return False
    links = [l.strip() for l in DRIVE_LINKS_FILE.read_text().splitlines() if l.strip()]
    if not links:
        return False

    VIDEOS_DIR.mkdir(exist_ok=True)
    url = links[0]
    print(f"Downloading from Google Drive: {url}")
    output = VIDEOS_DIR / "downloaded_video.mp4"

    try:
        gdown.download(url, str(output), quiet=False, fuzzy=True)
        # Remove link after successful download so we don't re-download
        DRIVE_LINKS_FILE.write_text("\n".join(links[1:]))
        print("Download complete")
        return True
    except Exception as e:
        print(f"Drive download failed: {e}")
        return False

def edit_for_copyright(input_path, output_path, part_num):
    filters = (
        "hflip,"
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
        "drawtext=text='Part\\#{}':fontcolor=white:fontsize=48:"
        "box=1:boxcolor=black@0.5:boxborderw=10:x=50:y=50"
    ).format(part_num)

    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-vf", filters,
        "-af", "atempo=1.15",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-y", str(output_path)
    ]
    subprocess.run(cmd, check=True)

def split_and_edit(video_path):
    CLIPS_DIR.mkdir(exist_ok=True)
    temp_dir = Path("temp")
    temp_dir.mkdir(exist_ok=True)

    split_pattern = temp_dir / f"{video_path.stem}_temp_%03d.mp4"
    subprocess.run([
        "ffmpeg", "-i", str(video_path),
        "-c", "copy", "-map", "0", "-segment_time", "59",
        "-f", "segment", "-reset_timestamps", "1", str(split_pattern)
    ], check=True)

    for temp_clip in sorted(temp_dir.glob("*.mp4")):
        final_clip = CLIPS_DIR / f"{video_path.stem}_edit_{temp_clip.stem[-3:]}.mp4"
        part_num = int(temp_clip.stem[-3:]) + 1
edit_for_copyright(temp_clip, final_clip, part_num)
        temp_clip.unlink()

    temp_dir.rmdir()
    video_path.unlink()

def generate_metadata(filename):
    num = filename.split("_edit_")[-1].replace(".mp4","")
    base = filename.split("_edit_")[0].replace("_"," ")
    title = f"{base} Bodycam Part {num} | Police Footage"
    desc = f"""Seattle PD bodycam footage for news & educational purposes.
Full video source: Public records.

#police #bodycam #seattle #news"""
    tags = ["police", "bodycam", "seattle pd", "cop", "news", "law enforcement"]
    return title, desc, tags

def load_queue():
    if QUEUE_FILE.exists():
        return json.loads(QUEUE_FILE.read_text())
    return {"processed": [], "posted": []}

def save_queue(q):
    QUEUE_FILE.write_text(json.dumps(q, indent=2))

def should_post_now():
    now_pk = datetime.now(PK_TZ)
    return now_pk.strftime("%H:%M") in POST_TIMES_PK

def upload_next_clip(youtube):
    q = load_queue()
    pending = [c for c in sorted(CLIPS_DIR.glob("*.mp4")) if str(c) not in q["posted"]]
    if not pending:
        print("Queue empty")
        return
    clip = pending[0]
    title, desc, tags = generate_metadata(clip.name)
    print(f"Uploading {clip.name}")
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": desc, "tags": tags, "categoryId": "25"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
        },
        media_body=MediaFileUpload(str(clip))
    )
    response = request.execute()
    print(f"Uploaded: https://youtube.com/watch?v={response['id']}")
    q["posted"].append(str(clip))
    save_queue(q)
    clip.unlink()

def main():
    VIDEOS_DIR.mkdir(exist_ok=True)
    CLIPS_DIR.mkdir(exist_ok=True)
    q = load_queue()

    # Step 0: Download from Drive if link exists
    download_from_drive()

    # Step 1: Process any videos in videos/ folder
    for video_file in VIDEOS_DIR.glob("*.mp4"):
        if str(video_file) not in q["processed"]:
            print(f"Processing: {video_file.name}")
            split_and_edit(video_file)
            q["processed"].append(str(video_file))
            save_queue(q)
            break

    # Step 2: Post if it's time
    if should_post_now():
        yt = get_youtube_service()
        upload_next_clip(yt)
    else:
        print(f"Not post time. Current PK: {datetime.now(PK_TZ).strftime('%H:%M')}")

if __name__ == "__main__":
    main()
