import hashlib
import secrets
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBearer
from sqlalchemy import exists, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Asset, Job, Research, Source, Topic, Video
from app.db.session import SessionLocal, get_db
from app.logging import configure_logging
from app.schemas import TERMINAL, Status, TopicCreate, VideoCreate

settings = get_settings()
bearer = HTTPBearer(auto_error=False)
basic = HTTPBasic(auto_error=False)


def authenticate(token=Depends(bearer), login=Depends(basic)):
    supplied = (
        token.credentials if token else (login.password if login and login.username == "videott" else "")
    )
    expected = settings.worker_api_key.get_secret_value()
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            401, "Authentication required", headers={"WWW-Authenticate": 'Basic realm="VideoTT"'}
        )


@asynccontextmanager
async def lifespan(app):
    settings.require_auth()
    configure_logging()
    yield


app = FastAPI(
    title="VideoTT",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
    description="Original video creation. Manual publishing only. Videos provided by Pexels: https://www.pexels.com",
)
api = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])
Db = Annotated[Session, Depends(get_db)]


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable; retry later"})


@app.get("/health")
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/docs", include_in_schema=False, dependencies=[Depends(authenticate)])
def docs():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="VideoTT API")


@app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(authenticate)])
def openapi():
    return app.openapi()


def lookup(db, model, id):
    row = db.get(model, id)
    if not row:
        raise HTTPException(404, "Not found")
    return row


def serialize(row, exclude=()):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in exclude}


def lock_creation(db):
    # Serializes low-volume create/retry operations and makes idempotency and queue limits atomic.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(765443201)"))


def check_queue_limit(db):
    pending = db.scalar(select(func.count()).select_from(Job).where(Job.status.not_in(TERMINAL)))
    if pending >= settings.max_queued_jobs:
        raise HTTPException(429, "Queue is full; wait for pending jobs")


@api.post("/topics", status_code=201)
def create_topic(body: TopicCreate, db: Db):
    lock_creation(db)
    topic = db.scalar(select(Topic).where(Topic.title == body.title))
    if not topic:
        topic = Topic(title=body.title)
        db.add(topic)
        db.commit()
    return serialize(topic)


@api.get("/topics")
def topics(db: Db, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    return [
        serialize(t) for t in db.scalars(select(Topic).order_by(Topic.created_at).offset(offset).limit(limit))
    ]


@api.post("/videos", status_code=202)
def create_video(body: VideoCreate, db: Db, idempotency_key: str | None = Header(None, max_length=160)):
    lock_creation(db)
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if existing:
            if existing.request_digest != fingerprint:
                raise HTTPException(409, "Idempotency-Key already used for a different request")
            return {"job_id": existing.id, "video_id": existing.video_id, "status": existing.status}
    check_queue_limit(db)
    if body.topic_id:
        topic = lookup(db, Topic, body.topic_id)
    elif body.topic:
        topic = db.scalar(select(Topic).where(Topic.title == body.topic))
        if not topic:
            topic = Topic(title=body.topic)
            db.add(topic)
            db.flush()
    else:
        topic = db.scalar(
            select(Topic)
            .where(~exists().where(Video.topic_id == Topic.id))
            .order_by(Topic.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not topic:
            raise HTTPException(409, "NO_UNUSED_TOPICS: add topics before running the schedule")
    video = Video(topic_id=topic.id, is_test=settings.is_test)
    db.add(video)
    db.flush()
    job = Job(video_id=video.id, idempotency_key=idempotency_key, request_digest=fingerprint)
    db.add(job)
    db.commit()
    return {"job_id": job.id, "video_id": video.id, "status": job.status}


@api.get("/videos")
def videos(
    db: Db, status: Status | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
):
    query = select(Video).order_by(Video.created_at.desc()).offset(offset).limit(limit)
    if status:
        query = query.where(Video.status == status)
    return [
        {
            **serialize(v, ("script", "evaluation")),
            "download_url": f"/api/v1/videos/{v.id}/download",
            "caption_url": f"/api/v1/videos/{v.id}/caption",
        }
        for v in db.scalars(query)
    ]


@api.get("/videos/{video_id}")
def get_video(video_id: UUID, db: Db):
    video = lookup(db, Video, video_id)
    research = db.scalar(select(Research).where(Research.video_id == video_id))
    return {
        **serialize(video),
        "topic": lookup(db, Topic, video.topic_id).title,
        "research": research.result if research else None,
        "sources": [serialize(s) for s in db.scalars(select(Source).where(Source.video_id == video_id))],
        "asset_count": db.scalar(select(func.count()).select_from(Asset).where(Asset.video_id == video_id)),
        "download_url": f"/api/v1/videos/{video_id}/download",
        "caption_url": f"/api/v1/videos/{video_id}/caption",
    }


@api.get("/jobs/{job_id}")
def get_job(job_id: UUID, db: Db):
    return serialize(lookup(db, Job, job_id), ("idempotency_key", "request_digest"))


@api.post("/videos/{video_id}/render", status_code=202)
def retry_video(video_id: UUID, db: Db):
    lock_creation(db)
    video = lookup(db, Video, video_id)
    if video.status == Status.READY:
        raise HTTPException(409, "Video is already ready; create a new video for a different version")
    active = db.scalar(select(Job).where(Job.video_id == video_id, Job.status.not_in(TERMINAL)))
    if active:
        return {"job_id": active.id, "video_id": video_id, "status": active.status}
    check_queue_limit(db)
    video.status = Status.QUEUED
    video.error_code = video.error_message = None
    video.script = video.evaluation = None
    job = Job(video_id=video_id)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Video already has a pending job") from None
    return {"job_id": job.id, "video_id": video_id, "status": job.status}


def output_file(video_id, db, filename, media_type):
    video = lookup(db, Video, video_id)
    if video.status != Status.READY:
        raise HTTPException(409, "Video is not READY")
    path = settings.media_root / "output" / str(video_id) / filename
    if not path.is_file():
        raise HTTPException(404, "Output file is missing; check media volume")
    return FileResponse(
        path,
        media_type=media_type,
        filename=f"{video_id}-{filename}",
        headers={"Cache-Control": "private, no-store"},
    )


@api.get("/videos/{video_id}/download")
def download(video_id: UUID, db: Db):
    return output_file(video_id, db, "final.mp4", "video/mp4")


@api.get("/videos/{video_id}/caption")
def caption(video_id: UUID, db: Db):
    return output_file(video_id, db, "caption.txt", "text/plain")


@api.get("/videos/{video_id}/manifest")
def manifest(video_id: UUID, db: Db):
    return output_file(video_id, db, "rights_manifest.json", "application/json")


@api.get("/videos/{video_id}/metadata")
def metadata(video_id: UUID, db: Db):
    return output_file(video_id, db, "metadata.json", "application/json")


app.include_router(api)
