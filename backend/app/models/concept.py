import enum
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, DateTime, Enum as SAEnum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ConceptStage(str, enum.Enum):
    new = "new"
    learning = "learning"
    fluent = "fluent"
    teach = "teach"


class _ConceptBase:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    source_paper_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), default=list)
    stage: Mapped[ConceptStage] = mapped_column(
        SAEnum(ConceptStage, name="concept_stage"), default=ConceptStage.new
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def _make_concept_model(dim: int) -> type:
    return type(
        f"Concept{dim}",
        (_ConceptBase, Base),
        {
            "__tablename__": f"concept_{dim}",
            "embedding": mapped_column(Vector(dim)),
        },
    )


Concept768 = _make_concept_model(768)
Concept1024 = _make_concept_model(1024)
Concept1536 = _make_concept_model(1536)

_CONCEPT_MODELS = {768: Concept768, 1024: Concept1024, 1536: Concept1536}


def concept_model_for(dim: int):
    try:
        return _CONCEPT_MODELS[dim]
    except KeyError:
        raise ValueError(f"unsupported embed_dim {dim}; pick one of {sorted(_CONCEPT_MODELS)}")
