from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, DateTime, Text, Enum as SAEnum
import enum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaperStatus(str, enum.Enum):
    uploaded = "uploaded"
    parsed = "parsed"
    failed = "failed"


class Paper(Base):
    __tablename__ = "paper"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[str] = mapped_column(String(1000), default="")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    s3_key: Mapped[str] = mapped_column(String(500))
    text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[PaperStatus] = mapped_column(
        SAEnum(PaperStatus, name="paper_status"), default=PaperStatus.uploaded
    )
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
