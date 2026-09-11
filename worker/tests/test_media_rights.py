from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.errors import PipelineError
from app.services.media import validate_render
from app.services.output import rights_manifest
from app.services.subtitles import ass_time, escape_ass, write_subtitles
from app.services.tts import Cue


def valid_probe():
    return {
        "format": {"duration": "72.4"},
        "streams": [
            {
                "codec_type": "video",
                "width": 1080,
                "height": 1920,
                "codec_name": "h264",
                "avg_frame_rate": "30/1",
                "pix_fmt": "yuv420p",
            },
            {"codec_type": "audio", "codec_name": "aac", "duration": "72.4"},
        ],
    }


def test_render_metadata():
    assert validate_render(valid_probe(), Settings(_env_file=None)) == 72.4


@pytest.mark.parametrize("change", ["width", "codec", "no_audio", "fps", "duration", "nan", "pixel_format"])
def test_invalid_render(change):
    data = valid_probe()
    if change == "width":
        data["streams"][0]["width"] = 720
    elif change == "codec":
        data["streams"][0]["codec_name"] = "hevc"
    elif change == "no_audio":
        data["streams"].pop()
    elif change == "fps":
        data["streams"][0]["avg_frame_rate"] = "0/0"
    elif change == "pixel_format":
        data["streams"][0]["pix_fmt"] = "yuv444p"
    else:
        data["format"]["duration"] = "nan" if change == "nan" else "120"
    with pytest.raises(PipelineError):
        validate_render(data, Settings(_env_file=None))


def test_rights_manifest_and_unknown_license():
    asset = {
        "scene_id": "scene1",
        "provider": "pexels",
        "provider_asset_id": "12",
        "author": "Photographer",
        "source_url": "https://www.pexels.com/video/12/",
        "asset_url": "https://videos.pexels.com/12.mp4",
        "license": "Pexels License",
        "downloaded_at": datetime.now(timezone.utc),
        "local_path": "/data/media/a.mp4",
        "sha256": "a" * 64,
    }
    manifest = rights_manifest("video1", [asset])
    assert manifest["assets"][0]["author"] == "Photographer"
    assert manifest["assets"][0]["scene_id"] == "scene1"
    asset["license"] = "unknown"
    with pytest.raises(PipelineError):
        rights_manifest("video1", [asset])


def test_ass_safe_text_timing_and_layout(tmp_path):
    assert ass_time(59.999) == "0:01:00.00"
    assert "{" not in escape_ass(r"{\pos(0,0)} hello")
    cues = [
        Cue(i * 0.5, i * 0.5 + 0.4, text)
        for i, text in enumerate(["Unicode", "café", "—", "hello.", "Next", "caption."])
    ]
    path = tmp_path / "test.ass"
    write_subtitles(cues, 3.5, path)
    content = path.read_text()
    assert "café" in content and "PlayResX: 1080" in content
    assert r"\t(0,110" in content
    assert "430,1" in content
    assert len([line for line in content.splitlines() if line.startswith("Dialogue:")]) == 2
