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


async def _seed_with_paper(c, h, monkeypatch):
    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, messages, stream=False):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"Attention","summary":"x"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    await c.post("/llm-config", json={
        "name":"n","chat_base_url":"http://x/v1","chat_api_key":"sk","chat_model":"m",
        "embed_base_url":"http://x/v1","embed_api_key":"sk","embed_model":"em","embed_dim":1536,
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


async def test_persisted_assistant_turn_visible_after_stream(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed_with_paper(c, h, monkeypatch)

        class FakeStream:
            def __init__(self, deltas): self._d = deltas
            def __aiter__(self): return self._iter()
            async def _iter(self):
                for d in self._d:
                    yield type("Chunk", (), {
                        "choices": [type("C", (), {
                            "delta": type("D", (), {"content": d}),
                            "finish_reason": None,
                        })],
                    })
                yield type("Chunk", (), {
                    "choices": [type("C", (), {
                        "delta": type("D", (), {"content": None}),
                        "finish_reason": "stop",
                    })],
                })

        class GW:
            async def chat(self, messages, stream=False):
                if stream: return FakeStream(["Why?"])
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score":0.5}'))])

        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"kind":"fresh"}, headers=h)).json()["id"]
        async with c.stream(
            "POST", f"/feynman/{sid}/message",
            headers=h, json={"content": "explanation"},
        ) as r:
            async for _ in r.aiter_lines():
                pass

        from uuid import UUID
        maker = get_sessionmaker()
        async with maker() as db:
            row = (await db.execute(
                select(FeynmanSession).where(FeynmanSession.id == UUID(sid))
            )).scalar_one()
        roles = [t["role"] for t in row.transcript]
        assert "user" in roles
        assert "assistant" in roles
        last = row.transcript[-1]
        assert last["role"] == "assistant" and "Why?" in last["content"]
