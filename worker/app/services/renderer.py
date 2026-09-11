import math
import shutil
from pathlib import Path

from app.services.media import run_process


async def render(clips: list[Path], durations, audio, subtitles, destination, temp, settings):
    temp.mkdir(parents=True, exist_ok=True)
    elapsed = 0.0
    previous_frame = 0
    for i, (clip, duration) in enumerate(zip(clips, durations, strict=True)):
        elapsed += duration
        end_frame = math.ceil(elapsed * 30)
        frames = end_frame - previous_frame
        previous_frame = end_frame
        await run_process(
            [
                settings.ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-nostdin",
                "-protocol_whitelist",
                "file,pipe",
                "-stream_loop",
                "-1",
                "-i",
                str(clip),
                "-map",
                "0:v:0",
                "-an",
                "-sn",
                "-dn",
                "-vf",
                "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,format=yuv420p",
                "-frames:v",
                str(frames),
                "-c:v",
                "libx264",
                "-threads",
                str(settings.ffmpeg_threads),
                "-preset",
                settings.ffmpeg_preset,
                "-crf",
                "23",
                "-video_track_timescale",
                "15360",
                str(temp / f"clip-{i}.mp4"),
            ],
            settings.ffmpeg_timeout_sec,
        )
    (temp / "concat.txt").write_text("\n".join(f"file 'clip-{i}.mp4'" for i in range(len(clips))))
    shutil.copy2(subtitles, temp / "captions.ass")
    # Filter filename is static and relative; user input never becomes a filter expression.
    await run_process(
        [
            settings.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            "concat.txt",
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            "ass=captions.ass",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v",
            "libx264",
            "-threads",
            str(settings.ffmpeg_threads),
            "-preset",
            settings.ffmpeg_preset,
            "-crf",
            "23",
            "-maxrate",
            "6M",
            "-bufsize",
            "12M",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-t",
            f"{elapsed:.6f}",
            "-movflags",
            "+faststart",
            "-map_metadata",
            "-1",
            str(destination),
        ],
        settings.ffmpeg_timeout_sec,
        cwd=temp,
    )
