import json
from pathlib import Path

import pytest


def test_workflows_bounded_and_no_publication():
    roots = [Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]]
    root = next((p for p in roots if (p / "workflows").exists()), roots[0])
    if not (root / "workflows").exists():
        pytest.skip("Workflow files are validated from repository checkout")
    for path in (root / "workflows").glob("*.json"):
        data = json.loads(path.read_text())
        assert data["active"] is False
        assert data["settings"]["executionTimeout"] == 7200
        names = {n["name"] for n in data["nodes"]}
        assert {"Create video", "Check job", "Ready?", "Needs attention"} <= names
        for node in data["nodes"]:
            if node["type"] == "n8n-nodes-base.httpRequest":
                assert "worker:8000" in node["parameters"]["url"]
                assert node["parameters"]["genericAuthType"] == "httpHeaderAuth"
        assert not any(
            word in path.read_text().lower()
            for word in ("video.upload", "video.publish", "tiktok.com", "oauth")
        )
