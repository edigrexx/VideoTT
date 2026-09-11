import asyncio
import signal
import time

import psycopg

from app.config import get_settings
from app.db.session import SessionLocal, engine
from app.logging import configure_logging, event
from app.pipeline import process_job
from app.queue import claim_next, recover_interrupted

LOCK_ID = 765443200


async def consume(settings):
    while True:
        job_id = claim_next(SessionLocal)
        if job_id:
            await process_job(job_id, settings, SessionLocal)
        else:
            await asyncio.sleep(settings.poll_interval_sec)


async def heartbeat(connection, settings):
    while True:
        # A lost leader connection cancels the pipeline before this process can claim more work.
        async with asyncio.timeout(10):
            await connection.execute("SELECT 1")
        (settings.media_root / "runner.heartbeat").write_text(str(time.time()))
        await asyncio.sleep(5)


async def run():
    settings = get_settings()
    settings.require_auth()
    settings.media_root.mkdir(parents=True, exist_ok=True)
    dsn = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True, connect_timeout=10) as connection:
        while True:
            result = await connection.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
            if (await result.fetchone())[0]:
                break
            await asyncio.sleep(5)
        recover_interrupted(SessionLocal, settings.max_job_attempts)
        tasks = [asyncio.create_task(consume(settings)), asyncio.create_task(heartbeat(connection, settings))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    task = asyncio.create_task(run())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    configure_logging()
    try:
        asyncio.run(main())
    except Exception as exc:
        event("RUNNER_STOPPED", error_type=type(exc).__name__)
        raise SystemExit(1) from None
