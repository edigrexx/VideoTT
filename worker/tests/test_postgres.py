import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.models import Base, Job, Topic, Video
from app.queue import claim_next, recover_interrupted

pytestmark = pytest.mark.integration


@pytest.fixture
def pg(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    engine = create_engine(url)
    # TEST_DATABASE_URL is explicitly a disposable DB. Never use production DATABASE_URL.
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    yield engine, config
    get_settings.cache_clear()
    engine.dispose()


def test_migration_roundtrip_and_uuid_timezone(pg):
    engine, config = pg
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0001"
        column = connection.execute(
            text(
                "SELECT data_type FROM information_schema.columns WHERE table_name='jobs' AND column_name='created_at'"
            )
        ).scalar()
        assert column == "timestamp with time zone"
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_pg_skip_locked_and_recovery(pg):
    engine, _ = pg
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as db:
        topic = Topic(title="PG queue test")
        db.add(topic)
        db.flush()
        video = Video(topic_id=topic.id)
        db.add(video)
        db.flush()
        job = Job(video_id=video.id)
        db.add(job)
        db.flush()
        job_id = job.id
    with sessions.begin() as first:
        first.scalar(select(Job).where(Job.id == job_id).with_for_update())
        assert claim_next(sessions) is None
    assert claim_next(sessions) == job_id
    recover_interrupted(sessions, 3)
    assert claim_next(sessions) == job_id
    with sessions() as db:
        assert db.get(Job, job_id).attempts == 2


def test_pg_runner_lock_exclusive(pg):
    engine, _ = pg
    with engine.connect() as first, engine.connect() as second:
        assert first.execute(text("SELECT pg_try_advisory_lock(765443200)")).scalar() is True
        assert second.execute(text("SELECT pg_try_advisory_lock(765443200)")).scalar() is False
        first.execute(text("SELECT pg_advisory_unlock(765443200)"))
        assert second.execute(text("SELECT pg_try_advisory_lock(765443200)")).scalar() is True
        second.execute(text("SELECT pg_advisory_unlock(765443200)"))
