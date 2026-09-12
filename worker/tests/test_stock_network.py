import socket

import httpx
import pytest
import respx

from app.config import Settings
from app.errors import PipelineError
from app.services.network import bounded_fetch, public_address
from app.services.stock import PexelsProvider, PexelsResponse, PexelsVideo, VideoFile, choose_file


def file(id, w, h):
    return VideoFile(
        id=id, width=w, height=h, file_type="video/mp4", link=f"https://videos.pexels.com/{id}.mp4"
    )


def video(id):
    return {
        "id": id,
        "url": f"https://www.pexels.com/video/{id}/",
        "duration": 12,
        "user": {"name": "Author"},
        "video_files": [file(id, 1080, 1920).model_dump()],
    }


def test_best_file_prefers_full_hd_not_4k():
    assert choose_file([file(1, 720, 1280), file(2, 1080, 1920), file(3, 2160, 3840)]).id == 2
    assert choose_file([file(1, 1280, 720), file(2, 960, 540)]).id == 1


@respx.mock
async def test_pexels_current_endpoint_parsing():
    data = {"videos": [video(42)]}
    # The full Pexels page keeps narrow topics from running out of unused clips.
    route = respx.get(
        "https://api.pexels.com/v1/videos/search",
        params={"query": "keyboard", "orientation": "portrait", "per_page": 80, "locale": "en-US"},
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


async def searched(provider, used, fallback, tmp_path, monkeypatch, pools):
    queries = []

    async def search(query, orientation):
        queries.append((query, orientation))
        return [PexelsVideo.model_validate(v) for v in pools.get(query, [])]

    async def download(url, **kwargs):
        kwargs["destination"].write_bytes(b"clip")

    async def probe(path, settings):
        return {"streams": [{"codec_type": "video"}]}

    monkeypatch.setattr(provider, "search", search)
    monkeypatch.setattr("app.services.stock.bounded_fetch", download)
    monkeypatch.setattr("app.services.stock.probe", probe)
    asset = await provider.fetch("exact shot", used, tmp_path / "scene.mp4", fallback)
    return queries, asset


async def test_fallback_query_is_searched_before_reusing_clips(tmp_path, monkeypatch):
    provider = PexelsProvider(Settings(_env_file=None, pexels_api_key="test"))
    pools = {"exact shot": [video(7)], "broader shot": [video(9)]}
    # Scene 7 already played, so the exact query offers nothing new for this scene.
    queries, asset = await searched(provider, {"7"}, "broader shot", tmp_path, monkeypatch, pools)
    assert asset["provider_asset_id"] == "9"
    assert queries == [("exact shot", "portrait"), ("exact shot", "landscape"), ("broader shot", "portrait")]


async def test_exact_query_wins_and_fallback_is_not_searched(tmp_path, monkeypatch):
    provider = PexelsProvider(Settings(_env_file=None, pexels_api_key="test"))
    pools = {"exact shot": [video(7)], "broader shot": [video(9)]}
    queries, asset = await searched(provider, set(), "broader shot", tmp_path, monkeypatch, pools)
    assert asset["provider_asset_id"] == "7"
    assert queries == [("exact shot", "portrait")]


async def test_repeated_clip_is_the_last_resort_after_both_queries(tmp_path, monkeypatch):
    provider = PexelsProvider(Settings(_env_file=None, pexels_api_key="test"))
    pools = {"exact shot": [video(7)], "broader shot": [video(7)]}
    queries, asset = await searched(provider, {"7"}, "broader shot", tmp_path, monkeypatch, pools)
    assert asset["provider_asset_id"] == "7"
    assert [q for q, _ in queries] == ["exact shot", "exact shot", "broader shot", "broader shot"]


async def test_missing_or_duplicate_fallback_costs_no_extra_request(tmp_path, monkeypatch):
    provider = PexelsProvider(Settings(_env_file=None, pexels_api_key="test"))
    pools = {"exact shot": [video(7)]}
    for fallback in (None, "exact shot"):
        queries, asset = await searched(provider, {"7"}, fallback, tmp_path, monkeypatch, pools)
        assert asset["provider_asset_id"] == "7"
        assert [q for q, _ in queries] == ["exact shot", "exact shot"]
