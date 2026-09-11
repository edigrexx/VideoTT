import json
import logging
from datetime import datetime, timezone


def configure_logging():
    # Third-party HTTP exception strings can contain signed URLs. Never emit them.
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("videott").setLevel(logging.INFO)


def event(stage: str, job_id=None, video_id=None, **fields):
    logging.getLogger("videott").info(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": stage,
                "job_id": str(job_id) if job_id else None,
                "video_id": str(video_id) if video_id else None,
                **fields,
            }
        )
    )
