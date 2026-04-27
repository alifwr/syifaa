from uuid import uuid4
import types

from httpx import AsyncClient, ASGITransport
from app.main import app


def _pdf(t):
    import fitz
    d = fitz.open(); d.new_page().insert_text((72,72), t); b = d.tobytes(); d.close(); return b


async def _signup(c):
    email = f"u{uuid4()}@x.y"
    await c.post("/auth/signup", json={"email": email, "password": "supersecret1"})
    r = await c.post("/auth/login", json={"email": email, "password": "supersecret1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_cfg(c, h, dim: int) -> str:
    await c.post("/llm-config", json={
        "name": f"d{dim}", "chat_base_url": "http://x/v1", "chat_api_key": "sk",
        "chat_model": "m", "embed_base_url": "http://x/v1", "embed_api_key": "sk",
        "embed_model": "em", "embed_dim": dim,
    }, headers=h)
    rs = (await c.get("/llm-config", headers=h)).json()
    return next(r["id"] for r in rs if r["embed_dim"] == dim)


async def test_activate_same_dim_after_data_exists_ok(monkeypatch, s3_bucket, fernet_key, fresh_schema):
    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, *a, **k):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"x","summary":"s"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        id1 = await _create_cfg(c, h, 1536)
        await c.post(f"/llm-config/{id1}/activate", headers=h)
        await c.post("/papers", headers=h,
                     files={"file":("p.pdf", _pdf("hi"), "application/pdf")},
                     data={"title": "t"})
        id2 = await _create_cfg(c, h, 1536)
        r = await c.post(f"/llm-config/{id2}/activate", headers=h)
        assert r.status_code == 200


async def test_activate_different_dim_after_data_exists_rejected(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, *a, **k):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"x","summary":"s"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        id1 = await _create_cfg(c, h, 1536)
        await c.post(f"/llm-config/{id1}/activate", headers=h)
        import asyncio
        for _ in range(50):
            rs = (await c.get("/concepts", headers=h)).json()
            if rs: break
            await asyncio.sleep(0.1)
        await c.post("/papers", headers=h,
                     files={"file":("p.pdf", _pdf("hi"), "application/pdf")},
                     data={"title":"t"})
        id2 = await _create_cfg(c, h, 768)
        r = await c.post(f"/llm-config/{id2}/activate", headers=h)
        assert r.status_code == 409
        assert "dim" in r.json()["detail"].lower()


async def test_activate_different_dim_with_no_data_ok(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        id1 = await _create_cfg(c, h, 1536)
        await c.post(f"/llm-config/{id1}/activate", headers=h)
        id2 = await _create_cfg(c, h, 768)
        r = await c.post(f"/llm-config/{id2}/activate", headers=h)
        assert r.status_code == 200
