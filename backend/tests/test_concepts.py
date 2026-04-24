from uuid import uuid4
import types

from httpx import AsyncClient, ASGITransport
from app.main import app


def _pdf(t):
    import fitz
    d = fitz.open(); d.new_page().insert_text((72,72), t); b = d.tobytes(); d.close(); return b


async def _signup_login(c):
    email = f"u{uuid4()}@x.y"
    await c.post("/auth/signup", json={"email": email, "password": "supersecret1"})
    r = await c.post("/auth/login", json={"email": email, "password": "supersecret1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _active_cfg(c, h):
    await c.post("/llm-config", json={
        "name":"n","chat_base_url":"http://x/v1","chat_api_key":"sk","chat_model":"m",
        "embed_base_url":"http://x/v1","embed_api_key":"sk","embed_model":"em","embed_dim":1536,
    }, headers=h)
    cid = (await c.get("/llm-config", headers=h)).json()[0]["id"]
    await c.post(f"/llm-config/{cid}/activate", headers=h)


async def test_list_concepts_empty(monkeypatch, s3_bucket, fernet_key, fresh_schema):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup_login(c)
        await _active_cfg(c, h)
        r = await c.get("/concepts", headers=h)
        assert r.status_code == 200
        assert r.json() == []


async def test_list_concepts_returns_own_only(monkeypatch, s3_bucket, fernet_key, fresh_schema):
    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, *a, **k):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"alpha","summary":"s"},{"name":"beta","summary":"s"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup_login(c)
        await _active_cfg(c, h)
        pdf = _pdf("hi paper")
        await c.post("/papers", headers=h,
                     files={"file":("p.pdf",pdf,"application/pdf")}, data={"title":"A"})
        import asyncio
        # Wait for background ingest.
        rs: list = []
        for _ in range(50):
            rs = (await c.get("/concepts", headers=h)).json()
            if rs:
                break
            await asyncio.sleep(0.1)
        assert {c["name"] for c in rs} == {"alpha", "beta"}


async def test_list_concepts_without_active_config_returns_400(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup_login(c)
        r = await c.get("/concepts", headers=h)
        assert r.status_code == 400
