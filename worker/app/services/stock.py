import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.errors import PipelineError
from app.logging import event
from app.services.media import probe, run_process
from app.services.network import bounded_fetch, check_status, retry_call
from app.services.relevance import relevance

# A clip whose description contains every content word of the query is a real match;
# half the words is a usable but looser match. Below that the clip only shares an
# incidental common word and looks unrelated on screen, so it is worse than reusing
# an earlier clip. Both tiers are measured against the live catalogues in the tests.
STRONG_MATCH = 0.999
WEAK_MATCH = 0.5
PAGE_SIZE = 80
DOWNLOAD_ATTEMPTS = 5


@dataclass(frozen=True)
class Candidate:
    """One downloadable clip, normalized across providers."""

    provider: str
    asset_id: str
    description: str
    page_url: str
    file_url: str
    author: str
    license: str

    @property
    def key(self):
        return f"{self.provider}:{self.asset_id}"


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


class PixabayFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str = ""
    width: int = 0
    height: int = 0


class PixabayHit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    pageURL: str = ""
    tags: str = ""
    user: str = ""
    videos: dict[str, PixabayFile] = {}


class PixabayResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    hits: list[PixabayHit] = []


def choose_file(files):
    candidates = [f for f in files if f.file_type == "video/mp4" and f.width and f.height]
    if not candidates:
        raise PipelineError("NO_VIDEO_FILE", "Pexels result has no usable MP4")
    return min(candidates, key=frame_score)


def frame_score(file):
    """Prefer a rendition that fills 1080x1920 without paying for 4K."""
    small, large = sorted([file.width, file.height])
    return (0 if small >= 1080 and large >= 1920 else 1, abs(file.width * file.height - 1080 * 1920))


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def slug_description(url):
    """A Pexels page URL ends with a human description and the numeric id."""
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return " ".join(slug.split("-")[:-1])


class StockProvider(Protocol):
    async def search(self, query: str) -> list[Candidate]: ...


class PexelsProvider:
    name = "pexels"
    license = "Pexels License"
    attribution = "Videos provided by Pexels — https://www.pexels.com"

    def __init__(self, settings):
        self.settings = settings
        if not settings.pexels_api_key.get_secret_value():
            raise PipelineError("PEXELS_NOT_CONFIGURED", "Set PEXELS_API_KEY")

    async def search(self, query):
        # No orientation filter: the portrait catalogue is far smaller and, on niche
        # topics, contains none of the relevant clips. The renderer crops to 1080x1920
        # anyway, so a well-matched landscape clip beats an unrelated portrait one.
        async def request():
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_sec) as client:
                response = await client.get(
                    "https://api.pexels.com/v1/videos/search",
                    params={"query": query, "per_page": PAGE_SIZE, "locale": "en-US"},
                    headers={"Authorization": self.settings.pexels_api_key.get_secret_value()},
                )
                check_status(response)
                return PexelsResponse.model_validate(response.json()).videos

        candidates = []
        for video in await retry_call(request):
            author = str(video.user.get("name", "")).strip()
            if not video.video_files or not author:
                continue
            try:
                link = choose_file(video.video_files).link
            except PipelineError:
                continue
            candidates.append(
                Candidate(
                    provider=self.name,
                    asset_id=str(video.id),
                    description=slug_description(video.url),
                    page_url=video.url,
                    file_url=link,
                    author=author,
                    license=self.license,
                )
            )
        return candidates


class PixabayProvider:
    name = "pixabay"
    license = "Pixabay Content License"
    attribution = "Videos provided by Pixabay — https://pixabay.com"

    def __init__(self, settings):
        self.settings = settings
        if not settings.pixabay_api_key.get_secret_value():
            raise PipelineError("PIXABAY_NOT_CONFIGURED", "Set PIXABAY_API_KEY")

    async def search(self, query):
        async def request():
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_sec) as client:
                # Pixabay authenticates by query parameter; never echo the URL on failure.
                response = await client.get(
                    "https://pixabay.com/api/videos/",
                    params={
                        "key": self.settings.pixabay_api_key.get_secret_value(),
                        "q": query[:100],
                        "per_page": PAGE_SIZE,
                        "safesearch": "true",
                        "lang": "en",
                    },
                )
                check_status(response)
                return PixabayResponse.model_validate(response.json()).hits

        try:
            hits = await retry_call(request)
        except PipelineError:
            raise
        except Exception:
            raise PipelineError("PIXABAY_SEARCH_FAILED", "Could not search Pixabay video library") from None
        candidates = []
        for hit in hits:
            files = [f for f in hit.videos.values() if f.url and f.width and f.height]
            author = hit.user.strip()
            if not files or not author:
                continue
            candidates.append(
                Candidate(
                    provider=self.name,
                    asset_id=str(hit.id),
                    # Pixabay ships real tags, a cleaner relevance signal than a URL slug.
                    description=hit.tags.replace(",", " "),
                    page_url=hit.pageURL,
                    file_url=min(files, key=frame_score).url,
                    author=author,
                    license=self.license,
                )
            )
        return candidates


class StockLibrary:
    """Search every configured library, then pick by measured relevance, not by luck."""

    def __init__(self, settings, providers):
        self.settings = settings
        self.providers = providers
        self.cache = {}

    async def search(self, query):
        """Cached per job: the fallback query repeats across scenes, and Pixabay
        asks callers to cache results rather than re-request them."""
        if query not in self.cache:
            found = await asyncio.gather(
                *(provider.search(query) for provider in self.providers), return_exceptions=True
            )
            candidates = []
            for provider, result in zip(self.providers, found, strict=True):
                if isinstance(result, BaseException):
                    # One library being down must not fail a job the other can serve.
                    event("STOCK_SEARCH_FAILED", provider=provider.name)
                    continue
                candidates.extend(result)
            if not candidates and all(isinstance(r, BaseException) for r in found):
                raise PipelineError("STOCK_SEARCH_FAILED", "No stock library answered the search")
            self.cache[query] = candidates
        return self.cache[query]

    async def ranked(self, query, minimum):
        scored = ((relevance(query, c.description), c) for c in await self.search(query))
        return [(score, c) for score, c in sorted(scored, key=lambda pair: -pair[0]) if score >= minimum]

    async def fetch(self, query, used, destination, fallback=None):
        queries = [query] + ([fallback] if fallback and fallback != query else [])
        # Try a real match on the precise query, then on the broader fallback, then
        # loosen the bar, and only then repeat a clip already used in this video.
        for minimum in (STRONG_MATCH, WEAK_MATCH):
            for search_query in queries:
                fresh = [c for _, c in await self.ranked(search_query, minimum) if c.key not in used]
                asset = await self.download(fresh, used, destination)
                if asset:
                    return asset
        for search_query in queries:
            repeats = [c for _, c in await self.ranked(search_query, WEAK_MATCH)]
            asset = await self.download(repeats, used, destination)
            if asset:
                return asset
        raise PipelineError(
            "NO_RELEVANT_STOCK", "No stock clip matched this scene closely enough to use on screen"
        )

    async def download(self, candidates, used, destination):
        for candidate in candidates[:DOWNLOAD_ATTEMPTS]:
            # Asset URLs come exclusively from the official APIs; downloads are DNS-pinned.
            if urlsplit(candidate.file_url).scheme != "https":
                continue

            async def fetch_file(url=candidate.file_url):
                async with asyncio.timeout(self.settings.http_timeout_sec * 6):
                    await bounded_fetch(
                        url,
                        limit=self.settings.max_asset_size_mb * 1024 * 1024,
                        timeout=self.settings.http_timeout_sec,
                        types=("video/mp4",),
                        destination=destination,
                    )

            try:
                await retry_call(fetch_file, self.settings.max_download_retries)
                metadata = await probe(destination, self.settings)
                if not any(s.get("codec_type") == "video" for s in metadata.get("streams", [])):
                    continue
            except Exception:
                destination.unlink(missing_ok=True)
                continue
            used.add(candidate.key)
            return {
                "provider": candidate.provider,
                "provider_asset_id": candidate.asset_id,
                "author": candidate.author,
                "source_url": candidate.page_url,
                "asset_url": candidate.file_url,
                "license": candidate.license,
                "downloaded_at": datetime.now(timezone.utc),
                "local_path": str(destination),
                "sha256": file_hash(destination),
            }
        return None


def create_stock_library(settings):
    providers = [PexelsProvider(settings)]
    if settings.pixabay_api_key.get_secret_value():
        providers.append(PixabayProvider(settings))
    return StockLibrary(settings, providers)


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
