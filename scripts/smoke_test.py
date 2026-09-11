#!/usr/bin/env python3
"""Actual persistent job + FFmpeg smoke test. Uses isolated SQLite only for this offline test."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker') if (ROOT / 'worker').exists() else str(ROOT))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import Settings
from app.db.models import Asset, Base, Job, Topic, Video
from app.pipeline import process_job
from app.queue import claim_next
from app.services.mock import SAMPLE_TOPIC
from app.services.media import probe, validate_render


async def main():
    root = Path(os.environ.get('SMOKE_OUTPUT_DIR', tempfile.mkdtemp(prefix='videott-smoke-'))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    config = Settings(_env_file=None, database_url='sqlite://', media_root=root,
                      llm_provider='mock', stock_provider='mock', tts_provider='mock', allow_test_mode=True,
                      ffmpeg_bin=os.environ.get('FFMPEG_BIN', 'ffmpeg'), ffprobe_bin=os.environ.get('FFPROBE_BIN', 'ffprobe'))
    engine = create_engine('sqlite:///' + str(root / 'smoke.sqlite'))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as db:
        topic = Topic(title=SAMPLE_TOPIC)
        db.add(topic)
        db.flush()
        video = Video(topic_id=topic.id, is_test=True)
        db.add(video)
        db.flush()
        job = Job(video_id=video.id)
        db.add(job)
        db.flush()
        job_id, video_id = job.id, video.id
    claimed = claim_next(sessions)
    assert claimed == job_id
    await process_job(job_id, config, sessions)
    with sessions() as db:
        job = db.get(Job, job_id)
        assert job.status == 'READY', (job.status, job.error_code, job.error_message)
        assert db.query(Asset).filter_by(video_id=video_id).count() == 9
    directory = root / 'output' / str(video_id)
    assert {p.name for p in directory.iterdir()} == {'final.mp4', 'caption.txt', 'metadata.json', 'rights_manifest.json'}
    duration = validate_render(await probe(directory / 'final.mp4', config), config)
    manifest = json.loads((directory / 'rights_manifest.json').read_text())
    assert len(manifest['assets']) == 9 and manifest['is_test']
    print(f'SMOKE PASS: 1080x1920, 30 fps, H.264/AAC, {duration:.2f}s, 9 scenes, animated ASS subtitles')
    print('SYNTHETIC FIXTURE with test tone; does not test live OpenRouter/OpenAI/Pexels/Edge services.')
    print(directory)


if __name__ == '__main__':
    asyncio.run(main())
