from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, String, Integer, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class LLMConfig(Base):
    __tablename__ = "llm_config"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))

    chat_base_url: Mapped[str] = mapped_column(String(500))
    chat_api_key_enc: Mapped[str] = mapped_column(Text)
    chat_model: Mapped[str] = mapped_column(String(200))

    embed_base_url: Mapped[str] = mapped_column(String(500))
    embed_api_key_enc: Mapped[str] = mapped_column(Text)
    embed_model: Mapped[str] = mapped_column(String(200))
    embed_dim: Mapped[int] = mapped_column(Integer)

    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
