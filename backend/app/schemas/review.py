from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class ReviewItemOut(BaseModel):
    id: UUID
    concept_id: UUID
    concept_name: str
    embed_dim: int
    ease: float
    interval_days: int
    due_at: datetime
    last_score: float | None


class ReviewStartIn(BaseModel):
    review_item_id: UUID
