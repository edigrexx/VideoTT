import socket

import httpx
import pytest
import respx

from app.config import Settings
from app.errors import PipelineError
from app.services.network import bounded_fetch, public_address
from app.services.stock import (
    Candidate,
    PexelsProvider,
    PexelsResponse,
    PixabayProvider,
    StockLibrary,
    VideoFile,
    choose_file,
    create_stock_library,
    slug_description,
)


def file(id, w, h):
    return VideoFile(
        id=id, width=w, height=h, file_type="video/mp4", link=f"https://videos.pexels.com/{id}.mp4"
    )


def pexels_video(id, slug):
    return {
        "id": id,
        "url": f"https://www.pexels.com/video/{slug}-{id}/",
        "duration": 12,
        "user": {"name": "Author"},
        "video_files": [file(id, 1080, 1920).model_dump()],
    }


def config(**overrides):
    return Settings(_env_file=None, pexels_api_key="pexels-test", **overrides)


def test_best_file_prefers_full_hd_not_4k():
    assert choose_file([file(1, 720, 1280), file(2, 1080, 1920), file(3, 2160, 3840)]).id == 2
    assert choose_file([file(1, 1280, 720), file(2, 960, 540)]).id == 1


def test_page_slug_becomes_the_relevance_description():
    assert slug_description("https://www.pexels.com/video/floppy-disk-80s-retro-20503028/") == (
        "floppy disk 80s retro"
    )


@respx.mock
async def test_pexels_search_uses_the_full_page_and_no_orientation_filter():
    # Portrait-only search returns none of the relevant clips on niche topics, and the
    # renderer crops to 1080x1920 anyway, so orientation must not narrow the pool.
    route = respx.get("https://api.pexels.com/v1/videos/search").mock(
        return_value=httpx.Response(200, json={"videos": [pexels_video(42, "floppy-disk-retro")]})
    )
    candidates = await PexelsProvider(config()).search("floppy disk")
    request = route.calls[0].request
    assert "orientation" not in request.url.params
    assert request.url.params["per_page"] == "80"
    assert candidates[0].asset_id == "42"
    assert candidates[0].description == "floppy disk retro"
    assert candidates[0].license == "Pexels License"
    assert candidates[0].key == "pexels:42"
    assert PexelsResponse.model_validate({"videos": []}).videos == []


@respx.mock
async def test_pexels_skips_results_without_a_usable_file_or_author():
    broken = pexels_video(1, "no-author")
    broken["user"] = {"name": "  "}
    no_mp4 = pexels_video(2, "no-mp4")
    no_mp4["video_files"] = [{"id": 9, "file_type": "video/webm", "width": 10, "height": 20, "link": "x"}]
    respx.get("https://api.pexels.com/v1/videos/search").mock(
        return_value=httpx.Response(200, json={"videos": [broken, no_mp4, pexels_video(3, "good-clip")]})
    )
    candidates = await PexelsProvider(config()).search("q")
    assert [c.asset_id for c in candidates] == ["3"]


@respx.mock
async def test_pixabay_tags_become_the_description_and_key_stays_out_of_results():
    route = respx.get("https://pixabay.com/api/videos/").mock(
        return_value=httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "id": 7,
                        "pageURL": "https://pixabay.com/videos/id-7/",
                        "tags": "floppy disk, retro, computer",
                        "user": "Photographer",
                        "videos": {
                            "large": {"url": "https://cdn.pixabay.com/7-large.mp4", "width": 3840, "height": 2160},
                            "medium": {"url": "https://cdn.pixabay.com/7-medium.mp4", "width": 1920, "height": 1080},
                            "tiny": {"url": "", "width": 0, "height": 0},
                        },
                    }
                ]
            },
        )
    )
    candidates = await PixabayProvider(config(pixabay_api_key="pixabay-test")).search("floppy disk")
    assert route.calls[0].request.url.params["key"] == "pixabay-test"
    assert candidates[0].description == "floppy disk  retro  computer"
    assert candidates[0].file_url == "https://cdn.pixabay.com/7-medium.mp4"
    assert candidates[0].license == "Pixabay Content License"
    assert candidates[0].key == "pixabay:7"


@respx.mock
async def test_pixabay_failure_never_echoes_the_url_that_carries_the_key():
    respx.get("https://pixabay.com/api/videos/").mock(return_value=httpx.Response(404))
    with pytest.raises(PipelineError) as error:
        await PixabayProvider(config(pixabay_api_key="pixabay-secret")).search("q")
    assert "pixabay-secret" not in str(error.value) and "pixabay-secret" not in error.value.message


def test_pixabay_joins_the_library_only_once_a_key_is_configured():
    assert [p.name for p in create_stock_library(config()).providers] == ["pexels"]
    library = create_stock_library(config(pixabay_api_key="k"))
    assert [p.name for p in library.providers] == ["pexels", "pixabay"]


def candidate(asset_id, description, provider="pexels"):
    return Candidate(
        provider=provider,
        asset_id=asset_id,
        description=description,
        page_url=f"https://example.com/{asset_id}/",
        file_url=f"https://cdn.example.com/{asset_id}.mp4",
        author="Author",
        license="Pexels License" if provider == "pexels" else "Pixabay Content License",
    )


class FakeProvider:
    def __init__(self, name, pools, fail=False):
        self.name = name
        self.pools = pools
        self.fail = fail
        self.queries = []

    async def search(self, query):
        self.queries.append(query)
        if self.fail:
            raise PipelineError("STOCK_SEARCH_FAILED", "down")
        return self.pools.get(query, [])


@pytest.fixture
def downloads(monkeypatch):
    async def download(url, **kwargs):
        kwargs["destination"].write_bytes(b"clip")

    async def probe(path, settings):
        return {"streams": [{"codec_type": "video"}]}

    monkeypatch.setattr("app.services.stock.bounded_fetch", download)
    monkeypatch.setattr("app.services.stock.probe", probe)


async def test_junk_result_is_never_used_even_when_the_api_ranks_it_first(tmp_path, downloads):
    # The live catalogue answers "floppy disk" with 79 clips of which 71 share no word
    # with the query; the relevant ones are not at the top.
    pool = [
        candidate("1", "close up of a beagle s nose outdoors"),
        candidate("2", "vintage vinyl record playing on turntable"),
        candidate("3", "floppy disk 80s computer retro diskette"),
    ]
    provider = FakeProvider("pexels", {"floppy disk": pool})
    library = StockLibrary(config(), [provider])
    asset = await library.fetch("floppy disk", set(), tmp_path / "scene.mp4", "retro computer")
    assert asset["provider_asset_id"] == "3"


async def test_fallback_query_runs_before_the_weaker_relevance_tier(tmp_path, downloads):
    pools = {
        "floppy disk": [candidate("1", "a person ejecting cd from the disk tray")],
        "retro computer": [candidate("2", "retro computer on a wooden desk")],
    }
    provider = FakeProvider("pexels", pools)
    library = StockLibrary(config(), [provider])
    asset = await library.fetch("floppy disk", set(), tmp_path / "scene.mp4", "retro computer")
    # The partial match on the exact query loses to a full match on the fallback.
    assert asset["provider_asset_id"] == "2"
    assert provider.queries == ["floppy disk", "retro computer"]


async def test_partial_match_is_accepted_once_no_query_has_a_full_match(tmp_path, downloads):
    pools = {
        "floppy disk": [candidate("1", "a person ejecting cd from the disk tray")],
        "retro computer": [candidate("2", "a cat sleeping on a sofa")],
    }
    library = StockLibrary(config(), [FakeProvider("pexels", pools)])
    asset = await library.fetch("floppy disk", set(), tmp_path / "scene.mp4", "retro computer")
    assert asset["provider_asset_id"] == "1"


async def test_a_clip_repeats_only_after_both_queries_are_exhausted(tmp_path, downloads):
    pools = {"floppy disk": [candidate("1", "floppy disk retro")], "retro computer": []}
    library = StockLibrary(config(), [FakeProvider("pexels", pools)])
    asset = await library.fetch("floppy disk", {"pexels:1"}, tmp_path / "scene.mp4", "retro computer")
    assert asset["provider_asset_id"] == "1"


async def test_an_all_junk_pool_fails_loudly_instead_of_showing_unrelated_footage(tmp_path, downloads):
    pools = {"floppy disk": [candidate("1", "a beagle in a field")], "retro computer": []}
    library = StockLibrary(config(), [FakeProvider("pexels", pools)])
    with pytest.raises(PipelineError) as error:
        await library.fetch("floppy disk", set(), tmp_path / "scene.mp4", "retro computer")
    assert error.value.code == "NO_RELEVANT_STOCK"


async def test_libraries_are_pooled_and_the_better_match_wins(tmp_path, downloads):
    pexels = FakeProvider("pexels", {"floppy disk": [candidate("1", "old computer disk tray")]})
    pixabay = FakeProvider(
        "pixabay", {"floppy disk": [candidate("9", "floppy disk  retro  computer", "pixabay")]}
    )
    library = StockLibrary(config(pixabay_api_key="k"), [pexels, pixabay])
    asset = await library.fetch("floppy disk", set(), tmp_path / "scene.mp4", "retro computer")
    assert (asset["provider"], asset["provider_asset_id"]) == ("pixabay", "9")
    assert asset["license"] == "Pixabay Content License"


async def test_one_library_being_down_does_not_fail_a_job_the_other_can_serve(tmp_path, downloads):
    broken = FakeProvider("pixabay", {}, fail=True)
    working = FakeProvider("pexels", {"floppy disk": [candidate("1", "floppy disk retro")]})
    library = StockLibrary(config(), [broken, working])
    asset = await library.fetch("floppy disk", set(), tmp_path / "scene.mp4", None)
    assert asset["provider_asset_id"] == "1"


async def test_every_library_failing_is_reported(tmp_path, downloads):
    library = StockLibrary(config(), [FakeProvider("pexels", {}, fail=True)])
    with pytest.raises(PipelineError) as error:
        await library.fetch("floppy disk", set(), tmp_path / "scene.mp4", None)
    assert error.value.code == "STOCK_SEARCH_FAILED"


async def test_repeated_queries_are_searched_once_per_job(tmp_path, downloads):
    pool = [candidate(str(i), "floppy disk retro") for i in range(1, 4)]
    provider = FakeProvider("pexels", {"floppy disk": pool})
    library = StockLibrary(config(), [provider])
    used = set()
    for index in range(3):
        await library.fetch("floppy disk", used, tmp_path / f"scene-{index}.mp4", "floppy disk")
    assert provider.queries == ["floppy disk"]
    assert used == {"pexels:1", "pexels:2", "pexels:3"}


async def test_unusable_download_falls_through_to_the_next_candidate(tmp_path, monkeypatch):
    attempted = []

    async def download(url, **kwargs):
        attempted.append(url)
        if url.endswith("1.mp4"):
            raise PipelineError("FILE_TOO_LARGE", "too big")
        kwargs["destination"].write_bytes(b"clip")

    async def probe(path, settings):
        return {"streams": [{"codec_type": "video"}]}

    monkeypatch.setattr("app.services.stock.bounded_fetch", download)
    monkeypatch.setattr("app.services.stock.probe", probe)
    pool = [candidate("1", "floppy disk retro"), candidate("2", "floppy disk vintage")]
    library = StockLibrary(config(), [FakeProvider("pexels", {"floppy disk": pool})])
    asset = await library.fetch("floppy disk", set(), tmp_path / "scene.mp4", None)
    assert asset["provider_asset_id"] == "2" and len(attempted) == 2


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
