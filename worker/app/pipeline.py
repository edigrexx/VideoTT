import asyncio
import shutil
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import delete

from app.db.models import Asset, Job, Research, Scene, Source, Topic, Video
from app.errors import LostOwnership, NeedsReview, PipelineError
from app.logging import event
from app.queue import set_stage
from app.schemas import TERMINAL, Status
from app.services.llm import OpenAIProvider
from app.services.media import probe, validate_render
from app.services.mock import MockLLMProvider
from app.services.output import write_output
from app.services.renderer import render
from app.services.research import validate_fact_evidence, validate_script_evidence
from app.services.stock import MockStockProvider, PexelsProvider
from app.services.subtitles import write_subtitles
from app.services.tts import EdgeTTSProvider, MockTTSProvider, build_narration


async def process_job(job_id, settings, session_factory):
    with session_factory() as db:
        job = db.get(Job, job_id)
        video = db.get(Video, job.video_id)
        video_id, attempt = video.id, job.attempts
        topic = db.get(Topic, video.topic_id).title
    job_root = settings.media_root / "jobs" / str(video_id)
    work = job_root / f"attempt-{attempt}-{job_id}"
    work.mkdir(parents=True, exist_ok=True)
    staging = work / "final"
    staging.mkdir(exist_ok=True)
    llm = None

    @contextmanager
    def owned_session():
        with session_factory.begin() as db:
            current = db.get(Job, job_id, with_for_update=True)
            if current.attempts != attempt or current.status in TERMINAL or current.status == Status.QUEUED:
                raise LostOwnership()
            yield db

    def stage(status):
        set_stage(session_factory, job_id, status, expected_attempt=attempt)
        event(status, job_id, video_id)

    try:
        async with asyncio.timeout(settings.job_timeout_sec):
            if video.is_test != settings.is_test:
                raise PipelineError(
                    "PROVIDER_MODE_CHANGED", "Provider mode changed after enqueue; retry in the original mode"
                )
            event("RESEARCHING", job_id, video_id, attempt=attempt)
            llm = MockLLMProvider() if settings.is_test else OpenAIProvider(settings)
            stock = MockStockProvider(settings) if settings.is_test else PexelsProvider(settings)
            tts = MockTTSProvider(settings) if settings.is_test else EdgeTTSProvider(settings)
            research, sources = await llm.research_topic(topic)
            # Persist research before validation so rejected facts remain inspectable.
            with owned_session() as db:
                for model in (Asset, Scene, Source, Research):
                    db.execute(delete(model).where(model.video_id == video_id))
                db.add(Research(video_id=video_id, result=research.model_dump()))
                for source in sources:
                    db.add(
                        Source(
                            video_id=video_id,
                            **{**source, "retrieved_at": datetime.fromisoformat(source["retrieved_at"])},
                        )
                    )
            validate_fact_evidence(research, sources)
            stage(Status.SCRIPTING)
            script = await llm.generate_script(research)
            with owned_session() as db:
                db.get(Video, video_id).script = script.model_dump()
            evaluation = await llm.evaluate_script(script, research, sources)
            with owned_session() as db:
                db.get(Video, video_id).evaluation = evaluation.model_dump()
            validate_script_evidence(script, research, evaluation, settings.min_fact_confidence)
            with owned_session() as db:
                scenes = [Scene(video_id=video_id, order=s.order, plan=s.model_dump()) for s in script.scenes]
                db.add_all(scenes)
                db.flush()
                scene_ids = [scene.id for scene in scenes]
            stage(Status.FETCHING_ASSETS)
            asset_dir = work / "assets"
            asset_dir.mkdir(exist_ok=True)
            assets, used, clips = [], set(), []
            for scene_id, scene in zip(scene_ids, script.scenes, strict=True):
                path = asset_dir / f"scene-{scene.order}.mp4"
                asset = await stock.fetch(scene.visual_query, used, path)
                asset.update(scene_id=scene_id, video_id=video_id)
                with owned_session() as db:
                    db.add(Asset(**asset))
                assets.append(asset)
                clips.append(path)
            stage(Status.GENERATING_TTS)
            audio, durations, cues, measured = await build_narration(script, work / "audio", settings, tts)
            with owned_session() as db:
                for scene_id, duration in zip(scene_ids, durations, strict=True):
                    db.get(Scene, scene_id).duration = duration
            subtitles = work / "subtitles.ass"
            write_subtitles(cues, measured, subtitles, settings.is_test)
            stage(Status.RENDERING)
            await render(clips, durations, audio, subtitles, staging / "final.mp4", work / "temp", settings)
            stage(Status.VALIDATING)
            duration = validate_render(await probe(staging / "final.mp4", settings), settings)
            write_output(staging, video_id, topic, script, sources, assets, duration, settings.is_test)
            output = settings.media_root / "output" / str(video_id)
            output.parent.mkdir(parents=True, exist_ok=True)
            # Directory rename is atomic on media_data. API serves it only after READY commits.
            with owned_session() as db:
                if output.exists():
                    shutil.rmtree(output)
                staging.rename(output)
                current_video = db.get(Video, video_id)
                current_video.duration = duration
                current_video.status = Status.READY
                db.get(Job, job_id).status = Status.READY
            event("READY", job_id, video_id)
            shutil.rmtree(work / "temp", ignore_errors=True)
            # Keep source clips, narration, timings and ASS for provenance/debugging.
    except LostOwnership:
        event("STALE_ATTEMPT_STOPPED", job_id, video_id)
    except asyncio.CancelledError:
        # Leave current stage persisted; next exclusive runner recovers it.
        event("INTERRUPTED", job_id, video_id)
        raise
    except Exception as exc:
        status = Status.NEEDS_REVIEW if isinstance(exc, NeedsReview) else Status.FAILED
        code = (
            exc.code
            if isinstance(exc, PipelineError)
            else ("JOB_TIMEOUT" if isinstance(exc, TimeoutError) else "PIPELINE_ERROR")
        )
        message = (
            exc.message
            if isinstance(exc, PipelineError)
            else f"Pipeline stopped ({type(exc).__name__}); check service configuration and retry"
        )
        try:
            set_stage(session_factory, job_id, status, code, message, expected_attempt=attempt)
        except LostOwnership:
            return
        event(status, job_id, video_id, error_code=code)
    finally:
        if llm and hasattr(llm, "close"):
            await llm.close()
