import enum
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EdgeStatus(str, enum.Enum):
    proposed = "proposed"
    accepted = "accepted"
    rejected = "rejected"


class ConceptEdge(Base):
    __tablename__ = "concept_edge"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    # Edge references concept UUIDs; we intentionally do NOT FK them because
    # concepts live in dim-sharded tables. The service layer enforces integrity.
    src_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    dst_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    relation: Mapped[str] = mapped_column(String(100), default="related-to")
    status: Mapped[EdgeStatus] = mapped_column(
        SAEnum(EdgeStatus, name="edge_status"), default=EdgeStatus.proposed
    )
    confidence: Mapped[float] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
