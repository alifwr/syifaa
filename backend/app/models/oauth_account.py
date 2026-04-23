from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, String, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class OAuthAccount(Base):
    __tablename__ = "oauth_account"
    __table_args__ = (UniqueConstraint("provider", "provider_sub"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_sub: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
