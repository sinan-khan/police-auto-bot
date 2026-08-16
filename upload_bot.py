import os
from datetime import datetime
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from bot_common import load_queue, save_queue, download_clip_asset, delete_clip_asset

# ============= CONFIGURATION =============
DOWNLOAD_DIR = "shorts_ready"
VIDEOS_PER_RUN = 1  # this workflow is scheduled twice a day -> 2 uploads/day total


def generate_metadata(part_number):
    title = f"USA Police Bodycam - PART #{part_number} #Shorts"
    description = f"""USA Police BODYCAM FOOTAGE - PART #{part_number}

Real body camera footage from Seattle Police Department (SPD)

🔔 SUBSCRIBE for more bodycam content daily!

#SeattlePolice #Bodycam #PoliceBodycam #SPD #Shorts"""
    tags = ["Seattle Police", "Bodycam", "SPD", "Police Bodycam", "Seattle PD", "Shorts"]
    return title, description, tags


def get_authenticated_service():
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        else:
            print("  ❌ No valid token found")
            return None

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(video_path, title, description, tags):
    if not os.path.exists(video_path):
        print("  ❌ Video not found")
        return None

    file_size = os.path.getsize(video_path)
    print(f"  📹 File size: {file_size/1024/1024:.2f} MB")

    youtube = get_authenticated_service()
    if not youtube:
        return None

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=1024 * 1024, resumable=True)
    print("  📤 Uploading...")

    try:
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
        video_id = response.get("id")

        if video_id:
            print(f"  ✅ UPLOADED! Shorts ID: {video_id}")
            print(f"  🔗 https://youtube.com/shorts/{video_id}")
            return video_id
        print("  ❌ No video ID returned")
        return None
    except HttpError as e:
        # Quota-exceeded and other API errors land here. We deliberately do
        # NOT remove the clip from the queue on failure (see main()) so a
        # quota error just means "try again on the next scheduled run."
        print(f"  ❌ YouTube API Error: {e}")
        return None


def main():
    print("\n" + "=" * 60)
    print("📤 UPLOAD BOT - YouTube Shorts Uploader")
    print("=" * 60)

    queue = load_queue()

    if not queue["pending_clips"]:
        print("✅ No pending clips to upload!")
        return

    print(f"📊 Next Part: #{queue['next_part_number']}")
    print(f"📊 Pending clips: {len(queue['pending_clips'])}")

    attempts = min(VIDEOS_PER_RUN, len(queue["pending_clips"]))
    print(f"\n🚀 Attempting {attempts} upload(s)...")

    succeeded = 0
    for _ in range(attempts):
        if not queue["pending_clips"]:
            break

        clip_info = queue["pending_clips"][0]
        asset_name = clip_info["asset_name"]
        part_num = queue["next_part_number"]

        print(f"\n📹 Processing Part #{part_num} (asset: {asset_name})")

        local_path = download_clip_asset(asset_name, DOWNLOAD_DIR)
        if not local_path:
            # Asset is gone/unrecoverable (e.g. manually deleted from the
            # release). Nothing to retry — drop it so it doesn't block the
            # queue forever, but don't touch next_part_number.
            print("  ❌ Could not fetch clip asset from release storage, dropping this entry")
            queue["pending_clips"].pop(0)
            save_queue(queue)
            continue

        title, description, tags = generate_metadata(part_num)
        print(f"   Title: {title}")

        video_id = upload_to_youtube(local_path, title, description, tags)

        if os.path.exists(local_path):
            os.remove(local_path)

        if not video_id:
            # Leave this clip at the front of the queue untouched so the
            # next scheduled run retries it — previously the whole entry
            # was silently discarded here even on failure.
            print("  ⏭️ Leaving clip in queue for retry on next run")
            break

        delete_clip_asset(asset_name)
        queue["pending_clips"].pop(0)
        queue["uploaded_clips"].append({
            "part_number": part_num,
            "video_id": video_id,
            "uploaded_at": datetime.now().isoformat(),
        })
        queue["next_part_number"] = part_num + 1
        succeeded += 1
        save_queue(queue)

    print("\n" + "=" * 60)
    print(f"✅ Uploaded {succeeded} Short(s)")
    print(f"📊 Next Part: #{queue['next_part_number']}")
    print(f"📊 Remaining: {len(queue['pending_clips'])}")
    print("=" * 60)


if __name__ == "__main__":
    main()
