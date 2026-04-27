from uuid import uuid4
import asyncio
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


async def _seed(c, h, monkeypatch):
    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, messages, stream=False):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"X","summary":"s"},{"name":"Y","summary":"s"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    await c.post("/llm-config", json={
        "name":"n","chat_base_url":"http://x/v1","chat_api_key":"sk","chat_model":"m",
        "embed_base_url":"http://x/v1","embed_api_key":"sk","embed_model":"em","embed_dim":1536,
    }, headers=h)
    cid = (await c.get("/llm-config", headers=h)).json()[0]["id"]
    await c.post(f"/llm-config/{cid}/activate", headers=h)
    pid = (await c.post("/papers", headers=h,
                        files={"file":("p.pdf", _pdf("hi"), "application/pdf")},
                        data={"title":"A"})).json()["id"]
    for _ in range(50):
        rs = (await c.get("/concepts", headers=h)).json()
        if len(rs) == 2: break
        await asyncio.sleep(0.1)
    return pid


async def test_dashboard_empty_state(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        r = await c.get("/dashboard", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["concept_count"] == 0
        assert body["sessions"] == []


async def test_dashboard_counts_concepts_and_sessions(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        pid = await _seed(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score":0.8}'))])
        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        for _ in range(2):
            sid = (await c.post("/feynman/start", json={"paper_id":pid,"kind":"fresh"}, headers=h)).json()["id"]
            await c.post(f"/feynman/{sid}/end", headers=h)

        r = await c.get("/dashboard", headers=h)
        body = r.json()
        assert body["concept_count"] == 2
        assert len(body["sessions"]) == 2
        assert all("started_at" in s and "quality_score" in s for s in body["sessions"])
        # newest first
        assert body["sessions"][0]["started_at"] >= body["sessions"][1]["started_at"]


async def test_dashboard_excludes_unended_sessions(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        pid = await _seed(c, h, monkeypatch)
        await c.post("/feynman/start", json={"paper_id":pid,"kind":"fresh"}, headers=h)
        r = await c.get("/dashboard", headers=h)
        assert r.json()["sessions"] == []
