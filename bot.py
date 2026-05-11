import os
import subprocess
import json
from moviepy.editor import VideoFileClip

TEMP_DOWNLOAD_DIR = "temp_downloads"
LINKS_FILE = "links.txt"
QUEUE_FILE = "queue.json"
OUTPUT_DIR = "output_videos"

os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, 'r') as f:
            return json.load(f)
    return {"videos": [], "current": 0}

def save_queue(queue):
    with open(QUEUE_FILE, 'w') as f:
        json.dump(queue, f, indent=2)

def get_links():
    if not os.path.exists(LINKS_FILE):
        return []
    with open(LINKS_FILE, 'r') as f:
        return [line.strip() for line in f if line.strip()]

def download_video(url, video_id):
    output_path = os.path.join(TEMP_DOWNLOAD_DIR, f"video_{video_id}.mp4")
    cmd = [
    "yt-dlp",
    "-f", "best[height<=720][ext=mp4]/best[ext=mp4]/best",
    "-o", output_path,
    "--no-playlist",
    "--cookies", "cookies.txt",
    "--extractor-args", "youtube:player_client=mweb,web",
    "--user-agent", "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "--sleep-requests", "3",
    "--sleep-interval", "5",
    "--max-sleep-interval", "10",
    "--no-check-certificates",
    "--force-ipv4",
    url
]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    
    if result.returncode!= 0:
        print(f"Download failed with code {result.returncode}")
        return None
        
    if os.path.exists(output_path):
        return output_path
    else:
        print("File not found after download")
        return None

def split_video(input_path, video_id):
    clip = VideoFileClip(input_path)
    duration = clip.duration
    part = 1
    
    for start in range(0, int(duration), 60):
        end = min(start + 60, duration)
        if end - start < 10:
            continue
            
        subclip = clip.subclip(start, end)
        output_file = os.path.join(OUTPUT_DIR, f"{video_id}_part{part}.mp4")
        subclip.write_videofile(output_file, codec="libx264", audio_codec="aac", verbose=False, logger=None)
        print(f"Saved: {output_file}")
        part += 1
    
    clip.close()

def main():
    links = get_links()
    if not links:
        print("No links found in links.txt")
        return
    
    for link in links:
        print(f"Running yt-dlp on: {link}")
        video_id = link.split("v=")[-1].split("&")[0]
        video_path = download_video(link, video_id)
        
        if video_path:
            print(f"Found files: ['{video_path}']")
            split_video(video_path, video_id)
            os.remove(video_path)
        else:
            print(f"Failed to download: {link}")
    
    print("Splitting complete. Queue updated")

if __name__ == "__main__":
    main()
