import os, json, random, requests
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

def download_video():
    urls = [
        "https://archive.org/download/Cops.Compilation.1990s/Cops%20Compilation%201990s.mp4",
        "https://archive.org/download/KansasCityPoliceFootage/Kansas%20City%20Police%20Footage.mp4",
        "https://archive.org/download/PoliceDashCamCompilation2017/Police%20Dash%20Cam%20Compilation%202017.mp4"
    ]
    
    for url in urls:
        try:
            print(f"Trying: {url}")
            r = requests.get(url, stream=True, timeout=60)
            if r.status_code == 200:
                with open("source.mp4", "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        f.write(chunk)
                if os.path.getsize("source.mp4") > 5000000: # >5MB = real video
                    info = {"title": "Police Footage Archive", "uploader": "Archive.org", "id": "archive"}
                    with open('source_info.json', 'w') as f:
                        json.dump(info, f)
                    print("Download success")
                    return True
                else:
                    print("File too small, trying next")
            else:
                print(f"HTTP {r.status_code}")
        except Exception as e:
            print(f"Failed {url}: {e}")
            continue
    return False

def make_short():
    if not os.path.exists("source.mp4"): return False
    clip = VideoFileClip("source.mp4").subclip(0, min(58, VideoFileClip("source.mp4").duration))
    w, h = clip.size
    target_w = int(h * 9 / 16)
    x1 = max(0, (w - target_w) // 2)
    clip = clip.crop(x1=x1, x2=x1+target_w).resize(height=1920)
    
    titles = ["SHOCKING POLICE STOP", "UNBELIEVABLE ARREST", "COPS CAUGHT THIS", "POLICE CHASE FOOTAGE"]
    title = random.choice(titles)
    
    txt = TextClip(title, fontsize=110, color='white', font='Arial-Bold', stroke_color='black', stroke_width=6, method='caption', size=(1000, None))
    txt = txt.set_position(('center', 100)).set_duration(clip.duration)
    
    final = CompositeVideoClip([clip, txt])
    final.write_videofile("short.mp4", fps=30, codec="libx264", audio_codec="aac", threads=4, logger=None)
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
    try: font = ImageFont.truetype("arialbd.ttf", 95)
    except: font = ImageFont.load_default()
    
    text = "POLICE\nENCOUNTER"
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
    client_info = json.loads(os.environ['CLIENT_SECRET'])['web']
    creds = Credentials(
        token_info['token'],
        refresh_token=token_info['refresh_token'],
        token_uri=client_info['token_uri'],
        client_id=client_info['client_id'],
        client_secret=client_info['client_secret']
    )
    
    youtube = build('youtube', 'v3', credentials=creds)
    
    with open('source_info.json', 'r') as f:
        info = json.load(f)
    
    title = f"INSANE POLICE ENCOUNTER #shorts #police"
    desc = f"Police bodycam footage. Source: Archive.org Public Domain\n\n#police #bodycam #cops #lawenforcement #shorts"
    
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": desc, "tags": ["police","bodycam","shorts"], "categoryId": "25"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
        },
        media_body=MediaFileUpload("short.mp4", chunksize=-1, resumable=True)
    )
    response = request.execute()
    vid_id = response['id']
    
    if os.path.exists("thumb.jpg"):
        youtube.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload("thumb.jpg")).execute()
    
    print(f"Uploaded as: https://youtube.com/shorts/{vid_id}")

if __name__ == "__main__":
    if download_video():
        make_short()
        make_thumb() 
        upload()
    else:
        print("No video found")
