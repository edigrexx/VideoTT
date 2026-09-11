import socket

import httpx
import pytest
import respx

from app.config import Settings
from app.errors import PipelineError
from app.services.network import bounded_fetch, public_address
from app.services.stock import PexelsProvider, PexelsResponse, VideoFile, choose_file


def file(id, w, h):
    return VideoFile(
        id=id, width=w, height=h, file_type="video/mp4", link=f"https://videos.pexels.com/{id}.mp4"
    )


def test_best_file_prefers_full_hd_not_4k():
    assert choose_file([file(1, 720, 1280), file(2, 1080, 1920), file(3, 2160, 3840)]).id == 2
    assert choose_file([file(1, 1280, 720), file(2, 960, 540)]).id == 1


@respx.mock
async def test_pexels_current_endpoint_parsing():
    data = {
        "videos": [
            {
                "id": 42,
                "url": "https://www.pexels.com/video/42/",
                "duration": 12,
                "user": {"name": "Author"},
                "video_files": [file(2, 1080, 1920).model_dump()],
            }
        ]
    }
    route = respx.get(
        "https://api.pexels.com/v1/videos/search",
        params={"query": "keyboard", "orientation": "portrait", "per_page": 20, "locale": "en-US"},
    ).mock(return_value=httpx.Response(200, json=data))
    result = await PexelsProvider(Settings(_env_file=None, pexels_api_key="test")).search(
        "keyboard", "portrait"
    )
    assert result[0].id == 42 and route.called
    assert PexelsResponse.model_validate({"videos": []}).videos == []


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://169.254.169.254/latest",
        "https://user:pass@example.com",
        "https://example.com:444/",
    ],
)
async def test_private_and_unsafe_sources_rejected(url, monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    import asyncio

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(PipelineError):
        await public_address(url)


@respx.mock
async def test_download_size_and_content_type(monkeypatch, tmp_path):
    async def pinned(url):
        return "https://93.184.216.34/file", "example.com"

    monkeypatch.setattr("app.services.network.public_address", pinned)
    route = respx.get("https://93.184.216.34/file").mock(
        return_value=httpx.Response(200, content=b"0123456789", headers={"Content-Type": "video/mp4"})
    )
    with pytest.raises(PipelineError, match="size limit"):
        await bounded_fetch(
            "https://example.com/file",
            limit=5,
            timeout=1,
            types=("video/mp4",),
            destination=tmp_path / "clip.mp4",
        )
    route.mock(return_value=httpx.Response(200, content=b"html", headers={"Content-Type": "text/html"}))
    with pytest.raises(PipelineError, match="content type"):
        await bounded_fetch("https://example.com/file", limit=100, timeout=1, types=("video/mp4",))
