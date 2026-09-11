import re
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=12000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Status(StrEnum):
    QUEUED = "QUEUED"
    RESEARCHING = "RESEARCHING"
    SCRIPTING = "SCRIPTING"
    FETCHING_ASSETS = "FETCHING_ASSETS"
    GENERATING_TTS = "GENERATING_TTS"
    RENDERING = "RENDERING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


TERMINAL = {Status.READY, Status.FAILED, Status.NEEDS_REVIEW}
ACTIVE = set(Status) - TERMINAL - {Status.QUEUED}
STAGES = list(Status)[:8]


def can_transition(before: str, after: str):
    if before in TERMINAL:
        return False
    return after in {Status.FAILED, Status.NEEDS_REVIEW} or (
        before in STAGES[:-1] and after == STAGES[STAGES.index(before) + 1]
    )


class SourceCandidate(StrictModel):
    title: Text
    url: Text


class Fact(StrictModel):
    id: Text
    text: Text
    source_urls: list[Text] = Field(min_length=1, max_length=6)
    evidence_quotes: list[Text] = Field(min_length=1, max_length=6)


class ResearchResult(StrictModel):
    topic: Text
    summary: Text
    facts: list[Fact] = Field(min_length=2, max_length=16)


class ScenePlan(StrictModel):
    order: int = Field(ge=1, le=16)
    narration: Text
    visual_query: Annotated[str, Field(min_length=3, max_length=150)]
    duration_hint: float = Field(gt=0, le=20)
    fact_ids: list[Text] = Field(min_length=1, max_length=16)


class Script(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=160)]
    hook: Annotated[str, Field(min_length=1, max_length=200)]
    payoff: Annotated[str, Field(min_length=1, max_length=300)]
    narration: Text
    estimated_duration: float = Field(ge=60, le=90)
    scenes: list[ScenePlan] = Field(min_length=8, max_length=16)
    caption: Annotated[str, Field(min_length=1, max_length=1500)]
    hashtags: list[Annotated[str, Field(pattern=r"^[A-Za-zА-Яа-яЁё0-9_]{1,40}$")]] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def consistency(self):
        def norm(s):
            return " ".join(s.split())

        if norm(self.narration) != norm(" ".join(s.narration for s in self.scenes)):
            raise ValueError("Narration must equal concatenated scene narration")
        if [s.order for s in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError("Scenes must be consecutive and ordered")
        if not self.narration.startswith(self.hook) or not self.narration.endswith(self.payoff):
            raise ValueError("Narration must start with hook and end with payoff")
        if len(self.hook.split()) > 10:
            raise ValueError("Keep the opening hook to 10 words or fewer")
        if not 135 <= len(re.findall(r"\b[\w'-]+\b", self.narration)) <= 215:
            raise ValueError("Narration must contain 135–215 words")
        return self


class Evaluation(StrictModel):
    supported: bool
    confidence: float = Field(ge=0, le=1)
    contradictions: list[Text]
    unsupported_claims: list[Text]
    explanation: Text


class TopicCreate(StrictModel):
    title: Annotated[str, Field(min_length=5, max_length=300)]


class VideoCreate(StrictModel):
    topic_id: UUID | None = None
    topic: Annotated[str, Field(min_length=5, max_length=300)] | None = None

    @model_validator(mode="after")
    def one_topic(self):
        if self.topic_id and self.topic:
            raise ValueError("Pass topic OR topic_id, or neither to take the next unused topic")
        return self
