import re
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

Text = Annotated[str, Field(min_length=1, max_length=12000)]
VisualQuery = Annotated[str, Field(min_length=3, max_length=150)]


def narration_word_count(text):
    return len(re.findall(r"\b[\w'-]+\b", text))


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


class EvidencePair(StrictModel):
    source_url: Text
    quote: Text


class ExtractedFact(StrictModel):
    id: Text
    text: Text
    evidence: list[EvidencePair] = Field(min_length=1, max_length=6)


class ResearchExtraction(StrictModel):
    """LLM wire format pairs each source with its quote; storage stays compatible."""

    topic: Text
    summary: Text
    facts: list[ExtractedFact] = Field(min_length=2, max_length=16)

    def to_research(self):
        return ResearchResult(
            topic=self.topic,
            summary=self.summary,
            facts=[
                Fact(
                    id=fact.id,
                    text=fact.text,
                    source_urls=[pair.source_url for pair in fact.evidence],
                    evidence_quotes=[pair.quote for pair in fact.evidence],
                )
                for fact in self.facts
            ],
        )


class ScenePlan(StrictModel):
    order: int = Field(ge=1, le=16)
    narration: Text
    visual_query: VisualQuery
    # Optional so scripts stored before the fallback existed still validate.
    visual_query_fallback: VisualQuery | None = None
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
    hashtags: list[Annotated[str, Field(pattern=r"^[A-Za-zА-Яа-яЁё0-9_]{1,40}$")]] = Field(
        min_length=3, max_length=6
    )

    @field_validator("hook")
    @classmethod
    def hook_length(cls, value):
        words = len(value.split())
        if words > 10:
            raise PydanticCustomError(
                "hook_word_count",
                "Opening hook must contain at most 10 words; got {actual}",
                {"actual": words},
            )
        return value

    @field_validator("narration")
    @classmethod
    def narration_length(cls, value):
        words = narration_word_count(value)
        if not 120 <= words <= 215:
            raise PydanticCustomError(
                "narration_word_count",
                "Narration must contain 120–215 words; got {actual}",
                {"actual": words},
            )
        return value

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
        return self


class SceneDraft(StrictModel):
    narration: Text = Field(description="Scene body ONLY. Do not repeat the separate hook or payoff.")
    visual_query: VisualQuery = Field(
        description="English Pexels query describing the shot to film, not the object named in the narration."
    )
    visual_query_fallback: VisualQuery = Field(
        description="Broader English Pexels query for a thematically close shot stock libraries certainly have."
    )
    duration_hint: float = Field(gt=0, le=20)
    fact_ids: list[Text] = Field(min_length=1, max_length=16)


class ScriptDraft(StrictModel):
    """Generate each spoken fragment once; derive the existing public Script format."""

    title: Annotated[str, Field(min_length=1, max_length=160)]
    hook: Annotated[str, Field(min_length=1, max_length=200)] = Field(
        description="A separate opening sentence, 4–8 words. NOT the full first scene."
    )
    payoff: Annotated[str, Field(min_length=1, max_length=300)] = Field(
        description="A separate final sentence, about 8–12 words. Do not repeat it in scene bodies."
    )
    estimated_duration: float = Field(ge=60, le=90)
    scenes: list[SceneDraft] = Field(min_length=8, max_length=16)
    caption: Annotated[str, Field(min_length=1, max_length=1500)]
    hashtags: list[Annotated[str, Field(pattern=r"^[A-Za-zА-Яа-яЁё0-9_]{1,40}$")]] = Field(
        min_length=3, max_length=6
    )

    def assembled_data(self):
        data = self.model_dump()
        scenes = data["scenes"]
        for order, scene in enumerate(scenes, start=1):
            scene["order"] = order
        scenes[0]["narration"] = self.hook + " " + scenes[0]["narration"]
        scenes[-1]["narration"] += " " + self.payoff
        data["narration"] = " ".join(scene["narration"] for scene in scenes)
        return data

    def to_script(self):
        return Script.model_validate(self.assembled_data())


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
