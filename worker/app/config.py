from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr | None = None
    postgres_host: str = "postgres"
    postgres_app_password: SecretStr = SecretStr("")
    worker_api_key: SecretStr = SecretStr("")
    llm_provider: Literal["openai", "openrouter", "mock"] = "openai"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    openrouter_max_tokens: int = Field(8192, ge=1024, le=32768)
    openrouter_max_searches: int = Field(2, ge=1, le=4)
    openrouter_reasoning_tokens: int = Field(1024, ge=0, le=8192)
    pexels_api_key: SecretStr = SecretStr("")
    tts_provider: Literal["edge", "mock"] = "edge"
    content_language: Literal["ru-RU", "en-US"] = "ru-RU"
    tts_voice: str = "ru-RU-SvetlanaNeural"
    stock_provider: Literal["pexels", "mock"] = "pexels"
    allow_test_mode: bool = False
    media_root: Path = Path("/data/media")
    min_video_duration_sec: float = Field(60, ge=1)
    max_video_duration_sec: float = Field(90, ge=1, le=180)
    max_asset_size_mb: int = Field(120, ge=1, le=500)
    max_download_retries: int = Field(3, ge=1, le=5)
    http_timeout_sec: float = Field(30, ge=1, le=120)
    llm_timeout_sec: float = Field(120, ge=10, le=300)
    tts_timeout_sec: float = Field(180, ge=10, le=600)
    ffmpeg_timeout_sec: float = Field(900, ge=10, le=3600)
    job_timeout_sec: float = Field(3600, ge=60, le=7200)
    max_job_attempts: int = Field(3, ge=1, le=5)
    max_queued_jobs: int = Field(20, ge=1, le=100)
    poll_interval_sec: float = Field(3, ge=0.1, le=30)
    min_fact_confidence: float = Field(0.85, ge=0, le=1)
    ffmpeg_threads: int = Field(2, ge=1, le=16)
    ffmpeg_preset: str = "veryfast"
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    @model_validator(mode="after")
    def check_config(self):
        if self.tts_provider == "edge" and not self.tts_voice.startswith(self.content_language + "-"):
            raise ValueError("TTS_VOICE locale must match CONTENT_LANGUAGE (ru-RU or en-US)")
        if self.openrouter_reasoning_tokens >= self.openrouter_max_tokens:
            raise ValueError("OpenRouter reasoning budget must be smaller than the total output budget")
        if self.min_video_duration_sec > self.max_video_duration_sec:
            raise ValueError("Minimum duration exceeds maximum")
        if self.ffmpeg_preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}:
            raise ValueError("Invalid FFmpeg preset")
        if self.is_test and not self.allow_test_mode:
            raise ValueError("Mock providers require ALLOW_TEST_MODE=true")
        if self.is_test and not all(
            p == "mock" for p in (self.llm_provider, self.tts_provider, self.stock_provider)
        ):
            raise ValueError(
                "Use all three mock providers together; mock research must not look like production"
            )
        return self

    @property
    def is_test(self):
        return "mock" in (self.llm_provider, self.tts_provider, self.stock_provider)

    @property
    def language_instruction(self):
        language = "Russian" if self.content_language == "ru-RU" else "English"
        return (
            f"Write audience-facing text and explanations in {language}. "
            "Keep JSON field names, IDs, URLs and proper names unchanged. "
            "Keep the input topic verbatim and evidence_quotes in their ORIGINAL source language; "
            "never translate evidence quotes. Write visual_query and visual_query_fallback in English "
            "for Pexels search."
        )

    @property
    def db_url(self):
        if self.database_url:
            return self.database_url.get_secret_value()
        return URL.create(
            "postgresql+psycopg",
            username="videott",
            password=self.postgres_app_password.get_secret_value(),
            host=self.postgres_host,
            database="videott",
        )

    def require_auth(self):
        if len(self.worker_api_key.get_secret_value()) < 32:
            raise ValueError("WORKER_API_KEY must contain at least 32 characters")


@lru_cache
def get_settings():
    return Settings()
