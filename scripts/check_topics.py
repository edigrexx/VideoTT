#!/usr/bin/env python3
"""Check a topic's stock coverage before spending a generation on it.

Stock search always answers, so a topic with no footage produces a video
illustrated by unrelated clips. Pass the subjects the scenes will search for;
a topic is only as good as its thinnest scene, so the weakest query decides.

    python scripts/check_topics.py "railway track" "train rails" "train passing"
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker") if (ROOT / "worker").exists() else str(ROOT))

from app.config import Settings
from app.services.relevance import relevance
from app.services.stock import create_stock_library

# A scene needs a handful of unused full matches; below that it falls back to
# loose matches and the footage stops following the narration.
GOOD, RISKY = 15, 5


async def main(queries):
    library = create_stock_library(Settings())
    print("libraries: " + ", ".join(p.name for p in library.providers) + "\n")
    weakest = None
    for query in queries:
        found = await library.search(query)
        scored = sorted(((relevance(query, c.description), c) for c in found), key=lambda p: -p[0])
        full = [c for score, c in scored if score >= 0.999]
        weakest = len(full) if weakest is None else min(weakest, len(full))
        mark = "OK  " if len(full) >= GOOD else "risk" if len(full) >= RISKY else "NONE"
        libraries = {}
        for candidate in full:
            libraries[candidate.provider] = libraries.get(candidate.provider, 0) + 1
        print(f"{mark} {len(full):>4} full matches  {query!r}  {libraries or ''}")
        for score, candidate in scored[:2]:
            print(f"            {score:.2f}  {candidate.description[:64]}")
    verdict = "USE IT" if weakest >= GOOD else "RISKY, rewrite the weak subjects" if weakest >= RISKY else "SKIP"
    print(f"\nweakest scene: {weakest} full matches  ->  {verdict}")
    return 0 if weakest >= RISKY else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    try:
        raise SystemExit(asyncio.run(main(sys.argv[1:])))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
