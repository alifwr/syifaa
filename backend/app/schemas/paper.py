from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class PaperOut(BaseModel):
    id: UUID
    title: str
    authors: str
    uploaded_at: datetime
    status: str
    parse_error: str | None = None
    chunks_count: int = 0
    concepts_count: int = 0
