from sqlalchemy import select

from app.db.models import Job, Video, now
from app.errors import LostOwnership
from app.schemas import ACTIVE, Status, can_transition


def set_stage(session_factory, job_id, status, error_code=None, error_message=None, expected_attempt=None):
    with session_factory.begin() as db:
        job = db.get(Job, job_id, with_for_update=True)
        if expected_attempt is not None and (job.attempts != expected_attempt or job.status == Status.QUEUED):
            raise LostOwnership()
        if not can_transition(job.status, status):
            raise ValueError(f"Invalid transition: {job.status} -> {status}")
        job.status = status
        job.error_code, job.error_message = error_code, error_message
        video = db.get(Video, job.video_id)
        video.status = status
        video.error_code, video.error_message = error_code, error_message


def recover_interrupted(session_factory, max_attempts):
    """Only called while holding the exclusive PostgreSQL runner advisory lock."""
    with session_factory.begin() as db:
        jobs = db.scalars(select(Job).where(Job.status.in_(ACTIVE)).with_for_update()).all()
        for job in jobs:
            video = db.get(Video, job.video_id)
            job.status = video.status = Status.QUEUED if job.attempts < max_attempts else Status.FAILED
            job.error_code = video.error_code = "WORKER_INTERRUPTED"
            job.error_message = video.error_message = (
                "Worker restarted; retry queued"
                if job.status == Status.QUEUED
                else "Restart attempt limit reached"
            )


def claim_next(session_factory):
    with session_factory.begin() as db:
        job = db.scalar(
            select(Job)
            .where(Job.status == Status.QUEUED)
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        job.status = Status.RESEARCHING
        job.attempts += 1
        job.error_code = job.error_message = None
        video = db.get(Video, job.video_id)
        video.status = Status.RESEARCHING
        video.error_code = video.error_message = None
        video.updated_at = now()
        db.flush()
        return job.id
