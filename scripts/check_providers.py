#!/usr/bin/env python3
"""Run from checkout or inside worker; never print credentials or upstream responses."""
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker") if (ROOT / "worker").exists() else str(ROOT))

from app.config import Settings
from app.services.preflight import check_providers


async def main():
    checks = await check_providers(Settings())
    for check in checks:
        print(f'{"OK" if check["ok"] else "FAIL"} | {check["check"]}: {check["detail"]}')
    print("No LLM generation or paid web search was requested. This is not an end-to-end video test.")
    return 0 if all(check["ok"] for check in checks) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        raise SystemExit("Provider check failed. Check Environment values and network access.") from None
