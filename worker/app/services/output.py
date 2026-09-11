import json
from datetime import datetime, timezone

from app.errors import PipelineError


def rights_manifest(video_id, assets, is_test=False):
    entries = []
    for asset in assets:
        allowed = (asset["provider"] == "pexels" and asset["license"] == "Pexels License") or (
            is_test
            and asset["provider"] == "synthetic-test"
            and asset["license"] == "CC0-1.0 (generated test shapes)"
        )
        if not allowed or not asset.get("author") or not asset.get("source_url"):
            raise PipelineError("UNKNOWN_LICENSE", "Asset has missing or unsupported rights metadata")
        entries.append(
            {
                "scene_id": str(asset["scene_id"]),
                "provider": asset["provider"],
                "asset_id": asset["provider_asset_id"],
                "author": asset["author"],
                "source_url": asset["source_url"],
                "asset_url": asset["asset_url"],
                "license": asset["license"],
                "downloaded_at": asset["downloaded_at"].isoformat(),
                "local_path": asset["local_path"],
                "sha256": asset["sha256"],
            }
        )
    return {
        "video_id": str(video_id),
        "is_test": is_test,
        "assets": entries,
        "attribution": "Videos provided by Pexels — https://www.pexels.com"
        if not is_test
        else "Synthetic test fixtures",
        "font": {"name": "DejaVu Sans", "license": "Bitstream Vera / DejaVu public domain additions"},
        "audio": {
            "type": "test tone" if is_test else "original narration synthesized by Edge TTS",
            "stock_audio_used": False,
        },
    }


def write_output(directory, video_id, topic, script, sources, assets, duration, is_test=False):
    manifest = rights_manifest(video_id, assets, is_test)
    metadata = {
        "video_id": str(video_id),
        "topic": topic,
        "title": script.title,
        "hook": script.hook,
        "payoff": script.payoff,
        "duration": duration,
        "language": "en-US",
        "status": "READY",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_test": is_test,
        "sources": [{k: s[k] for k in ("title", "url", "publisher", "retrieved_at")} for s in sources],
        "attribution": manifest["attribution"],
    }
    for filename, payload in (("metadata.json", metadata), ("rights_manifest.json", manifest)):
        (directory / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "caption.txt").write_text(
        script.caption + "\n\n" + " ".join("#" + tag for tag in script.hashtags) + "\n", encoding="utf-8"
    )
