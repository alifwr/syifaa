from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class _PaperChunkBase:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE"), index=True
    )
    ord: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer)


def _make_chunk_model(dim: int) -> type:
    name = f"PaperChunk{dim}"
    return type(
        name,
        (_PaperChunkBase, Base),
        {
            "__tablename__": f"paper_chunk_{dim}",
            "embedding": mapped_column(Vector(dim)),
        },
    )


PaperChunk768 = _make_chunk_model(768)
PaperChunk1024 = _make_chunk_model(1024)
PaperChunk1536 = _make_chunk_model(1536)

_CHUNK_MODELS = {768: PaperChunk768, 1024: PaperChunk1024, 1536: PaperChunk1536}


def chunk_model_for(dim: int):
    try:
        return _CHUNK_MODELS[dim]
    except KeyError:
        raise ValueError(f"unsupported embed_dim {dim}; pick one of {sorted(_CHUNK_MODELS)}")
