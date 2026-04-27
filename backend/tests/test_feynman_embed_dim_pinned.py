from uuid import uuid4
import asyncio
import types

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.db import get_sessionmaker
from app.models import FeynmanSession


def _pdf(t):
    import fitz
    d = fitz.open(); d.new_page().insert_text((72,72), t); b = d.tobytes(); d.close(); return b


async def _signup(c):
    email = f"u{uuid4()}@x.y"
    await c.post("/auth/signup", json={"email": email, "password": "supersecret1"})
    r = await c.post("/auth/login", json={"email": email, "password": "supersecret1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_with_paper(c, h, monkeypatch, dim: int):
    class GW:
        async def embed(self, texts): return [[0.1]*dim for _ in texts]
        async def chat(self, messages, stream=False):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"x","summary":"s"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    await c.post("/llm-config", json={
        "name":"n","chat_base_url":"http://x/v1","chat_api_key":"sk","chat_model":"m",
        "embed_base_url":"http://x/v1","embed_api_key":"sk","embed_model":"em","embed_dim":dim,
    }, headers=h)
    cid = (await c.get("/llm-config", headers=h)).json()[0]["id"]
    await c.post(f"/llm-config/{cid}/activate", headers=h)
    await c.post("/papers", headers=h,
                 files={"file":("p.pdf", _pdf("hi"), "application/pdf")},
                 data={"title":"A"})
    for _ in range(50):
        rs = (await c.get("/concepts", headers=h)).json()
        if rs: break
        await asyncio.sleep(0.1)


async def test_session_pins_active_dim_at_start(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed_with_paper(c, h, monkeypatch, dim=1536)
        sid = (await c.post("/feynman/start", json={"kind":"fresh"}, headers=h)).json()["id"]

        from uuid import UUID
        maker = get_sessionmaker()
        async with maker() as db:
            row = (await db.execute(
                select(FeynmanSession).where(FeynmanSession.id == UUID(sid))
            )).scalar_one()
        assert row.embed_dim == 1536


def test_session_dim_column_not_null():
    cols = FeynmanSession.__table__.columns
    assert "embed_dim" in cols.keys()
    assert cols["embed_dim"].nullable is False
