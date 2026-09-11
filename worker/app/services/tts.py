import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import edge_tts

from app.errors import PipelineError
from app.services.media import duration_of, probe, run_process


@dataclass
class Cue:
    start: float
    end: float
    text: str


class TTSProvider(Protocol):
    async def synthesize(self, text: str, path: Path) -> list[Cue]: ...


class EdgeTTSProvider:
    def __init__(self, settings):
        self.settings = settings

    async def synthesize(self, text, path):
        for attempt in range(3):
            try:
                cues = []
                async with asyncio.timeout(self.settings.tts_timeout_sec):
                    communicate = edge_tts.Communicate(
                        text,
                        self.settings.tts_voice,
                        boundary="WordBoundary",
                        connect_timeout=15,
                        receive_timeout=60,
                    )
                    with path.open("wb") as handle:
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                handle.write(chunk["data"])
                            elif chunk["type"] in {"WordBoundary", "SentenceBoundary"}:
                                start = chunk["offset"] / 10_000_000
                                cues.append(Cue(start, start + chunk["duration"] / 10_000_000, chunk["text"]))
                if path.stat().st_size == 0:
                    raise ValueError("empty audio")
                return cues
            except Exception:
                path.unlink(missing_ok=True)
                if attempt == 2:
                    raise PipelineError(
                        "TTS_FAILED",
                        "Edge TTS unavailable after three attempts; retry later or check voice/connectivity",
                    ) from None
                await asyncio.sleep(2**attempt)


class MockTTSProvider:
    def __init__(self, settings):
        self.settings = settings

    async def synthesize(self, text, path):
        # Quiet test tone, explicitly watermarked in rendered video; not fake narration.
        duration = len(text.split()) / 2.5
        await run_process(
            [
                self.settings.ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=220:sample_rate=24000:duration={duration}",
                "-af",
                "volume=0.05",
                "-c:a",
                "libmp3lame",
                str(path),
            ],
            30,
        )
        words = text.split()
        return [
            Cue(i * duration / len(words), (i + 1) * duration / len(words), word)
            for i, word in enumerate(words)
        ]


async def build_narration(script, directory, settings, provider):
    directory.mkdir(parents=True, exist_ok=True)
    all_cues, durations = [], []
    offset = 0.0
    for scene in script.scenes:
        mp3 = directory / f"scene-{scene.order}.mp3"
        wav = directory / f"scene-{scene.order}.wav"
        cues = await provider.synthesize(scene.narration, mp3)
        await run_process(
            [
                settings.ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-i",
                str(mp3),
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            60,
        )
        duration = duration_of(await probe(wav, settings))
        durations.append(duration)
        if not cues:
            words = scene.narration.split()
            cues = [
                Cue(i * duration / len(words), (i + 1) * duration / len(words), word)
                for i, word in enumerate(words)
            ]
        for cue in cues:
            # Split sentence boundaries proportionally when word timing is unavailable.
            words = cue.text.split()
            for i, word in enumerate(words):
                start = min(cue.start + (cue.end - cue.start) * i / len(words), duration)
                end = min(cue.start + (cue.end - cue.start) * (i + 1) / len(words), duration)
                if end > start:
                    all_cues.append(Cue(offset + start, offset + end, word))
        offset += duration
    # Keep speech natural; excessive duration is actionable instead of silently cutting the narration.
    if not settings.min_video_duration_sec <= offset <= settings.max_video_duration_sec:
        raise PipelineError(
            "NARRATION_DURATION",
            "Actual speech duration is outside limits; regenerate the script or adjust voice",
        )
    (directory / "concat.txt").write_text("\n".join(f"file 'scene-{s.order}.wav'" for s in script.scenes))
    audio = directory / "narration.wav"
    await run_process(
        [
            settings.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            "concat.txt",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            str(audio),
        ],
        60,
        cwd=directory,
    )
    measured = duration_of(await probe(audio, settings))
    (directory / "timings.json").write_text(
        json.dumps([vars(cue) for cue in all_cues], ensure_ascii=False, indent=2)
    )
    return audio, durations, all_cues, measured
