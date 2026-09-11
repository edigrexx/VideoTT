import pytest
from fastapi.testclient import TestClient

from app.db.models import Job, Topic, Video
from app.db.session import get_db
from app.main import app, settings
from app.queue import claim_next, recover_interrupted, set_stage
from app.schemas import Status, can_transition


@pytest.fixture
def client(sessions, tmp_path, monkeypatch):
    def override():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(settings, "media_root", tmp_path)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + settings.worker_api_key.get_secret_value()
        yield client
    app.dependency_overrides.clear()


def test_api_auth_including_download_and_docs(client):
    client.headers.pop("Authorization")
    for path in [
        "/api/v1/topics",
        "/api/v1/videos",
        "/docs",
        "/openapi.json",
        "/api/v1/videos/11111111-1111-1111-1111-111111111111/download",
    ]:
        assert client.get(path).status_code == 401
    assert (
        client.get("/openapi.json", auth=("videott", settings.worker_api_key.get_secret_value())).status_code
        == 200
    )


def test_idempotency_queue_and_topic_consumption(client):
    assert client.post("/api/v1/topics", json={"title": "Topic one for test"}).status_code == 201
    response = client.post("/api/v1/videos", json={}, headers={"Idempotency-Key": "request-1"})
    assert response.status_code == 202
    duplicate = client.post("/api/v1/videos", json={}, headers={"Idempotency-Key": "request-1"})
    assert duplicate.json() == response.json()
    assert (
        client.post(
            "/api/v1/videos", json={"topic": "A different topic"}, headers={"Idempotency-Key": "request-1"}
        ).status_code
        == 409
    )
    assert client.post("/api/v1/videos", json={}).status_code == 409
    video_id = response.json()["video_id"]
    assert client.get(f"/api/v1/videos/{video_id}/download").status_code == 409
    assert client.post(f"/api/v1/videos/{video_id}/render").json()["job_id"] == response.json()["job_id"]


def test_persistent_recovery_and_max_attempts(sessions):
    with sessions.begin() as db:
        topic = Topic(title="A test topic")
        db.add(topic)
        db.flush()
        video = Video(topic_id=topic.id)
        db.add(video)
        db.flush()
        job = Job(video_id=video.id)
        db.add(job)
        db.flush()
        job_id = job.id
    assert claim_next(sessions) == job_id
    assert claim_next(sessions) is None
    set_stage(sessions, job_id, Status.SCRIPTING)
    with pytest.raises(ValueError):
        set_stage(sessions, job_id, Status.READY)
    recover_interrupted(sessions, max_attempts=2)
    assert claim_next(sessions) == job_id
    recover_interrupted(sessions, max_attempts=2)
    with sessions() as db:
        job = db.get(Job, job_id)
        assert job.status == Status.FAILED and job.attempts == 2
        assert db.get(Video, job.video_id).status == Status.FAILED
    assert not can_transition(Status.READY, Status.RENDERING)


def test_ready_file_is_authenticated_and_range_supported(client, sessions, tmp_path):
    from uuid import UUID

    response = client.post("/api/v1/videos", json={"topic": "A topic to finish"}).json()
    video_id = UUID(response["video_id"])
    with sessions.begin() as db:
        db.get(Video, video_id).status = Status.READY
    out = tmp_path / "output" / str(video_id)
    out.mkdir(parents=True)
    (out / "final.mp4").write_bytes(b"0123456789")
    response = client.get(f"/api/v1/videos/{video_id}/download", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206 and response.content == b"0123"
    assert client.post(f"/api/v1/videos/{video_id}/render").status_code == 409


def test_stale_attempt_cannot_change_job(sessions):
    from app.errors import LostOwnership

    with sessions.begin() as db:
        topic = Topic(title="Stale attempt test")
        db.add(topic)
        db.flush()
        video = Video(topic_id=topic.id)
        db.add(video)
        db.flush()
        job = Job(video_id=video.id)
        db.add(job)
        db.flush()
        job_id = job.id
    claim_next(sessions)
    recover_interrupted(sessions, 3)
    claim_next(sessions)
    with pytest.raises(LostOwnership):
        set_stage(sessions, job_id, Status.FAILED, expected_attempt=1)
    with sessions() as db:
        assert db.get(Job, job_id).status == Status.RESEARCHING
