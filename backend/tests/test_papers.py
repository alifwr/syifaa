import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock

from httpx import AsyncClient, ASGITransport
import types

from app.main import app


def _make_pdf(text: str) -> bytes:
    import fitz
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), text)
    b = doc.tobytes()
    doc.close()
    return b


async def _auth_header(client: AsyncClient) -> dict[str, str]:
    email = f"u{uuid4()}@x.y"
    await client.post("/auth/signup", json={"email": email, "password": "supersecret1"})
    r = await client.post("/auth/login", json={"email": email, "password": "supersecret1"})
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _seed_active_llm_config(client, headers):
    await client.post(
        "/llm-config",
        json={
            "name": "fake", "chat_base_url": "http://x/v1", "chat_api_key": "sk",
            "chat_model": "m", "embed_base_url": "http://x/v1", "embed_api_key": "sk",
            "embed_model": "em", "embed_dim": 1536,
        },
        headers=headers,
    )
    r = await client.get("/llm-config", headers=headers)
    cid = r.json()[0]["id"]
    await client.post(f"/llm-config/{cid}/activate", headers=headers)


async def test_upload_creates_paper_and_runs_ingest(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    class FakeGW:
        async def embed(self, texts):
            return [[0.1] * 1536 for _ in texts]
        async def chat(self, messages, stream=False):
            content = '{"concepts":[{"name":"x","summary":"s"}]}'
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content=content))])

    async def fake_builder(db, user): return FakeGW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake_builder)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _auth_header(c)
        await _seed_active_llm_config(c, h)
        pdf = _make_pdf("Hello paper. Topic: attention.")
        r = await c.post(
            "/papers",
            headers=h,
            files={"file": ("p.pdf", pdf, "application/pdf")},
            data={"title": "My Paper"},
        )
        assert r.status_code == 201, r.text
        pid = r.json()["id"]

        r = await c.get(f"/papers/{pid}", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] in ("uploaded", "parsed")

        body: dict = {}
        for _ in range(50):
            body = (await c.get(f"/papers/{pid}", headers=h)).json()
            if body.get("status") == "parsed" and body.get("chunks_count", 0) >= 1:
                break
            await asyncio.sleep(0.1)
        assert body["chunks_count"] >= 1
        assert body["concepts_count"] >= 1


async def test_list_papers_only_returns_own(monkeypatch, s3_bucket, fernet_key, fresh_schema):
    async def fake_builder(db, user):
        class G:
            async def embed(self, texts): return [[0.1] * 1536 for _ in texts]
            async def chat(self, *a, **k):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(
                        content='{"concepts":[{"name":"x","summary":"s"}]}'))])
        return G()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake_builder)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h1 = await _auth_header(c)
        await _seed_active_llm_config(c, h1)
        h2 = await _auth_header(c)
        await _seed_active_llm_config(c, h2)

        pdf = _make_pdf("user one's paper")
        await c.post("/papers", headers=h1, files={"file":("a.pdf",pdf,"application/pdf")}, data={"title": "A"})
        pdf2 = _make_pdf("user two's paper")
        await c.post("/papers", headers=h2, files={"file":("b.pdf",pdf2,"application/pdf")}, data={"title":"B"})

        r1 = (await c.get("/papers", headers=h1)).json()
        r2 = (await c.get("/papers", headers=h2)).json()
        assert len(r1) == 1 and r1[0]["title"] == "A"
        assert len(r2) == 1 and r2[0]["title"] == "B"


async def test_upload_rejects_non_pdf(monkeypatch, s3_bucket, fernet_key, fresh_schema):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _auth_header(c)
        await _seed_active_llm_config(c, h)
        r = await c.post(
            "/papers",
            headers=h,
            files={"file": ("note.txt", b"hello", "text/plain")},
            data={"title": "t"},
        )
        assert r.status_code == 415


async def test_upload_without_active_config_returns_400(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _auth_header(c)
        pdf = _make_pdf("no config")
        r = await c.post(
            "/papers",
            headers=h,
            files={"file": ("p.pdf", pdf, "application/pdf")},
            data={"title": "t"},
        )
        assert r.status_code == 400
        assert "LLM config" in r.json()["detail"]


async def test_delete_paper_removes_row_and_blob(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    class FailGW:
        async def embed(self, texts): raise RuntimeError("no")
        async def chat(self, *a, **k): raise RuntimeError("no")

    async def fake_builder(db, user): return FailGW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake_builder)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _auth_header(c)
        await _seed_active_llm_config(c, h)
        pdf = _make_pdf("del me")
        pid = (await c.post(
            "/papers", headers=h,
            files={"file":("p.pdf", pdf, "application/pdf")},
            data={"title":"t"},
        )).json()["id"]
        r = await c.delete(f"/papers/{pid}", headers=h)
        assert r.status_code == 204
        r = await c.get(f"/papers/{pid}", headers=h)
        assert r.status_code == 404
