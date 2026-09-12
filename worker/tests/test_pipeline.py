from sqlalchemy import select

from app.config import Settings
from app.db.models import Job, Research, Topic, Video
from app.pipeline import process_job
from app.queue import claim_next
from app.schemas import Evaluation, Status
from app.services.mock import SAMPLE_TOPIC, MockLLMProvider


async def test_invalid_evidence_is_saved_but_never_reaches_scripting(sessions, tmp_path, monkeypatch, sample):
    research, sources, _ = sample
    research.facts[0].evidence_quotes = ["This evidence does not occur in the actual sources."]

    async def invalid(*args):
        return research, sources

    async def must_not_write(*args):
        raise AssertionError("Invalid evidence reached scripting")

    monkeypatch.setattr(MockLLMProvider, "research_topic", invalid)
    monkeypatch.setattr(MockLLMProvider, "generate_script", must_not_write)
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
    claim_next(sessions)
    config = Settings(
        _env_file=None,
        media_root=tmp_path,
        llm_provider="mock",
        stock_provider="mock",
        tts_provider="mock",
        allow_test_mode=True,
    )
    await process_job(job_id, config, sessions)
    with sessions() as db:
        assert db.get(Job, job_id).status == Status.NEEDS_REVIEW
        assert db.get(Job, job_id).error_code == "FACT_EVIDENCE"
        assert db.get(Video, video_id).script is None
        assert (
            db.scalar(select(Research).where(Research.video_id == video_id)).result == research.model_dump()
        )
    assert not list(tmp_path.rglob("*.mp4"))


async def test_rejected_facts_never_download_or_render(sessions, tmp_path, monkeypatch):
    async def reject(*args):
        return Evaluation(
            supported=False,
            confidence=0.2,
            contradictions=[],
            unsupported_claims=["Unverified claim"],
            explanation="Not enough evidence",
        )

    monkeypatch.setattr(MockLLMProvider, "evaluate_script", reject)
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
    claim_next(sessions)
    config = Settings(
        _env_file=None,
        media_root=tmp_path,
        llm_provider="mock",
        stock_provider="mock",
        tts_provider="mock",
        allow_test_mode=True,
    )
    await process_job(job_id, config, sessions)
    with sessions() as db:
        assert db.get(Job, job_id).status == Status.NEEDS_REVIEW
        assert db.get(Video, video_id).evaluation["confidence"] == 0.2
    assert not list(tmp_path.rglob("*.mp4"))


async def test_exception_secrets_are_not_persisted(sessions, tmp_path, monkeypatch):
    async def fail(*args):
        raise RuntimeError("secret-api-token-should-not-leak")

    monkeypatch.setattr(MockLLMProvider, "research_topic", fail)
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
        job_id = job.id
    claim_next(sessions)
    config = Settings(
        _env_file=None,
        media_root=tmp_path,
        llm_provider="mock",
        stock_provider="mock",
        tts_provider="mock",
        allow_test_mode=True,
    )
    await process_job(job_id, config, sessions)
    with sessions() as db:
        job = db.get(Job, job_id)
        assert job.status == Status.FAILED
        assert "secret-api-token" not in job.error_message
