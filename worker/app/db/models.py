from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Topic(Record, Base):
    __tablename__ = "topics"
    title: Mapped[str] = mapped_column(String(300), unique=True)


class Video(Record, Base):
    __tablename__ = "videos"
    topic_id: Mapped[UUID] = mapped_column(ForeignKey("topics.id"))
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    script: Mapped[dict | None] = mapped_column(JSON)
    evaluation: Mapped[dict | None] = mapped_column(JSON)
    duration: Mapped[float | None] = mapped_column(Float)
    is_test: Mapped[bool] = mapped_column(default=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)


class Research(Record, Base):
    __tablename__ = "research_results"
    video_id: Mapped[UUID] = mapped_column(ForeignKey("videos.id"), unique=True)
    result: Mapped[dict] = mapped_column(JSON)


class Source(Record, Base):
    __tablename__ = "research_sources"
    video_id: Mapped[UUID] = mapped_column(ForeignKey("videos.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    excerpt: Mapped[str] = mapped_column(Text)


class Scene(Record, Base):
    __tablename__ = "scenes"
    video_id: Mapped[UUID] = mapped_column(ForeignKey("videos.id"), index=True)
    order: Mapped[int] = mapped_column(Integer)
    plan: Mapped[dict] = mapped_column(JSON)
    duration: Mapped[float | None] = mapped_column(Float)


class Asset(Record, Base):
    __tablename__ = "assets"
    video_id: Mapped[UUID] = mapped_column(ForeignKey("videos.id"), index=True)
    scene_id: Mapped[UUID] = mapped_column(ForeignKey("scenes.id"))
    provider: Mapped[str] = mapped_column(String(40))
    provider_asset_id: Mapped[str] = mapped_column(String(100))
    author: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    asset_url: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))


class Job(Record, Base):
    __tablename__ = "jobs"
    video_id: Mapped[UUID] = mapped_column(ForeignKey("videos.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    request_digest: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index(
            "one_active_job_per_video",
            "video_id",
            unique=True,
            postgresql_where=text("status NOT IN ('READY', 'FAILED', 'NEEDS_REVIEW')"),
            sqlite_where=text("status NOT IN ('READY', 'FAILED', 'NEEDS_REVIEW')"),
        ),
    )
