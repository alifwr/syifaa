from uuid import UUID
from pydantic import BaseModel


class ConceptOut(BaseModel):
    id: UUID
    name: str
    summary: str
    stage: str
