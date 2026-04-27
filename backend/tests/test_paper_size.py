from uuid import uuid4
from httpx import AsyncClient, ASGITransport
from app.main import app


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


async def test_upload_rejects_oversize(monkeypatch, s3_bucket, fernet_key, fresh_schema):
    monkeypatch.setenv("PAPER_MAX_BYTES", "1024")
    from app.config import get_settings
    get_settings.cache_clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed(c, h)
        big = b"%PDF-" + b"x" * 2048
        r = await c.post(
            "/papers", headers=h,
            files={"file":("p.pdf", big, "application/pdf")},
            data={"title":"big"},
        )
        assert r.status_code == 413


async def test_upload_rejects_non_pdf_magic(monkeypatch, s3_bucket, fernet_key, fresh_schema):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed(c, h)
        r = await c.post(
            "/papers", headers=h,
            files={"file":("p.pdf", b"NOTAPDF", "application/pdf")},
            data={"title":"fake"},
        )
        assert r.status_code == 415
        assert "PDF" in r.json()["detail"] or "pdf" in r.json()["detail"]
