from datetime import datetime
from pydantic import BaseModel


class SessionScorePoint(BaseModel):
    started_at: datetime
    quality_score: float


class DashboardOut(BaseModel):
    concept_count: int
    sessions: list[SessionScorePoint]
