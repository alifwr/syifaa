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


async def _seed_with_paper(c, h, monkeypatch):
    class GW:
        async def embed(self, texts): return [[0.1]*1536 for _ in texts]
        async def chat(self, messages, stream=False):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"Attention","summary":"focus mech"}]}'))])
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
    return pid, rs[0]


async def test_start_session_picks_concept_and_seeds_transcript(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        pid, concept = await _seed_with_paper(c, h, monkeypatch)
        r = await c.post(
            "/feynman/start",
            json={"paper_id": pid, "kind": "fresh"},
            headers=h,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["target_concept_id"] == concept["id"]
        assert body["kind"] == "fresh"
        assert body["paper_id"] == pid
        # System turn is server-side only; not exposed via API.
        assert all(t["role"] != "system" for t in body["transcript"])


async def test_start_session_without_paper_picks_any_concept(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed_with_paper(c, h, monkeypatch)
        r = await c.post(
            "/feynman/start",
            json={"paper_id": None, "kind": "scheduled"},
            headers=h,
        )
        assert r.status_code == 201
        assert r.json()["paper_id"] is None
        assert r.json()["kind"] == "scheduled"


async def test_start_without_concepts_returns_400(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await c.post("/llm-config", json={
            "name":"n","chat_base_url":"http://x/v1","chat_api_key":"sk","chat_model":"m",
            "embed_base_url":"http://x/v1","embed_api_key":"sk","embed_model":"em","embed_dim":1536,
        }, headers=h)
        cid = (await c.get("/llm-config", headers=h)).json()[0]["id"]
        await c.post(f"/llm-config/{cid}/activate", headers=h)
        r = await c.post("/feynman/start", json={"kind":"fresh"}, headers=h)
        assert r.status_code == 400


async def test_get_session_only_visible_to_owner(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h1 = await _signup(c)
        await _seed_with_paper(c, h1, monkeypatch)
        sid = (await c.post("/feynman/start", json={"kind":"fresh"}, headers=h1)).json()["id"]

        h2 = await _signup(c)
        r = await c.get(f"/feynman/{sid}", headers=h2)
        assert r.status_code == 404
        r = await c.get(f"/feynman/{sid}", headers=h1)
        assert r.status_code == 200


async def test_message_streams_and_persists(
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
                if stream:
                    return FakeStream(["Why ", "self-attention", "?"])
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score":0.5}'))])

        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"kind":"fresh"}, headers=h)).json()["id"]

        async with c.stream(
            "POST",
            f"/feynman/{sid}/message",
            headers=h,
            json={"content": "Self-attention is when..."},
        ) as r:
            assert r.status_code == 200
            collected: list[str] = []
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    collected.append(line[6:])
        full_reply = "".join(c for c in collected if c and c != "[DONE]")
        assert "Why" in full_reply

        body = (await c.get(f"/feynman/{sid}", headers=h)).json()
        roles = [t["role"] for t in body["transcript"]]
        assert "user" in roles
        assert "assistant" in roles
        last = body["transcript"][-1]
        assert last["role"] == "assistant" and "Why" in last["content"]


async def test_message_session_not_owned_returns_404(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h1 = await _signup(c)
        await _seed_with_paper(c, h1, monkeypatch)
        sid = (await c.post("/feynman/start", json={"kind":"fresh"}, headers=h1)).json()["id"]
        h2 = await _signup(c)
        r = await c.post(f"/feynman/{sid}/message", json={"content":"x"}, headers=h2)
        assert r.status_code == 404


async def test_end_session_grades_and_sets_score(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed_with_paper(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                if stream:
                    raise AssertionError("end should not stream")
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score": 0.62}'))])

        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"kind":"fresh"}, headers=h)).json()["id"]
        r = await c.post(f"/feynman/{sid}/end", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert abs(body["quality_score"] - 0.62) < 1e-9

        detail = (await c.get(f"/feynman/{sid}", headers=h)).json()
        assert detail["ended_at"] is not None
        assert detail["quality_score"] is not None


async def test_end_session_idempotent_returns_existing(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed_with_paper(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score": 0.4}'))])

        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"kind":"fresh"}, headers=h)).json()["id"]
        r1 = await c.post(f"/feynman/{sid}/end", headers=h)
        s1 = r1.json()["quality_score"]
        r2 = await c.post(f"/feynman/{sid}/end", headers=h)
        assert r2.status_code == 200
        assert r2.json()["quality_score"] == s1


async def test_end_upserts_review_item(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        pid, concept = await _seed_with_paper(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score": 0.85}'))])

        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"paper_id": pid, "kind":"fresh"}, headers=h)).json()["id"]
        await c.post(f"/feynman/{sid}/end", headers=h)

        from uuid import UUID
        from sqlalchemy import select
        from app.db import get_sessionmaker
        from app.models import ReviewItem
        async with get_sessionmaker()() as db:
            ri = (await db.execute(
                select(ReviewItem).where(ReviewItem.concept_id == UUID(concept["id"]))
            )).scalar_one()
        assert ri.embed_dim == 1536
        assert ri.last_score is not None
        assert abs(float(ri.last_score) - 0.85) < 1e-9
        assert ri.interval_days == 1  # first pass
        assert ri.last_session_id == UUID(sid)


async def test_end_second_pass_extends_interval(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        pid, concept = await _seed_with_paper(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score": 1.0}'))])

        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid1 = (await c.post("/feynman/start", json={"paper_id": pid, "kind":"fresh"}, headers=h)).json()["id"]
        await c.post(f"/feynman/{sid1}/end", headers=h)
        sid2 = (await c.post("/feynman/start", json={"paper_id": pid, "kind":"scheduled"}, headers=h)).json()["id"]
        await c.post(f"/feynman/{sid2}/end", headers=h)

        from uuid import UUID
        from sqlalchemy import select, func
        from app.db import get_sessionmaker
        from app.models import ReviewItem
        async with get_sessionmaker()() as db:
            n = (await db.execute(
                select(func.count()).select_from(ReviewItem)
                .where(ReviewItem.concept_id == UUID(concept["id"]))
            )).scalar()
            ri = (await db.execute(
                select(ReviewItem).where(ReviewItem.concept_id == UUID(concept["id"]))
            )).scalar_one()
        assert n == 1, "second end must update existing review_item, not insert"
        assert ri.interval_days == 6  # 1 → 6 on the second pass
        assert ri.last_session_id == UUID(sid2)


async def test_double_end_does_not_compound_sm2(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    """Calling /end twice on the same session must NOT run SM-2 twice.
    Idempotency guard short-circuits before SM-2 fires."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        pid, concept = await _seed_with_paper(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score": 1.0}'))])

        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"paper_id": pid, "kind":"fresh"}, headers=h)).json()["id"]
        await c.post(f"/feynman/{sid}/end", headers=h)
        # Second end must not compound: interval should stay at 1 (first pass),
        # not advance to 6 (which would happen if SM-2 ran a second time).
        await c.post(f"/feynman/{sid}/end", headers=h)

        from uuid import UUID
        from sqlalchemy import select
        from app.db import get_sessionmaker
        from app.models import ReviewItem
        async with get_sessionmaker()() as db:
            ri = (await db.execute(
                select(ReviewItem).where(ReviewItem.concept_id == UUID(concept["id"]))
            )).scalar_one()
        assert ri.interval_days == 1, (
            f"SM-2 must not run twice on a re-ended session "
            f"(interval={ri.interval_days}; would be 6 if compounded)"
        )
