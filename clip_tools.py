import subprocess

TARGET_W, TARGET_H = 1080, 1920


def cut_and_convert_clip(source_path, start_time, duration, output_path):
    """Cut [start_time, start_time+duration) out of source_path and convert
    straight to 9:16 Shorts format, in a single ffmpeg pass.

    -ss is placed AFTER -i (not before) so the seek is frame-accurate rather
    than snapped to the nearest keyframe. That's only safe because we're
    re-encoding anyway (-c:v libx264) — the old code used -c copy, which
    can't honor a frame-accurate seek and silently produced clips that
    didn't start exactly where the queue said they would.
    """
    filter_complex = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=1,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black"
    )
    cmd = [
        "ffmpeg",
        "-i", source_path,
        "-ss", str(start_time),
        "-t", str(duration),
        "-vf", filter_complex,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
