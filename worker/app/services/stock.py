import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.errors import PipelineError
from app.services.media import probe, run_process
from app.services.network import bounded_fetch, check_status, retry_call


class VideoFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    file_type: str
    width: int | None = None
    height: int | None = None
    link: str


class PexelsVideo(BaseModel):
    id: int
    url: str
    duration: float = Field(gt=0)
    user: dict
    video_files: list[VideoFile]


class PexelsResponse(BaseModel):
    videos: list[PexelsVideo]


def choose_file(files):
    candidates = [f for f in files if f.file_type == "video/mp4" and f.width and f.height]
    if not candidates:
        raise PipelineError("NO_VIDEO_FILE", "Pexels result has no usable MP4")

    def score(f):
        small, large = sorted([f.width, f.height])
        return (0 if small >= 1080 and large >= 1920 else 1, abs(f.width * f.height - 1080 * 1920))

    return min(candidates, key=score)


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class StockProvider(Protocol):
    async def fetch(
        self, query: str, used: set[str], destination: Path, fallback: str | None = None
    ) -> dict: ...


class PexelsProvider:
    def __init__(self, settings):
        self.settings = settings
        if not settings.pexels_api_key.get_secret_value():
            raise PipelineError("PEXELS_NOT_CONFIGURED", "Set PEXELS_API_KEY")

    async def search(self, query, orientation):
        async def request():
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_sec) as client:
                response = await client.get(
                    "https://api.pexels.com/v1/videos/search",
                    params={"query": query, "orientation": orientation, "per_page": 80, "locale": "en-US"},
                    headers={"Authorization": self.settings.pexels_api_key.get_secret_value()},
                )
                check_status(response)
                return PexelsResponse.model_validate(response.json()).videos

        return await retry_call(request)

    async def fetch(self, query, used, destination, fallback=None):
        # Precise scene query first; the broader fallback keeps a narrow topic from
        # exhausting one small pool of generic clips before repeats are allowed.
        queries = [query] + ([fallback] if fallback and fallback != query else [])
        repeat_candidates = []
        candidates = []
        for search_query in queries:
            for orientation in ("portrait", "landscape"):
                found = await self.search(search_query, orientation)
                repeat_candidates.extend(found)
                candidates = [video for video in found if str(video.id) not in used and video.video_files]
                if candidates:
                    break
            if candidates:
                break
        if not candidates:
            candidates = [v for v in repeat_candidates if v.video_files]
        if not candidates:
            raise PipelineError("NO_STOCK_FOUND", "Pexels returned no usable stock footage for a scene")
        for video in candidates[:5]:
            file = choose_file(video.video_files)
            # Asset URL comes exclusively from the official API; all downloads are additionally DNS-pinned.
            if urlsplit(file.link).scheme != "https" or not str(video.user.get("name", "")).strip():
                continue

            async def download():
                async with asyncio.timeout(self.settings.http_timeout_sec * 6):
                    await bounded_fetch(
                        file.link,
                        limit=self.settings.max_asset_size_mb * 1024 * 1024,
                        timeout=self.settings.http_timeout_sec,
                        types=("video/mp4",),
                        destination=destination,
                    )

            try:
                await retry_call(download, self.settings.max_download_retries)
                metadata = await probe(destination, self.settings)
                if not any(s.get("codec_type") == "video" for s in metadata.get("streams", [])):
                    continue
            except Exception:
                destination.unlink(missing_ok=True)
                continue
            used.add(str(video.id))
            return {
                "provider": "pexels",
                "provider_asset_id": str(video.id),
                "author": video.user["name"],
                "source_url": video.url,
                "asset_url": file.link,
                "license": "Pexels License",
                "downloaded_at": datetime.now(timezone.utc),
                "local_path": str(destination),
                "sha256": file_hash(destination),
            }
        raise PipelineError(
            "STOCK_DOWNLOAD_FAILED", "No selected Pexels file passed size, content type and media checks"
        )


class MockStockProvider:
    def __init__(self, settings):
        self.settings = settings

    async def fetch(self, query, used, destination, fallback=None):
        index = len(used) + 1
        # Different portrait/landscape, fps and short durations exercise normalization/looping.
        size = "640x360" if index % 2 else "360x640"
        color = ["0x20394c", "0x364939", "0x593849", "0x5b4931"][index % 4]
        await run_process(
            [
                self.settings.ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={size}:r={24 if index % 2 else 25}:d=1.5",
                "-vf",
                f"drawbox=x={index * 20}:y=80:w=130:h=200:color=white@0.25:t=fill",
                "-an",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-pix_fmt",
                "yuv420p",
                str(destination),
            ],
            self.settings.ffmpeg_timeout_sec,
        )
        used.add(str(index))
        return {
            "provider": "synthetic-test",
            "provider_asset_id": str(index),
            "author": "VideoTT fixture generator",
            "source_url": "fixture://generated-colors",
            "asset_url": "fixture://generated-colors",
            "license": "CC0-1.0 (generated test shapes)",
            "downloaded_at": datetime.now(timezone.utc),
            "local_path": str(destination),
            "sha256": file_hash(destination),
        }
