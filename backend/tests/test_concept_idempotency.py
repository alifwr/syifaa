from uuid import uuid4
import types
import asyncio

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func

from app.main import app
from app.db import get_sessionmaker
from app.models import concept_model_for, ConceptEdge


def _pdf(t):
    import fitz
    d = fitz.open(); d.new_page().insert_text((72,72), t); b = d.tobytes(); d.close(); return b


async def _signup_login(c):
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


async def _wait(c, h, n: int):
    for _ in range(80):
        rs = (await c.get("/concepts", headers=h)).json()
        if len(rs) >= n: return rs
        await asyncio.sleep(0.1)
    return rs


async def test_reingest_does_not_duplicate_concepts(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, *a, **k):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"Attention","summary":"s"},{"name":"Transformer","summary":"s"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup_login(c)
        await _seed(c, h)
        pid = (await c.post("/papers", headers=h,
                            files={"file":("p.pdf", _pdf("hi"), "application/pdf")},
                            data={"title":"A"})).json()["id"]
        rs = await _wait(c, h, 2)
        assert {r["name"] for r in rs} == {"Attention", "Transformer"}

        await c.post(f"/papers/{pid}/reingest", headers=h)
        for _ in range(80):
            r = (await c.get(f"/papers/{pid}", headers=h)).json()
            if r["status"] == "parsed": break
            await asyncio.sleep(0.1)

        ConceptM = concept_model_for(1536)
        async with get_sessionmaker()() as db:
            n = (await db.execute(select(func.count()).select_from(ConceptM))).scalar()
        assert n == 2


async def test_concept_match_is_case_insensitive(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    calls = {"n": 0}

    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, *a, **k):
            calls["n"] += 1
            payloads = [
                '{"concepts":[{"name":"Attention","summary":"s"}]}',
                '{"concepts":[{"name":"attention","summary":"s"}]}',
            ]
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content=payloads[(calls["n"] - 1) % len(payloads)]))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup_login(c)
        await _seed(c, h)
        await c.post("/papers", headers=h,
                     files={"file":("p1.pdf", _pdf("a"), "application/pdf")},
                     data={"title":"A"})
        await _wait(c, h, 1)
        await c.post("/papers", headers=h,
                     files={"file":("p2.pdf", _pdf("b"), "application/pdf")},
                     data={"title":"B"})
        await asyncio.sleep(2)
        rs = (await c.get("/concepts", headers=h)).json()
        assert len(rs) == 1


async def test_reingest_appends_paper_id_to_source_list(
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
        h = await _signup_login(c)
        await _seed(c, h)
        p1 = (await c.post("/papers", headers=h,
                           files={"file":("a.pdf", _pdf("a"), "application/pdf")},
                           data={"title":"A"})).json()["id"]
        await _wait(c, h, 1)
        p2 = (await c.post("/papers", headers=h,
                           files={"file":("b.pdf", _pdf("b"), "application/pdf")},
                           data={"title":"B"})).json()["id"]
        await asyncio.sleep(2)

        ConceptM = concept_model_for(1536)
        async with get_sessionmaker()() as db:
            row = (await db.execute(select(ConceptM))).scalar_one()
        ids = {str(x) for x in row.source_paper_ids}
        assert {p1, p2} <= ids
