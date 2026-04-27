from uuid import uuid4
import asyncio
import types
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, update

from app.main import app
from app.db import get_sessionmaker
from app.models import ReviewItem


def _pdf(t):
    import fitz
    d = fitz.open(); d.new_page().insert_text((72,72), t); b = d.tobytes(); d.close(); return b


async def _signup(c):
    email = f"u{uuid4()}@x.y"
    await c.post("/auth/signup", json={"email": email, "password": "supersecret1"})
    r = await c.post("/auth/login", json={"email": email, "password": "supersecret1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_with_paper(c, h, monkeypatch, content='{"concepts":[{"name":"Attention","summary":"x"}]}'):
    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, messages, stream=False):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content=content))])
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
        if rs: break
        await asyncio.sleep(0.1)
    return pid, rs


async def test_review_due_empty_when_no_sessions(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed_with_paper(c, h, monkeypatch)
        r = await c.get("/review/due", headers=h)
        assert r.status_code == 200
        assert r.json() == []


async def test_review_due_lists_items_past_due_at(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        pid, _ = await _seed_with_paper(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score":0.85}'))])
        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"paper_id":pid,"kind":"fresh"}, headers=h)).json()["id"]
        await c.post(f"/feynman/{sid}/end", headers=h)

        # Force the due_at into the past so it shows up in /due.
        async with get_sessionmaker()() as db:
            await db.execute(
                update(ReviewItem).values(due_at=datetime.now(timezone.utc) - timedelta(days=1))
            )
            await db.commit()

        r = await c.get("/review/due", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["concept_name"] == "Attention"
        assert "due_at" in body[0]
        assert "interval_days" in body[0]


async def test_review_due_skips_future_dues(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        pid, _ = await _seed_with_paper(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score":0.9}'))])
        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"paper_id":pid,"kind":"fresh"}, headers=h)).json()["id"]
        await c.post(f"/feynman/{sid}/end", headers=h)

        # due_at is now+1 day (default first pass) → not yet due.
        r = await c.get("/review/due", headers=h)
        assert r.json() == []


async def test_review_due_without_active_config_returns_empty(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    # Mirrors /dashboard's empty-state contract: no active config means
    # "nothing to review", not a 400.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        r = await c.get("/review/due", headers=h)
        assert r.status_code == 200
        assert r.json() == []


async def test_review_start_creates_scheduled_session(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        pid, _ = await _seed_with_paper(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score":0.85}'))])
        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"paper_id":pid,"kind":"fresh"}, headers=h)).json()["id"]
        await c.post(f"/feynman/{sid}/end", headers=h)
        async with get_sessionmaker()() as db:
            await db.execute(
                update(ReviewItem).values(due_at=datetime.now(timezone.utc) - timedelta(days=1))
            )
            await db.commit()

        items = (await c.get("/review/due", headers=h)).json()
        assert len(items) == 1
        item_id = items[0]["id"]
        target_cid = items[0]["concept_id"]

        r = await c.post("/review/start", json={"review_item_id": item_id}, headers=h)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["kind"] == "scheduled"
        assert body["target_concept_id"] == target_cid


async def test_review_start_rejects_unknown_id(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed_with_paper(c, h, monkeypatch)
        r = await c.post("/review/start", json={"review_item_id": str(uuid4())}, headers=h)
        assert r.status_code == 404


async def test_review_start_rejects_other_users_item(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h1 = await _signup(c)
        pid, _ = await _seed_with_paper(c, h1, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score":0.85}'))])
        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"paper_id":pid,"kind":"fresh"}, headers=h1)).json()["id"]
        await c.post(f"/feynman/{sid}/end", headers=h1)
        async with get_sessionmaker()() as db:
            ri = (await db.execute(select(ReviewItem))).scalar_one()
            iid = str(ri.id)

        h2 = await _signup(c)
        r = await c.post("/review/start", json={"review_item_id": iid}, headers=h2)
        assert r.status_code == 404
