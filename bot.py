import os, json, random, glob, subprocess
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

LINKS_FILE = "links.txt"
QUEUE_FILE = "upload_queue.json"
TEMP_FOLDER = "temp_downloads"
CHUNK_DURATION = 45

def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, 'r') as f:
            return json.load(f)
    return {"pending": [], "uploaded": []}

def save_queue(queue):
    with open(QUEUE_FILE, 'w') as f:
        json.dump(queue, f, indent=2)

def download_video(url):
    """Download video from YouTube using yt-dlp"""
    os.makedirs(TEMP_FOLDER, exist_ok=True)
    output_path = f"{TEMP_FOLDER}/video_%(id)s.%(ext)s"
    
        cmd = [
    "yt-dlp",
    "-f", "best[height<=720][ext=mp4]/best[ext=mp4]/best",
    "-o", output_path,
    "--no-playlist",
    "--cookies", "cookies.txt",
    "--extractor-args", "youtube:player_client=tv_embedded,android",
    "--user-agent", "com.google.android.youtube/19.09.37(Linux; U; Android 11) gzip",
    "--sleep-requests", "2",
    url
]
    
    print(f"Running yt-dlp on: {url}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print("STDOUT:", result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    if result.returncode!= 0:
        print(f"Download failed with code {result.returncode}")
        return None
    
    files = glob.glob(f"{TEMP_FOLDER}/*.mp4")
    print(f"Found files: {files}")
    return files[0] if files else None

def split_video_to_queue(filepath, source_url):
    """Split downloaded video and add to queue"""
    filename = os.path.basename(filepath)
    print(f"Splitting: {filename}")
    clip = VideoFileClip(filepath)
    total_duration = clip.duration
    chunks = int(total_duration // CHUNK_DURATION)
    if total_duration % CHUNK_DURATION > 10: chunks += 1
    
    queue = load_queue()
    for i in range(chunks):
        start = i * CHUNK_DURATION
        end = min(start + CHUNK_DURATION, total_duration)
        if end - start < 10: continue
        queue["pending"].append({
            "source_file": filepath,
            "source_name": filename,
            "source_url": source_url,
            "part": i + 1,
            "total_parts": chunks,
            "start_time": start,
            "end_time": end
        })
    save_queue(queue)
    print(f"Added {chunks} parts to queue. Queue size: {len(queue['pending'])}")
    return True

def make_short_from_queue_item(item):
    clip = VideoFileClip(item["source_file"])
    part_clip = clip.subclip(item["start_time"], item["end_time"])
    w, h = part_clip.size
    target_w = int(h * 9 / 16)
    x1 = max(0, (w - target_w) // 2)
    part_clip = part_clip.crop(x1=x1, x2=x1+target_w).resize(height=1920)
    
    title = random.choice(["SEATTLE PD BODY CAM", "SPD INCIDENT", "SEATTLE POLICE"])
    img = Image.new('RGBA', (1080, 350), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    try: 
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
    except: 
        font = ImageFont.load_default()
    
    x, y = 540, 150
    for dx, dy in [(-3,-3),(-3,3),(3,-3),(3,3)]:
        draw.text((x+dx, y+dy), title, font=font, fill="black", anchor="mm")
    draw.text((x, y), title, font=font, fill="white", anchor="mm")
    draw.text((x, y+85), f"PART {item['part']}/{item['total_parts']}", font=font, fill="yellow", anchor="mm")
    
    img.save("text.png")
    text_clip = ImageClip("text.png").set_duration(part_clip.duration).set_position(('center', 100))
    final = CompositeVideoClip([part_clip, text_clip])
    final.write_videofile("short.mp4", fps=30, codec="libx264", audio_codec="aac", threads=4, logger=None)
    
    if os.path.exists("text.png"): os.remove("text.png")
    return True

def upload_short(item):
    if not os.path.exists("short.mp4"): return False
    token_info = json.loads(os.environ['YT_TOKEN'])
    client_data = json.loads(os.environ['CLIENT_SECRET'])
    client_info = client_data.get('web') or client_data.get('installed')
    creds = Credentials(token_info['token'], refresh_token=token_info['refresh_token'], token_uri=client_info['token_uri'], client_id=client_info['client_id'], client_secret=client_info['client_secret'])
    youtube = build('youtube', 'v3', credentials=creds)
    
    title = f"Seattle PD Bodycam Part {item['part']} #shorts #seattlepd"
    desc = f"""Seattle Police Department body camera footage - Part {item['part']}/{item['total_parts']}

Source: Seattle Police Department YouTube Channel
Public Record - Washington State Public Records Act
Edited to 9:16 format.

Original: {item['source_url']}

#seattlepd #bodycam #police #lawenforcement #shorts"""
    
    request = youtube.videos().insert(
        part="snippet,status",
        body={"snippet": {"title": title, "description": desc, "tags": ["seattle pd","bodycam","police","shorts"], "categoryId": "25"}, "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}},
        media_body=MediaFileUpload("short.mp4", chunksize=-1, resumable=True)
    )
    response = request.execute()
    print(f"Uploaded: https://youtube.com/shorts/{response['id']}")
    return True

def cleanup_temp():
    """Delete downloaded videos to save space"""
    if os.path.exists(TEMP_FOLDER):
        for f in glob.glob(f"{TEMP_FOLDER}/*"):
            os.remove(f)
        print("Cleaned temp files")

if __name__ == "__main__":
    # MODE 1: Manual run - process new links from links.txt
    if os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch':
        if not os.path.exists(LINKS_FILE):
            print("No links.txt found. Create it and add YouTube URLs, 1 per line.")
            exit()
        
        with open(LINKS_FILE, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
        queue = load_queue()
        processed_urls = {item['source_url'] for item in queue['pending'] + queue['uploaded']}
        
        for url in urls:        processed_urls = []
        for url in urls:
            if url not in processed_urls:
                video_path = download_video(url)
                if video_path:
                    split_video_to_queue(video_path, url)
                    processed_urls.append(url) # Add this line
                else:
                    print(f"Failed to download: {url}")
            if url not in processed_urls:
                video_path = download_video(url)
                if video_path:
                    split_video_to_queue(video_path, url)
        
                # Only clear links.txt if we successfully processed at least 1 video
        if processed_urls:
            with open(LINKS_FILE, 'w') as f:
                f.write("# Add YouTube URLs here, one per line\n")
            print("Cleared links.txt after successful processing")
        else:
            print("No videos processed. links.txt unchanged for retry.")
        
        print("Splitting complete. Queue updated.")
        exit()
    
    # MODE 2: Scheduled run - upload 1 item from queue
    queue = load_queue()
    if not queue["pending"]:
        print("Queue empty. Add URLs to links.txt and run manually.")
        cleanup_temp()
        exit()
    
    item = queue["pending"].pop(0)
    print(f"Processing: {item['source_name']} Part {item['part']}")
    
    # Re-download if file was deleted
    if not os.path.exists(item["source_file"]):
        item["source_file"] = download_video(item["source_url"])
    
    if item["source_file"] and make_short_from_queue_item(item):
        if upload_short(item):
            queue["uploaded"].append(item)
            save_queue(queue)
    
    if os.path.exists("short.mp4"): os.remove("short.mp4")
    
    # If queue empty after this, cleanup
    if not queue["pending"]:
        cleanup_temp()
