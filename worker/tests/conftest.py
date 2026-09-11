import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("WORKER_API_KEY", "test-api-key-at-least-32-characters-long")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base


@pytest.fixture
def sessions():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
async def sample():
    from app.services.mock import SAMPLE_TOPIC, MockLLMProvider

    provider = MockLLMProvider()
    research, sources = await provider.research_topic(SAMPLE_TOPIC)
    return research, sources, await provider.generate_script(research)
