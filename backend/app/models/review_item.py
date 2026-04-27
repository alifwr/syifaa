from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime, Float, ForeignKey, Index, Integer, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReviewItem(Base):
    __tablename__ = "review_item"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    # Concept lives in a dim-sharded table; no FK, service layer enforces.
    concept_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    embed_dim: Mapped[int] = mapped_column(Integer)

    ease: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    last_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("feynman_session.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index(
            "uq_review_item_user_concept_dim",
            "user_id", "concept_id", "embed_dim",
            unique=True,
        ),
        Index(
            "ix_review_item_user_due",
            "user_id", "due_at",
        ),
    )
