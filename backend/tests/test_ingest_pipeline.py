from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.db import get_sessionmaker
from app.models import (
    User, LLMConfig, Paper, PaperStatus,
    chunk_model_for, concept_model_for, ConceptEdge,
)
from app.security import encrypt_secret
from app.services.ingest import ingest_paper


def _make_pdf(text: str) -> bytes:
    import fitz
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), text)
    b = doc.tobytes()
    doc.close()
    return b


async def _seed_user_cfg(db) -> tuple[User, LLMConfig]:
    u = User(email=f"{uuid4()}@x.y", pw_hash="h")
    db.add(u)
    await db.commit()
    c = LLMConfig(
        user_id=u.id, name="n",
        chat_base_url="http://x/v1", chat_api_key_enc=encrypt_secret("sk"),
        chat_model="m",
        embed_base_url="http://x/v1", embed_api_key_enc=encrypt_secret("sk"),
        embed_model="em", embed_dim=1536, is_active=True,
    )
    db.add(c)
    await db.commit()
    return u, c


async def test_ingest_happy_path_writes_chunks_concepts_and_edges(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    from app.services.storage import Storage
    storage = Storage()
    key = f"papers/{uuid4()}.pdf"
    await storage.put_object(
        key, _make_pdf("Attention is all you need. Transformer self-attention layers."),
    )

    maker = get_sessionmaker()
    async with maker() as db:
        u, _ = await _seed_user_cfg(db)
        paper = Paper(user_id=u.id, title="t", s3_key=key)
        db.add(paper)
        await db.commit()
        pid = paper.id

    # Mock LLMGateway.
    fake_chunk_vec = [0.01] * 1536
    fake_concept_vecs = [[0.9] + [0.0] * 1535, [0.89] + [0.0] * 1535]

    class FakeGW:
        def __init__(self):
            self.embed_calls = 0

        async def embed(self, texts):
            self.embed_calls += 1
            if self.embed_calls == 1:
                return [fake_chunk_vec] * len(texts)
            return fake_concept_vecs[: len(texts)]

        async def chat(self, messages, stream=False):
            import types
            content = '{"concepts":[{"name":"attention","summary":"x"},{"name":"transformer","summary":"y"}]}'
            choice = types.SimpleNamespace(message=types.SimpleNamespace(content=content))
            return types.SimpleNamespace(choices=[choice])

    fake_gw = FakeGW()

    async with maker() as db:
        await ingest_paper(
            paper_id=pid, db=db, gateway=fake_gw, storage=storage, embed_dim=1536,
        )

    ChunkM = chunk_model_for(1536)
    ConceptM = concept_model_for(1536)
    async with maker() as db:
        n_chunks = (await db.execute(select(func.count()).select_from(ChunkM))).scalar()
        n_concepts = (await db.execute(select(func.count()).select_from(ConceptM))).scalar()
        n_edges = (await db.execute(select(func.count()).select_from(ConceptEdge))).scalar()
        p = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
    assert n_chunks >= 1
    assert n_concepts == 2
    # Two concepts with near-parallel vectors → at least 1 edge between them.
    assert n_edges >= 1
    assert p.status == PaperStatus.parsed


async def test_ingest_marks_failed_on_extraction_error(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    from app.services.storage import Storage
    storage = Storage()
    key = f"papers/{uuid4()}.pdf"
    await storage.put_object(key, b"this is not a pdf")
    maker = get_sessionmaker()
    async with maker() as db:
        u, _ = await _seed_user_cfg(db)
        paper = Paper(user_id=u.id, title="t", s3_key=key)
        db.add(paper)
        await db.commit()
        pid = paper.id

    class FakeGW:
        async def embed(self, texts): return []
        async def chat(self, *a, **k): return None

    async with maker() as db:
        await ingest_paper(
            paper_id=pid, db=db, gateway=FakeGW(), storage=storage, embed_dim=1536,
        )

    async with maker() as db:
        p = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
    assert p.status == PaperStatus.failed
    assert p.parse_error is not None
