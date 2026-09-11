import asyncio
import json
import math
from pathlib import Path

from app.errors import PipelineError


async def run_process(args: list[str], timeout: float, cwd: Path | None = None):
    process = await asyncio.create_subprocess_exec(
        *map(str, args),
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            raise PipelineError(
                "MEDIA_PROCESS_FAILED", "FFmpeg/ffprobe failed; check input media and installed codecs/fonts"
            )
        return stdout
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise


async def probe(path: Path, settings):
    output = await run_process(
        [
            settings.ffprobe_bin,
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        30,
    )
    return json.loads(output)


def duration_of(metadata):
    try:
        duration = float(metadata["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
        return duration
    except (KeyError, TypeError, ValueError) as exc:
        raise PipelineError("INVALID_DURATION", "Media has no valid duration") from exc


def validate_render(metadata, settings):
    videos = [s for s in metadata.get("streams", []) if s.get("codec_type") == "video"]
    audios = [s for s in metadata.get("streams", []) if s.get("codec_type") == "audio"]
    duration = duration_of(metadata)
    if len(videos) != 1 or len(audios) != 1:
        raise PipelineError("INVALID_RENDER", "Output must contain one video and one audio stream")
    video, audio = videos[0], audios[0]
    if (video.get("width"), video.get("height"), video.get("codec_name"), audio.get("codec_name")) != (
        1080,
        1920,
        "h264",
        "aac",
    ):
        raise PipelineError("INVALID_RENDER", "Output must be 1080x1920 H.264 with AAC")
    try:
        n, d = map(float, video.get("avg_frame_rate", "0/1").split("/"))
        fps = n / d
    except (ValueError, ZeroDivisionError):
        fps = 0
    if abs(fps - 30) > 0.01 or video.get("pix_fmt") != "yuv420p":
        raise PipelineError("INVALID_RENDER", "Output must have 30 fps and yuv420p pixel format")
    if not settings.min_video_duration_sec <= duration <= settings.max_video_duration_sec + 0.15:
        raise PipelineError("INVALID_RENDER", "Output duration is outside configured limits")
    if abs(float(audio.get("duration", duration)) - duration) > 0.3:
        raise PipelineError("INVALID_RENDER", "Output audio duration does not match video")
    return duration
