from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FeynmanStartIn(BaseModel):
    paper_id: UUID | None = None
    kind: Literal["fresh", "scheduled"] = "fresh"


class FeynmanMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class FeynmanSessionOut(BaseModel):
    id: UUID
    user_id: UUID
    paper_id: UUID | None
    target_concept_id: UUID
    kind: str
    started_at: datetime
    ended_at: datetime | None
    quality_score: float | None
    transcript: list[dict]


class FeynmanGradeOut(BaseModel):
    quality_score: float
