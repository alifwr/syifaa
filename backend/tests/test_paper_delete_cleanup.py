from uuid import uuid4
import asyncio
import types

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func

from app.main import app
from app.db import get_sessionmaker
from app.models import concept_model_for, ConceptEdge


def _pdf(t):
    import fitz
    d = fitz.open(); d.new_page().insert_text((72,72), t); b = d.tobytes(); d.close(); return b


async def _signup(c):
    email = f"u{uuid4()}@x.y"
    await c.post("/auth/signup", json={"email": email, "password": "supersecret1"})
    r = await c.post("/auth/login", json={"email": email, "password": "supersecret1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed(c, h):
    await c.post("/llm-config", json={
        "name":"n","chat_base_url":"http://x/v1","chat_api_key":"sk","chat_model":"m",
        "embed_base_url":"http://x/v1","embed_api_key":"sk","embed_model":"em","embed_dim":1536,
    }, headers=h)
    cid = (await c.get("/llm-config", headers=h)).json()[0]["id"]
    await c.post(f"/llm-config/{cid}/activate", headers=h)


async def test_delete_paper_drops_orphan_concepts_and_edges(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    class GW:
        async def embed(self, texts): return [[0.9]*1536 for _ in texts]
        async def chat(self, *a, **k):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"X","summary":"s"},{"name":"Y","summary":"s"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed(c, h)
        pid = (await c.post("/papers", headers=h,
                            files={"file":("p.pdf", _pdf("hi"), "application/pdf")},
                            data={"title":"A"})).json()["id"]
        for _ in range(50):
            rs = (await c.get("/concepts", headers=h)).json()
            if len(rs) == 2: break
            await asyncio.sleep(0.1)

        ConceptM = concept_model_for(1536)
        async with get_sessionmaker()() as db:
            n_concepts_before = (await db.execute(select(func.count()).select_from(ConceptM))).scalar()
            n_edges_before = (await db.execute(select(func.count()).select_from(ConceptEdge))).scalar()
        assert n_concepts_before == 2 and n_edges_before >= 1

        await c.delete(f"/papers/{pid}", headers=h)

        async with get_sessionmaker()() as db:
            n_concepts_after = (await db.execute(select(func.count()).select_from(ConceptM))).scalar()
            n_edges_after = (await db.execute(select(func.count()).select_from(ConceptEdge))).scalar()
        assert n_concepts_after == 0
        assert n_edges_after == 0


async def test_delete_paper_keeps_concepts_with_other_sources(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, *a, **k):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"Shared","summary":"s"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed(c, h)
        p1 = (await c.post("/papers", headers=h,
                           files={"file":("a.pdf", _pdf("a"), "application/pdf")},
                           data={"title":"A"})).json()["id"]
        for _ in range(40):
            rs = (await c.get("/concepts", headers=h)).json()
            if rs: break
            await asyncio.sleep(0.1)
        await c.post("/papers", headers=h,
                     files={"file":("b.pdf", _pdf("b"), "application/pdf")},
                     data={"title":"B"})
        await asyncio.sleep(1.5)

        await c.delete(f"/papers/{p1}", headers=h)

        rs = (await c.get("/concepts", headers=h)).json()
        assert len(rs) == 1
