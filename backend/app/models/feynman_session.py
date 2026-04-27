import enum
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime, Enum as SAEnum, ForeignKey, Integer, Numeric, Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FeynmanKind(str, enum.Enum):
    fresh = "fresh"
    scheduled = "scheduled"


class FeynmanSession(Base):
    __tablename__ = "feynman_session"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    paper_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("paper.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    # Concepts live in dim-sharded tables — no FK, service layer enforces.
    target_concept_id: Mapped[UUID] = mapped_column(Uuid, index=True)

    kind: Mapped[FeynmanKind] = mapped_column(
        SAEnum(FeynmanKind, name="feynman_kind"), default=FeynmanKind.fresh
    )
    embed_dim: Mapped[int] = mapped_column(Integer)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    quality_score: Mapped[float | None] = mapped_column(
        Numeric(5, 4), nullable=True,
    )
    # transcript = list of {"role": "user"|"assistant"|"system", "content": str, "ts": iso8601}
    transcript: Mapped[list[dict]] = mapped_column(JSONB, default=list)
