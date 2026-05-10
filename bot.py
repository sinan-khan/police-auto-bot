import os, json, random, requests
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

def download_video():
    headers = {"Authorization": os.environ['PEXELS_KEY']}
    queries = ["police car", "police officer", "law enforcement", "cop car"]
    
    for query in queries:
        try:
            r = requests.get(f"https://api.pexels.com/videos/search?query={query}&per_page=15", headers=headers)
            videos = r.json()['videos']
            random.shuffle(videos)
            
            for vid in videos:
                video_files = [v for v in vid['video_files'] if v['height'] <= 720 and v['file_type'] == 'video/mp4']
                if not video_files: continue
                
                video_url = video_files[0]['link']
                print(f"Downloading: {vid['id']}")
                
                r = requests.get(video_url, stream=True, timeout=60)
                if r.status_code == 200:
                    with open("source.mp4", "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            f.write(chunk)
                    if os.path.getsize("source.mp4") > 1000000:
                        info = {"title": "Police Stock Footage", "uploader": "Pexels", "id": vid['id']}
                        with open('source_info.json', 'w') as f:
                            json.dump(info, f)
                        print("Download success")
                        return True
        except Exception as e:
            print(f"Pexels search failed: {e}")
            continue
    return False

def make_short():
    if not os.path.exists("source.mp4"): return False
    
    clip = VideoFileClip("source.mp4")
    duration = min(58, clip.duration)
    clip = clip.subclip(0, duration)
    
    w, h = clip.size
    target_w = int(h * 9 / 16)
    x1 = max(0, (w - target_w) // 2)
    clip = clip.crop(x1=x1, x2=x1+target_w).resize(height=1920)
    
    titles = ["POLICE ON PATROL", "COP CAR FOOTAGE", "LAW ENFORCEMENT", "POLICE ACTIVITY"]
    title = random.choice(titles)
    
    img = Image.new('RGBA', (1080, 300), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    try: 
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 90)
    except: 
        font = ImageFont.load_default()
    
    x, y = 540, 150
    for dx, dy in [(-4,-4),(-4,4),(4,-4),(4,4)]:
        draw.text((x+dx, y+dy), title, font=font, fill="black", anchor="mm")
    draw.text((x, y), title, font=font, fill="white", anchor="mm")
    
    img.save("text.png")
    text_clip = ImageClip("text.png").set_duration(clip.duration).set_position(('center', 100))
    
    final = CompositeVideoClip([clip, text_clip])
    final.write_videofile("short.mp4", fps=30, codec="libx264", audio_codec="aac", threads=4, logger=None)
    
    if os.path.exists("text.png"): os.remove("text.png")
    return True

def make_thumb():
    if not os.path.exists("source.mp4"): return
    VideoFileClip("source.mp4").save_frame("frame.png", t=2)
    img = Image.open("frame.png").convert("RGB")
    w, h = img.size
    target_w = int(h * 9 / 16)
    x1 = max(0, (w - target_w) // 2)
    img = img.crop((x1, 0, x1+target_w, h)).resize((1080, 1920))
    
    draw = ImageDraw.Draw(img)
    try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 95)
    except: font = ImageFont.load_default()
    
    text = "POLICE\nFOOTAGE"
    bbox = draw.multiline_textbbox((0,0), text, font=font)
    x = (1080 - (bbox[2]-bbox[0])) // 2
    y = 150
    for dx, dy in [(-4,-4),(-4,4),(4,-4),(4,4)]:
        draw.multiline_text((x+dx, y+dy), text, font=font, fill="black", align="center")
    draw.multiline_text((x, y), text, font=font, fill="white", align="center")
    img.save("thumb.jpg", quality=95)

def upload():
    if not os.path.exists("short.mp4"): return
    
    token_info = json.loads(os.environ['YT_TOKEN'])
    client_data = json.loads(os.environ['CLIENT_SECRET'])
    
    if 'web' in client_data:
        client_info = client_data['web']
    elif 'installed' in client_data:
        client_info = client_data['installed']
    
    creds = Credentials(
        token_info['token'],
        refresh_token=token_info['refresh_token'],
        token_uri=client_info['token_uri'],
        client_id=client_info['client_id'],
        client_secret=client_info['client_secret']
    )
    
    youtube = build('youtube', 'v3', credentials=creds)
    
    title = f"POLICE PATROL FOOTAGE #shorts #police"
    desc = f"Law enforcement footage. Source: Pexels CC0 License\n\n#police #cops #lawenforcement #shorts"
    
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": desc, "tags": ["police","shorts","cops"], "categoryId": "25"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
        },
        media_body=MediaFileUpload("short.mp4", chunksize=-1, resumable=True)
    )
    response = request.execute()
    vid_id = response['id']
    print(f"Uploaded as: https://youtube.com/shorts/{vid_id}")
    
    # Try thumbnail, ignore if no permission
    if os.path.exists("thumb.jpg"):
        try:
            youtube.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload("thumb.jpg")).execute()
            print("Thumbnail set")
        except Exception as e:
            print(f"Thumbnail skipped - verify phone at youtube.com/verify"))

if __name__ == "__main__":
    if download_video():
        if make_short():
            make_thumb() 
            upload()
    else:
        print("No video found")
