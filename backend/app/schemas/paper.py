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
