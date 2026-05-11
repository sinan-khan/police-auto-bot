import os, json, random, glob, shutil
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

VIDEO_FOLDER = "source_videos"
QUEUE_FILE = "upload_queue.json"
CHUNK_DURATION = 45

def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, 'r') as f:
            return json.load(f)
    return {"pending": [], "uploaded": []}

def save_queue(queue):
    with open(QUEUE_FILE, 'w') as f:
        json.dump(queue, f, indent=2)

def split_video_to_queue(filepath):
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

Original: {item['source_name']}

#seattlepd #bodycam #police #lawenforcement #shorts"""
    
    request = youtube.videos().insert(
        part="snippet,status",
        body={"snippet": {"title": title, "description": desc, "tags": ["seattle pd","bodycam","police","shorts"], "categoryId": "25"}, "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}},
        media_body=MediaFileUpload("short.mp4", chunksize=-1, resumable=True)
    )
    response = request.execute()
    print(f"Uploaded: https://youtube.com/shorts/{response['id']}")
    return True

if __name__ == "__main__":
    os.makedirs(VIDEO_FOLDER, exist_ok=True)
    if os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch':
        new_videos = glob.glob(f"{VIDEO_FOLDER}/*.mp4")
        queue = load_queue()
        already_queued = {item['source_file'] for item in queue['pending'] + queue['uploaded']}
        for vid in new_videos:
            if vid not in already_queued:
                split_video_to_queue(vid)
        print("Splitting complete. Queue updated.")
        exit()
    
    queue = load_queue()
    if not queue["pending"]:
        print("Queue empty. Add videos to source_videos/ and run manually to split.")
        exit()
    
    item = queue["pending"].pop(0)
    print(f"Processing: {item['source_name']} Part {item['part']}")
    if make_short_from_queue_item(item):
        if upload_short(item):
            queue["uploaded"].append(item)
            save_queue(queue)
    if os.path.exists("short.mp4"): os.remove("short.mp4")
