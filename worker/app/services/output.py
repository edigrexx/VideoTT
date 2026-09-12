import json
from datetime import datetime, timezone

from app.errors import PipelineError

# Each library keeps its own licence name and the credit line it asks callers to show.
STOCK_LICENSES = {
    "pexels": ("Pexels License", "Videos provided by Pexels — https://www.pexels.com"),
    "pixabay": ("Pixabay Content License", "Videos provided by Pixabay — https://pixabay.com"),
}
TEST_LICENSE = ("CC0-1.0 (generated test shapes)", "Synthetic test fixtures")


def rights_manifest(video_id, assets, is_test=False):
    entries = []
    credits = []
    for asset in assets:
        expected, credit = STOCK_LICENSES.get(asset["provider"], (None, None))
        if is_test and asset["provider"] == "synthetic-test":
            expected, credit = TEST_LICENSE
        allowed = expected is not None and asset["license"] == expected
        if not allowed or not asset.get("author") or not asset.get("source_url"):
            raise PipelineError("UNKNOWN_LICENSE", "Asset has missing or unsupported rights metadata")
        if credit not in credits:
            credits.append(credit)
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
        "attribution": " | ".join(credits) if credits else "No stock footage used",
        "font": {"name": "DejaVu Sans", "license": "Bitstream Vera / DejaVu public domain additions"},
        "audio": {
            "type": "test tone" if is_test else "original narration synthesized by Edge TTS",
            "stock_audio_used": False,
        },
    }


def write_output(
    directory,
    video_id,
    topic,
    script,
    sources,
    assets,
    duration,
    is_test=False,
    llm_usage=None,
    language="en-US",
):
    manifest = rights_manifest(video_id, assets, is_test)
    metadata = {
        "video_id": str(video_id),
        "topic": topic,
        "title": script.title,
        "hook": script.hook,
        "payoff": script.payoff,
        "duration": duration,
        "language": language,
        "status": "READY",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_test": is_test,
        "sources": [{k: s[k] for k in ("title", "url", "publisher", "retrieved_at")} for s in sources],
        "attribution": manifest["attribution"],
    }
    if llm_usage is not None:
        metadata["llm_usage"] = llm_usage
    for filename, payload in (("metadata.json", metadata), ("rights_manifest.json", manifest)):
        (directory / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "caption.txt").write_text(
        script.caption + "\n\n" + " ".join("#" + tag for tag in script.hashtags) + "\n", encoding="utf-8"
    )
