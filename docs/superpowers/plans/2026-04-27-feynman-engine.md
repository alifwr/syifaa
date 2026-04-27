# Feynman Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Feynman teach-back chat loop end-to-end (start session → SSE-streamed chat → end + AI grading) on top of stabilised Plan 2 foundations.

**Architecture:** A new `feynman_session` table records `(user_id, paper_id?, target_concept_id, kind, transcript jsonb, quality_score?, started_at, ended_at?)`. The `/feynman` router exposes start/message/end/get endpoints. The message endpoint streams the model reply via SSE (`text/event-stream`); the frontend consumes the stream with `fetch` + `ReadableStream` so it can send the bearer token (EventSource can't). Grading is a separate non-streaming LLM call on session end. Folds in load-bearing carries from Plan 2's final review: `embed_dim` tightening, dim-immutability check, concept idempotency on reingest, paper-delete cleanup, paper size cap, cookie_secure setting, and `chunks_count`/`concepts_count` exposure.

**Tech Stack:** FastAPI + StreamingResponse + SSE, SQLAlchemy 2.x async, pgvector, OpenAI Python SDK streaming, Nuxt 4 with `fetch` ReadableStream consumption, Playwright.

**Out of scope (deferred to Plan 4):** SM-2 scheduler, `review_item` table, `/review/due`, `/dashboard`, `/review` and `/dashboard` pages.

---

## File Structure

**Backend (new):**
- `backend/app/models/feynman_session.py` — `FeynmanSession` ORM + `FeynmanKind` enum (`fresh|scheduled`).
- `backend/app/services/feynman.py` — pure-ish helpers: `pick_target_concept(paper_id|None, user)`, `build_system_prompt(concept)`, `grade_transcript(gateway, transcript) -> float`. No DB writes inside helpers — orchestration stays in the router.
- `backend/app/services/sse.py` — `sse_event(data: dict|str) -> bytes` formatter; `stream_chat(gateway, messages)` yields chunks as bytes.
- `backend/app/schemas/feynman.py` — `FeynmanStartIn`, `FeynmanMessageIn`, `FeynmanSessionOut`, `FeynmanGradeOut`.
- `backend/app/routers/feynman.py` — `POST /feynman/start`, `GET /feynman/{sid}`, `POST /feynman/{sid}/message`, `POST /feynman/{sid}/end`.
- `backend/alembic/versions/<rev>_feynman_session.py`.
- `backend/tests/test_feynman.py`, `test_sse.py`, `test_paper_size.py`, `test_concept_idempotency.py`, `test_paper_delete_cleanup.py`, `test_dim_immutability.py`, `test_embed_dim_literal.py`.

**Backend (modify):**
- `backend/app/config.py` — add `paper_max_bytes: int = 50_000_000`, `cookie_secure: bool = False`.
- `backend/app/schemas/llm_config.py` — `embed_dim: Literal[768, 1024, 1536]`.
- `backend/app/routers/llm_config.py` — at activate, reject if user has chunks/concepts in a different dim.
- `backend/app/routers/papers.py` — size cap + magic-byte sniff at upload; DELETE prunes concepts/edges; PaperOut now includes counts.
- `backend/app/services/ingest.py` — concept idempotency: match `(user_id, lower(name))` and merge `source_paper_ids` instead of inserting duplicates.
- `backend/app/schemas/paper.py` — `chunks_count: int`, `concepts_count: int`.
- `backend/app/routers/oauth.py` — read `cookie_secure` from settings.
- `backend/app/main.py` — include feynman router.

**Frontend (new):**
- `frontend/app/pages/feynman/[sid].vue` — chat UI (transcript list, input, end button, SSE consumer).
- `frontend/app/composables/useStream.ts` — wrapper around `fetch` + `ReadableStream` returning an async iterator of SSE chunks.
- `frontend/tests/e2e/feynman.spec.ts`.

**Frontend (modify):**
- `frontend/app/pages/papers/[id].vue` — add "Teach me back" button when `status==parsed && concepts_count > 0`; clicks `POST /feynman/start {paper_id, kind:"fresh"}` and navigates to `/feynman/<sid>`.

---

## Task 1: Tighten `embed_dim` to a Literal

**Files:**
- Modify: `backend/app/schemas/llm_config.py`
- Test: `backend/tests/test_embed_dim_literal.py`

**Context:** Plan 2 reviewer Important #4. `embed_dim` schema accepts any int 1..8192, but only 768/1024/1536 have backing tables. Reject at the schema layer instead of failing opaquely at ingest.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_embed_dim_literal.py`:

```python
import pytest
from pydantic import ValidationError
from app.schemas.llm_config import LLMConfigIn


def _payload(dim: int) -> dict:
    return {
        "name": "n", "chat_base_url": "http://x/v1", "chat_api_key": "sk",
        "chat_model": "m", "embed_base_url": "http://x/v1", "embed_api_key": "sk",
        "embed_model": "em", "embed_dim": dim,
    }


def test_embed_dim_768_accepted():
    LLMConfigIn(**_payload(768))


def test_embed_dim_1024_accepted():
    LLMConfigIn(**_payload(1024))


def test_embed_dim_1536_accepted():
    LLMConfigIn(**_payload(1536))


@pytest.mark.parametrize("bad", [512, 2048, 0, 1])
def test_embed_dim_unsupported_rejected(bad: int):
    with pytest.raises(ValidationError):
        LLMConfigIn(**_payload(bad))
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_embed_dim_literal.py -v
```

Expected: parametrized test fails (currently 512 etc. accepted).

- [ ] **Step 3: Implement**

Edit `backend/app/schemas/llm_config.py`. Replace the `embed_dim: int = Field(ge=1, le=8192)` line with:

```python
from typing import Literal

# ...
class LLMConfigIn(BaseModel):
    # ...
    embed_dim: Literal[768, 1024, 1536]
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/llm_config.py backend/tests/test_embed_dim_literal.py
git commit -m "feat(api): restrict embed_dim to Literal[768, 1024, 1536]"
```

---

## Task 2: Dim-immutability check at `/llm-config/{id}/activate`

**Files:**
- Modify: `backend/app/routers/llm_config.py`
- Test: `backend/tests/test_dim_immutability.py`

**Context:** Plan 2 reviewer Important #3. Switching `embed_dim` mid-life strands chunks/concepts in the old dim's tables. Simplest enforcement: at activate, if the user already has any data in a different dim, reject with 409.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_dim_immutability.py`:

```python
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
        # ingest one paper to populate concept_1536
        await c.post("/papers", headers=h,
                     files={"file":("p.pdf", _pdf("hi"), "application/pdf")},
                     data={"title": "t"})
        # add a SECOND 1536 config — activating must still work
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
        # wait for ingest
        import asyncio
        for _ in range(50):
            rs = (await c.get("/concepts", headers=h)).json()
            if rs: break
            await asyncio.sleep(0.1)
        await c.post("/papers", headers=h,
                     files={"file":("p.pdf", _pdf("hi"), "application/pdf")},
                     data={"title":"t"})
        # add a 768 config and try to activate
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
        # no papers uploaded yet — switching dim is allowed
        id2 = await _create_cfg(c, h, 768)
        r = await c.post(f"/llm-config/{id2}/activate", headers=h)
        assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_dim_immutability.py -v
```

Expected: middle test fails (currently switch is allowed silently).

- [ ] **Step 3: Implement**

Edit `backend/app/routers/llm_config.py` `activate` handler. Before the `is_active=False` clear, add:

```python
from sqlalchemy import func
from app.models import (
    PaperChunk768, PaperChunk1024, PaperChunk1536,
    Concept768, Concept1024, Concept1536, Paper,
)

_DIM_TABLES = {
    768: (PaperChunk768, Concept768),
    1024: (PaperChunk1024, Concept1024),
    1536: (PaperChunk1536, Concept1536),
}


async def _user_has_data_in_other_dim(db, user_id, target_dim: int) -> bool:
    for d, (CM, KM) in _DIM_TABLES.items():
        if d == target_dim:
            continue
        # Concepts are scoped by user_id directly. Chunks scope via Paper.
        n_concepts = (
            await db.execute(
                select(func.count()).select_from(KM).where(KM.user_id == user_id)
            )
        ).scalar()
        if n_concepts:
            return True
        n_chunks = (
            await db.execute(
                select(func.count()).select_from(CM)
                .join(Paper, Paper.id == CM.paper_id)
                .where(Paper.user_id == user_id)
            )
        ).scalar()
        if n_chunks:
            return True
    return False
```

In `activate(...)` after the `target = ...` lookup and 404 guard, add:

```python
    if await _user_has_data_in_other_dim(db, user.id, target.embed_dim):
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot switch embed_dim: existing chunks/concepts use a "
                "different dim. Delete existing papers first."
            ),
        )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_dim_immutability.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/llm_config.py backend/tests/test_dim_immutability.py
git commit -m "feat(llm-config): block activating different embed_dim while data exists"
```

---

## Task 3: Concept idempotency on reingest

**Files:**
- Modify: `backend/app/services/ingest.py`
- Test: `backend/tests/test_concept_idempotency.py`

**Context:** Plan 2 reviewer Important #1. Today, reingesting a paper inserts duplicate concept rows for each name. Match on `(user_id, lower(name))`; if found, append the paper id to `source_paper_ids` (without duplication) and reuse the row for edge proposals.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_concept_idempotency.py`:

```python
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

        # Reingest
        await c.post(f"/papers/{pid}/reingest", headers=h)
        # Wait for second ingest to settle (status flips back to parsed)
        for _ in range(80):
            r = (await c.get(f"/papers/{pid}", headers=h)).json()
            if r["status"] == "parsed": break
            await asyncio.sleep(0.1)

        # Still exactly two concepts.
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
                message=types.SimpleNamespace(content=payloads[calls["n"] % len(payloads) - 1]))])
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
        # second paper extracts "attention" (lowercase) — should match existing
        await asyncio.sleep(2)  # crude wait
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_concept_idempotency.py -v
```

Expected: first test fails (4 rows after reingest, not 2).

- [ ] **Step 3: Implement**

Edit `backend/app/services/ingest.py`. Replace the concept-insert block (the `for rec, vec in zip(...)` loop) with:

```python
            from sqlalchemy import func as sa_func
            ConceptM = concept_model_for(embed_dim)
            existing_rows = (
                await db.execute(
                    select(ConceptM).where(ConceptM.user_id == paper.user_id)
                )
            ).scalars().all()
            by_lname = {r.name.lower(): r for r in existing_rows}

            new_concepts: list = []
            touched: list = []
            for rec, vec in zip(concept_records, concept_embeds):
                lname = rec["name"].strip().lower()
                if not lname:
                    continue
                hit = by_lname.get(lname)
                if hit is not None:
                    if paper.id not in (hit.source_paper_ids or []):
                        # SQLAlchemy ARRAY mutation — reassign so dirty-tracking fires.
                        hit.source_paper_ids = list(hit.source_paper_ids or []) + [paper.id]
                    touched.append(hit)
                    continue
                obj = ConceptM(
                    user_id=paper.user_id,
                    name=rec["name"][:500],
                    summary=rec.get("summary", "")[:2000],
                    source_paper_ids=[paper.id],
                    embedding=vec,
                )
                db.add(obj)
                new_concepts.append(obj)
                by_lname[lname] = obj
            await db.flush()

            await _propose_edges(
                db, ConceptM, new_concepts + touched, user_id=paper.user_id,
                top_k=settings.concept_edge_top_k,
                min_cos=settings.concept_edge_min_cosine,
            )
```

(Note: pass both `new_concepts` and `touched` to `_propose_edges` so cross-paper concept relationships also get proposed when an old concept gets reinforced by a new paper.)

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_concept_idempotency.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ingest.py backend/tests/test_concept_idempotency.py
git commit -m "feat(ingest): match concepts case-insensitively and merge source_paper_ids"
```

---

## Task 4: `DELETE /papers/{id}` cleans up concepts and edges

**Files:**
- Modify: `backend/app/routers/papers.py`
- Test: `backend/tests/test_paper_delete_cleanup.py`

**Context:** Plan 2 reviewer Important #2. Currently DELETE drops the paper + chunks (FK cascade) but leaves concept rows referencing the deleted paper id in `source_paper_ids`, plus orphan `concept_edge` rows.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_paper_delete_cleanup.py`:

```python
from uuid import uuid4
import asyncio
import types

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func

from app.main import app
from app.db import get_sessionmaker
from app.models import concept_model_for, ConceptEdge


def _pdf(t):
    import fitz
    d = fitz.open(); d.new_page().insert_text((72,72), t); b = d.tobytes(); d.close(); return b


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


async def test_delete_paper_drops_orphan_concepts_and_edges(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    class GW:
        async def embed(self, texts): return [[0.9]*1536 for _ in texts]  # all near-parallel → edges
        async def chat(self, *a, **k):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"concepts":[{"name":"X","summary":"s"},{"name":"Y","summary":"s"}]}'))])
    async def fake(db, u): return GW()
    monkeypatch.setattr("app.routers.papers.build_user_gateway", fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed(c, h)
        pid = (await c.post("/papers", headers=h,
                            files={"file":("p.pdf", _pdf("hi"), "application/pdf")},
                            data={"title":"A"})).json()["id"]
        for _ in range(50):
            rs = (await c.get("/concepts", headers=h)).json()
            if len(rs) == 2: break
            await asyncio.sleep(0.1)

        ConceptM = concept_model_for(1536)
        async with get_sessionmaker()() as db:
            n_concepts_before = (await db.execute(select(func.count()).select_from(ConceptM))).scalar()
            n_edges_before = (await db.execute(select(func.count()).select_from(ConceptEdge))).scalar()
        assert n_concepts_before == 2 and n_edges_before >= 1

        await c.delete(f"/papers/{pid}", headers=h)

        async with get_sessionmaker()() as db:
            n_concepts_after = (await db.execute(select(func.count()).select_from(ConceptM))).scalar()
            n_edges_after = (await db.execute(select(func.count()).select_from(ConceptEdge))).scalar()
        assert n_concepts_after == 0
        assert n_edges_after == 0


async def test_delete_paper_keeps_concepts_with_other_sources(
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
        h = await _signup(c)
        await _seed(c, h)
        p1 = (await c.post("/papers", headers=h,
                           files={"file":("a.pdf", _pdf("a"), "application/pdf")},
                           data={"title":"A"})).json()["id"]
        for _ in range(40):
            rs = (await c.get("/concepts", headers=h)).json()
            if rs: break
            await asyncio.sleep(0.1)
        await c.post("/papers", headers=h,
                     files={"file":("b.pdf", _pdf("b"), "application/pdf")},
                     data={"title":"B"})
        await asyncio.sleep(1.5)

        await c.delete(f"/papers/{p1}", headers=h)

        rs = (await c.get("/concepts", headers=h)).json()
        assert len(rs) == 1  # Shared still alive, only sourced from p2 now
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_paper_delete_cleanup.py -v
```

Expected: first test fails — concepts and edges remain after delete.

- [ ] **Step 3: Implement**

Edit `backend/app/routers/papers.py` `delete` handler. Before `await db.delete(p)` add a cleanup pass that:
1. For each concept-dim table the user has data in, find concepts whose `source_paper_ids` contains `pid`. Remove `pid` from the list. If list becomes empty, delete that concept and any edges referencing it. If non-empty, just persist the trimmed list.
2. Run before deleting the Paper row so the foreign-key chunk cascade still works.

```python
from sqlalchemy import select, delete as sa_delete
from app.models import (
    Concept768, Concept1024, Concept1536, ConceptEdge,
)


async def _prune_concepts_for_paper(db, user_id, pid) -> None:
    for ConceptM in (Concept768, Concept1024, Concept1536):
        rows = (
            await db.execute(
                select(ConceptM).where(ConceptM.user_id == user_id)
            )
        ).scalars().all()
        for r in rows:
            srcs = list(r.source_paper_ids or [])
            if pid not in srcs:
                continue
            srcs = [s for s in srcs if s != pid]
            if srcs:
                r.source_paper_ids = srcs
                continue
            # last source — delete edges then the concept itself
            await db.execute(
                sa_delete(ConceptEdge).where(
                    ConceptEdge.user_id == user_id,
                    (ConceptEdge.src_id == r.id) | (ConceptEdge.dst_id == r.id),
                )
            )
            await db.delete(r)
```

In `delete(...)`:

```python
@router.delete("/{pid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(pid: UUID, user: CurrentUser, db: DbSession) -> None:
    p = (
        await db.execute(
            select(Paper).where(Paper.id == pid, Paper.user_id == user.id)
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        await Storage().delete_object(p.s3_key)
    except Exception:
        log.warning("blob %s not deleted; continuing", p.s3_key)
    await _prune_concepts_for_paper(db, user.id, p.id)
    await db.delete(p)
    await db.commit()
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_paper_delete_cleanup.py -v
cd backend && .venv/bin/pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/papers.py backend/tests/test_paper_delete_cleanup.py
git commit -m "feat(papers): prune concepts and edges on paper deletion"
```

---

## Task 5: Upload size cap + magic-byte sniff

**Files:**
- Modify: `backend/app/config.py`, `backend/app/routers/papers.py`
- Test: `backend/tests/test_paper_size.py`

**Context:** Plan 2 reviewer Important #5 + #6. Add a size limit (default 50 MB) and a 5-byte magic check (`%PDF-`) so non-PDFs labeled `application/pdf` get rejected at the router instead of inside background ingest.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_paper_size.py`:

```python
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
        # Bogus content claiming to be a PDF; lacks %PDF- magic.
        r = await c.post(
            "/papers", headers=h,
            files={"file":("p.pdf", b"NOTAPDF", "application/pdf")},
            data={"title":"fake"},
        )
        assert r.status_code == 415
        assert "PDF" in r.json()["detail"] or "pdf" in r.json()["detail"]
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_paper_size.py -v
```

Expected: both fail (no size cap, no magic check).

- [ ] **Step 3: Implement settings**

Edit `backend/app/config.py` — add:

```python
paper_max_bytes: int = 50_000_000  # 50 MB
```

- [ ] **Step 4: Implement router checks**

Edit `backend/app/routers/papers.py` `upload` handler. After the content-type check, replace the `data = await file.read()` block with:

```python
    settings = get_settings()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.paper_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large; max {settings.paper_max_bytes} bytes",
        )
    if not data.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=415,
            detail="File does not look like a PDF (missing %PDF- header)",
        )
```

Add `from app.config import get_settings` to the imports.

- [ ] **Step 5: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_paper_size.py -v
cd backend && .venv/bin/pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/routers/papers.py backend/tests/test_paper_size.py
git commit -m "feat(papers): enforce upload size cap and PDF magic-byte check"
```

---

## Task 6: `cookie_secure` setting for OAuth state

**Files:**
- Modify: `backend/app/config.py`, `backend/app/routers/oauth.py`

**Context:** Plan 2 reviewer Important #7. Production needs `Secure` on the state cookie; dev runs over plain HTTP. Drive from a setting, default false.

- [ ] **Step 1: Add setting**

Edit `backend/app/config.py`:

```python
cookie_secure: bool = False
```

- [ ] **Step 2: Use it in oauth router**

Edit `backend/app/routers/oauth.py`. In the `set_cookie` call inside `login_start`, replace `secure=False` with `secure=get_settings().cookie_secure`. (Already calls `get_settings()` in the body — reuse the local `s` variable.)

```python
    response.set_cookie(
        STATE_COOKIE, state,
        max_age=STATE_TTL,
        httponly=True, samesite="lax",
        secure=s.cookie_secure,
    )
```

- [ ] **Step 3: Verify nothing broke**

```bash
cd backend && .venv/bin/pytest tests/test_oauth.py tests/test_oauth_state.py -v
cd backend && .venv/bin/pytest -q
```

Expected: all green (default false matches existing behavior).

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py backend/app/routers/oauth.py
git commit -m "feat(config): cookie_secure setting drives oauth state cookie Secure flag"
```

---

## Task 7: Expose `chunks_count` and `concepts_count` on `PaperOut`

**Files:**
- Modify: `backend/app/schemas/paper.py`, `backend/app/routers/papers.py`
- Test: `backend/tests/test_papers.py` (extend existing happy-path test)

**Context:** Plan 2 reviewer Minor M2. The detail page already implies these counts exist; add them to the schema and compute via two cheap counts per paper.

- [ ] **Step 1: Update schema**

Edit `backend/app/schemas/paper.py`:

```python
class PaperOut(BaseModel):
    id: UUID
    title: str
    authors: str
    uploaded_at: datetime
    status: str
    parse_error: str | None = None
    chunks_count: int = 0
    concepts_count: int = 0
```

- [ ] **Step 2: Compute counts in router**

Edit `backend/app/routers/papers.py`. The current `_to_out(p)` is sync; we need access to `db` to count. Replace with an async helper that takes `(db, p, embed_dim)`:

```python
from sqlalchemy import func, cast, ARRAY, Uuid
from app.models import LLMConfig, chunk_model_for, concept_model_for


async def _to_out_async(db, p: Paper, embed_dim: int | None) -> PaperOut:
    chunks_count = 0
    concepts_count = 0
    if embed_dim is not None:
        ChunkM = chunk_model_for(embed_dim)
        ConceptM = concept_model_for(embed_dim)
        chunks_count = (
            await db.execute(
                select(func.count()).select_from(ChunkM).where(ChunkM.paper_id == p.id)
            )
        ).scalar() or 0
        concepts_count = (
            await db.execute(
                select(func.count()).select_from(ConceptM)
                .where(ConceptM.user_id == p.user_id)
                .where(ConceptM.source_paper_ids.any(p.id))
            )
        ).scalar() or 0
    return PaperOut(
        id=p.id, title=p.title, authors=p.authors or "",
        uploaded_at=p.uploaded_at, status=p.status.value,
        parse_error=p.parse_error,
        chunks_count=chunks_count, concepts_count=concepts_count,
    )


async def _resolve_embed_dim(db, user_id) -> int | None:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user_id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    return cfg.embed_dim if cfg else None
```

Note on the `source_paper_ids.any(p.id)` query: SQLAlchemy's pgvector + ARRAY operators include `.any(value)` which translates to PostgreSQL's `value = ANY(column)`. If your installed SQLAlchemy version doesn't expose this on `Mapped[list[UUID]]`, fall back to a literal comparison:

```python
from sqlalchemy import literal
.where(literal(p.id) == func.any(ConceptM.source_paper_ids))
```

Update each handler to await `_to_out_async`:

```python
@router.post("", response_model=PaperOut, status_code=status.HTTP_201_CREATED)
async def upload(...) -> PaperOut:
    # existing logic up through bg.add_task ...
    return await _to_out_async(db, paper, cfg.embed_dim)


@router.get("", response_model=list[PaperOut])
async def list_(user: CurrentUser, db: DbSession) -> list[PaperOut]:
    rows = (
        await db.execute(
            select(Paper).where(Paper.user_id == user.id)
            .order_by(Paper.uploaded_at.desc())
        )
    ).scalars().all()
    dim = await _resolve_embed_dim(db, user.id)
    return [await _to_out_async(db, p, dim) for p in rows]


@router.get("/{pid}", response_model=PaperOut)
async def get_one(pid: UUID, user: CurrentUser, db: DbSession) -> PaperOut:
    p = (
        await db.execute(
            select(Paper).where(Paper.id == pid, Paper.user_id == user.id)
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    dim = await _resolve_embed_dim(db, user.id)
    return await _to_out_async(db, p, dim)


@router.post("/{pid}/reingest", response_model=PaperOut)
async def reingest(...) -> PaperOut:
    # existing logic ...
    return await _to_out_async(db, p, cfg.embed_dim)
```

- [ ] **Step 3: Add count assertion to existing happy-path test**

Edit `backend/tests/test_papers.py`. In `test_upload_creates_paper_and_runs_ingest`, after waiting for `status == parsed`, assert `chunks_count >= 1` and `concepts_count >= 1`. Use a polling loop similar to `test_concepts.py`:

```python
import asyncio

# inside the test, after `assert r.status_code == 201`:
for _ in range(50):
    body = (await c.get(f"/papers/{pid}", headers=h)).json()
    if body["status"] == "parsed" and body["chunks_count"] >= 1:
        break
    await asyncio.sleep(0.1)
assert body["chunks_count"] >= 1
assert body["concepts_count"] >= 1
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_papers.py -v
cd backend && .venv/bin/pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/paper.py backend/app/routers/papers.py backend/tests/test_papers.py
git commit -m "feat(papers): expose chunks_count and concepts_count on PaperOut"
```

---

## Task 8: `FeynmanSession` model + migration

**Files:**
- Create: `backend/app/models/feynman_session.py`, `backend/alembic/versions/<rev>_feynman_session.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_feynman_model.py`

**Context:** Sessions store a JSONB transcript; `target_concept_id` is a UUID with no FK because concepts live in dim-sharded tables.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_feynman_model.py`:

```python
from app.models import FeynmanSession, FeynmanKind


def test_feynman_session_columns():
    cols = FeynmanSession.__table__.columns.keys()
    for c in (
        "id", "user_id", "paper_id", "target_concept_id",
        "kind", "started_at", "ended_at",
        "quality_score", "transcript",
    ):
        assert c in cols


def test_feynman_kind_enum_values():
    assert FeynmanKind.fresh.value == "fresh"
    assert FeynmanKind.scheduled.value == "scheduled"
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_model.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement model**

Create `backend/app/models/feynman_session.py`:

```python
import enum
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime, Enum as SAEnum, ForeignKey, Numeric, Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FeynmanKind(str, enum.Enum):
    fresh = "fresh"
    scheduled = "scheduled"


class FeynmanSession(Base):
    __tablename__ = "feynman_session"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    paper_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("paper.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    # Concepts live in dim-sharded tables — no FK, service layer enforces.
    target_concept_id: Mapped[UUID] = mapped_column(Uuid, index=True)

    kind: Mapped[FeynmanKind] = mapped_column(
        SAEnum(FeynmanKind, name="feynman_kind"), default=FeynmanKind.fresh
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    quality_score: Mapped[float | None] = mapped_column(
        Numeric(5, 4), nullable=True,
    )
    # transcript = list of {"role": "user"|"assistant"|"system", "content": str, "ts": iso8601}
    transcript: Mapped[list[dict]] = mapped_column(JSONB, default=list)
```

- [ ] **Step 4: Update `__init__.py`**

Append to `backend/app/models/__init__.py`:

```python
from app.models.feynman_session import FeynmanSession, FeynmanKind
```

- [ ] **Step 5: Generate migration**

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "feynman_session"
```

Edit the resulting file. Wrap the enum's `CREATE TYPE` in the same idempotent `DO $$ … EXCEPTION` pattern Plan 2 used (see `e4ad1e7b8012_papers_chunks_concepts.py` for reference). Set `down_revision = "e4ad1e7b8012"`.

- [ ] **Step 6: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_model.py tests/test_migrations.py -v
cd backend && .venv/bin/pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/models backend/alembic/versions backend/tests/test_feynman_model.py
git commit -m "feat(models): feynman_session with jsonb transcript and quality_score"
```

---

## Task 9: SSE helpers

**Files:**
- Create: `backend/app/services/sse.py`
- Test: `backend/tests/test_sse.py`

**Context:** Two helpers: `sse_event(payload)` formats an SSE frame; `stream_chat(gateway, messages)` consumes the OpenAI-style streamed chat completion and yields `(text_delta, finish_reason)` so the router can both forward to the client and accumulate the final text for the transcript.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_sse.py`:

```python
import json

from app.services.sse import sse_event, stream_chat


def test_sse_event_string_payload():
    out = sse_event("hello")
    assert out == b"data: hello\n\n"


def test_sse_event_dict_payload_json():
    out = sse_event({"text": "x"})
    assert out.startswith(b"data: ")
    body = out[len(b"data: "):-2]  # strip prefix + final blank line
    assert body.endswith(b"\n")
    payload = json.loads(body.rstrip(b"\n"))
    assert payload == {"text": "x"}


async def test_stream_chat_yields_deltas_and_full():
    """gateway.chat with stream=True returns an async-iterable; we mock that."""
    class FakeStream:
        def __init__(self, deltas):
            self._d = deltas
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

    class FakeGW:
        async def chat(self, messages, stream=False):
            assert stream is True
            return FakeStream(["hel", "lo"])

    chunks = []
    async for delta, finish in stream_chat(FakeGW(), [{"role": "user", "content": "x"}]):
        chunks.append((delta, finish))
    assert chunks[:2] == [("hel", None), ("lo", None)]
    assert chunks[-1][1] == "stop"
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_sse.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Create `backend/app/services/sse.py`:

```python
"""Server-Sent Events helpers + chat streaming adapter."""
import json
from typing import AsyncIterator


def sse_event(payload) -> bytes:
    """Format one SSE frame. Strings pass through; dict/list become JSON."""
    if isinstance(payload, (dict, list)):
        body = json.dumps(payload, separators=(",", ":"))
    else:
        body = str(payload)
    # Multi-line content must be re-prefixed with "data:" per SSE spec.
    lines = body.split("\n")
    return ("\n".join(f"data: {ln}" for ln in lines) + "\n\n").encode("utf-8")


async def stream_chat(gateway, messages) -> AsyncIterator[tuple[str | None, str | None]]:
    """Adapt gateway.chat(stream=True) into (delta, finish_reason) tuples.

    Both fields may be None on the same chunk; consumers should accumulate
    delta strings and stop when finish_reason is set.
    """
    stream = await gateway.chat(messages, stream=True)
    async for chunk in stream:
        choice = chunk.choices[0]
        delta = getattr(choice.delta, "content", None)
        finish = getattr(choice, "finish_reason", None)
        yield delta, finish
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_sse.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sse.py backend/tests/test_sse.py
git commit -m "feat(sse): event formatter and chat-stream adapter"
```

---

## Task 10: Feynman service helpers (target picker, system prompt, grader)

**Files:**
- Create: `backend/app/services/feynman.py`
- Test: `backend/tests/test_feynman_service.py`

**Context:** Three pure-ish helpers. `pick_target_concept` finds a concept for the session given an optional paper_id. `build_system_prompt` renders the curious-student persona. `grade_transcript` calls the chat LLM with a grading rubric and returns a float in [0,1].

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_feynman_service.py`:

```python
import types
import pytest

from app.services.feynman import (
    build_system_prompt,
    grade_transcript,
)


def test_build_system_prompt_mentions_concept_name():
    out = build_system_prompt(concept_name="Self-attention", concept_summary="x")
    assert "Self-attention" in out
    assert "curious" in out.lower() or "student" in out.lower()


async def test_grade_transcript_parses_score():
    class GW:
        async def chat(self, messages, stream=False):
            assert stream is False
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content='{"score": 0.74}'))])

    s = await grade_transcript(GW(), [
        {"role": "user", "content": "I will explain self-attention."},
        {"role": "assistant", "content": "OK go ahead."},
    ])
    assert 0.0 <= s <= 1.0
    assert abs(s - 0.74) < 1e-9


async def test_grade_transcript_clamps_out_of_range():
    class GW:
        async def chat(self, messages, stream=False):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content='{"score": 1.7}'))])
    assert await grade_transcript(GW(), [{"role": "user", "content": "x"}]) == 1.0


async def test_grade_transcript_bad_json_raises():
    class GW:
        async def chat(self, messages, stream=False):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="not json"))])
    with pytest.raises(ValueError):
        await grade_transcript(GW(), [])
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_service.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Create `backend/app/services/feynman.py`:

```python
"""Feynman teach-back support: prompt rendering and grading.

`pick_target_concept` is implemented in the router because it requires DB +
embed_dim resolution; keeping this module pure (no DB) helps testing.
"""
import json


_SYSTEM_TEMPLATE = """You are a curious undergraduate student. The user will explain "{name}" to you.
{summary_block}
Ask short, naive "why?" and "how?" questions whenever the user's explanation has a gap, jumps a step, or uses jargon without grounding. Do NOT explain the concept yourself. Do NOT provide answers. Do NOT lecture. Keep each turn to one or two questions, max 40 words. If the user explanation is genuinely complete and self-consistent, ask them to extend it to a related case.
"""


_GRADER_PROMPT = """You are a strict tutor evaluating a student's Feynman teach-back transcript.
Score the student's explanation quality from 0.0 to 1.0:
- 0.0 = wrong, contradictory, or vacuous.
- 0.5 = partially correct, gaps remain.
- 1.0 = clear, complete, self-consistent, handles follow-ups.
Return ONLY strict JSON of the form: {"score": <float>}
"""


def build_system_prompt(*, concept_name: str, concept_summary: str = "") -> str:
    sb = f"Background: {concept_summary}\n" if concept_summary else ""
    return _SYSTEM_TEMPLATE.format(name=concept_name, summary_block=sb)


async def grade_transcript(gateway, transcript: list[dict]) -> float:
    body = "\n".join(f"{t['role']}: {t['content']}" for t in transcript)
    msg = [
        {"role": "system", "content": _GRADER_PROMPT},
        {"role": "user", "content": body},
    ]
    resp = await gateway.chat(msg)
    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
        score = float(data["score"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise ValueError(f"grader returned non-numeric score: {content!r}") from e
    return max(0.0, min(1.0, score))
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/feynman.py backend/tests/test_feynman_service.py
git commit -m "feat(feynman): system prompt builder + transcript grader"
```

---

## Task 11: Feynman schemas + `/feynman` router (start, get)

**Files:**
- Create: `backend/app/schemas/feynman.py`, `backend/app/routers/feynman.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_feynman_router.py`

**Context:** Two endpoints first — `POST /feynman/start` and `GET /feynman/{sid}`. Streaming endpoints come in Task 12.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_feynman_router.py`:

```python
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
        # transcript seeded with system message
        assert any(t["role"] == "system" for t in body["transcript"])


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
        # seed config but no papers ⇒ no concepts
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_router.py -v
```

Expected: 404 on POST `/feynman/start` (router not registered).

- [ ] **Step 3: Implement schemas**

Create `backend/app/schemas/feynman.py`:

```python
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FeynmanStartIn(BaseModel):
    paper_id: UUID | None = None
    kind: Literal["fresh", "scheduled"] = "fresh"


class FeynmanMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class FeynmanSessionOut(BaseModel):
    id: UUID
    user_id: UUID
    paper_id: UUID | None
    target_concept_id: UUID
    kind: str
    started_at: datetime
    ended_at: datetime | None
    quality_score: float | None
    transcript: list[dict]


class FeynmanGradeOut(BaseModel):
    quality_score: float
```

- [ ] **Step 4: Implement router**

Create `backend/app/routers/feynman.py`:

```python
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import (
    FeynmanSession, FeynmanKind, LLMConfig, Paper, concept_model_for,
)
from app.schemas.feynman import (
    FeynmanStartIn, FeynmanSessionOut,
)
from app.services.feynman import build_system_prompt

log = logging.getLogger("syifa.feynman")
router = APIRouter(prefix="/feynman", tags=["feynman"])


def _to_out(s: FeynmanSession) -> FeynmanSessionOut:
    return FeynmanSessionOut(
        id=s.id, user_id=s.user_id, paper_id=s.paper_id,
        target_concept_id=s.target_concept_id, kind=s.kind.value,
        started_at=s.started_at, ended_at=s.ended_at,
        quality_score=float(s.quality_score) if s.quality_score is not None else None,
        transcript=s.transcript or [],
    )


async def _resolve_active_dim(db, user_id) -> int | None:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user_id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    return cfg.embed_dim if cfg else None


@router.post("/start", response_model=FeynmanSessionOut, status_code=status.HTTP_201_CREATED)
async def start(data: FeynmanStartIn, user: CurrentUser, db: DbSession) -> FeynmanSessionOut:
    dim = await _resolve_active_dim(db, user.id)
    if dim is None:
        raise HTTPException(status_code=400, detail="No active LLM config")
    ConceptM = concept_model_for(dim)

    if data.paper_id is not None:
        paper = (
            await db.execute(
                select(Paper).where(Paper.id == data.paper_id, Paper.user_id == user.id)
            )
        ).scalar_one_or_none()
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        candidate = (
            await db.execute(
                select(ConceptM).where(
                    ConceptM.user_id == user.id,
                    ConceptM.source_paper_ids.any(paper.id),
                ).order_by(ConceptM.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
    else:
        paper = None
        candidate = (
            await db.execute(
                select(ConceptM).where(ConceptM.user_id == user.id)
                .order_by(ConceptM.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()

    if candidate is None:
        raise HTTPException(status_code=400, detail="No concepts available; ingest a paper first")

    sys_prompt = build_system_prompt(
        concept_name=candidate.name, concept_summary=candidate.summary,
    )
    transcript = [{
        "role": "system",
        "content": sys_prompt,
        "ts": datetime.now(timezone.utc).isoformat(),
    }]

    session = FeynmanSession(
        user_id=user.id,
        paper_id=paper.id if paper else None,
        target_concept_id=candidate.id,
        kind=FeynmanKind(data.kind),
        transcript=transcript,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _to_out(session)


@router.get("/{sid}", response_model=FeynmanSessionOut)
async def get_one(sid: UUID, user: CurrentUser, db: DbSession) -> FeynmanSessionOut:
    s = (
        await db.execute(
            select(FeynmanSession).where(
                FeynmanSession.id == sid, FeynmanSession.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _to_out(s)
```

- [ ] **Step 5: Register router**

Edit `backend/app/main.py`:

```python
from app.routers import feynman as feynman_router
# ...
app.include_router(feynman_router.router)
```

- [ ] **Step 6: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_router.py -v
cd backend && .venv/bin/pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/feynman.py backend/app/routers/feynman.py backend/app/main.py backend/tests/test_feynman_router.py
git commit -m "feat(feynman): POST /feynman/start and GET /feynman/{sid}"
```

---

## Task 12: Feynman streaming `/message` endpoint

**Files:**
- Modify: `backend/app/routers/feynman.py`
- Test: extend `backend/tests/test_feynman_router.py`

**Context:** `POST /feynman/{sid}/message` accepts a user turn, persists it on the transcript immediately, then streams the model reply via SSE while accumulating the full text. When the stream finishes (or the client disconnects), persist the assistant turn to the transcript. Authentication uses the standard `Authorization` header — the frontend will use `fetch` + `ReadableStream` (not `EventSource`).

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_feynman_router.py`:

```python
async def test_message_streams_and_persists(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed_with_paper(c, h, monkeypatch)

        # Patch gateway used inside feynman router for streaming
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

        # transcript persisted with both user and assistant turns
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_router.py::test_message_streams_and_persists -v
```

Expected: 404 (endpoint missing).

- [ ] **Step 3: Implement**

Edit `backend/app/routers/feynman.py`. Add imports and endpoint:

```python
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi.responses import StreamingResponse
from sqlalchemy.orm.attributes import flag_modified

from app.schemas.feynman import FeynmanMessageIn
from app.services.sse import sse_event, stream_chat
from app.services.user_llm import build_user_gateway


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/{sid}/message")
async def message(
    sid: UUID,
    data: FeynmanMessageIn,
    user: CurrentUser,
    db: DbSession,
):
    s = (
        await db.execute(
            select(FeynmanSession).where(
                FeynmanSession.id == sid, FeynmanSession.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if s.ended_at is not None:
        raise HTTPException(status_code=400, detail="Session already ended")

    gw = await build_user_gateway(db, user)

    user_turn = {"role": "user", "content": data.content, "ts": _now_iso()}
    s.transcript = list(s.transcript or []) + [user_turn]
    flag_modified(s, "transcript")
    await db.commit()

    # Build LLM messages from transcript (drop ts).
    llm_msgs = [{"role": t["role"], "content": t["content"]} for t in s.transcript]

    async def gen() -> AsyncIterator[bytes]:
        full: list[str] = []
        try:
            async for delta, finish in stream_chat(gw, llm_msgs):
                if delta:
                    full.append(delta)
                    yield sse_event(delta)
                if finish:
                    break
        except Exception as e:
            log.exception("stream failed for session %s", sid)
            yield sse_event({"error": str(e)})
        finally:
            assistant = "".join(full).strip()
            if assistant:
                # Re-load session in a fresh transaction so concurrent gets see updates
                fresh = (
                    await db.execute(
                        select(FeynmanSession).where(FeynmanSession.id == sid)
                    )
                ).scalar_one()
                fresh.transcript = list(fresh.transcript or []) + [{
                    "role": "assistant", "content": assistant, "ts": _now_iso(),
                }]
                flag_modified(fresh, "transcript")
                await db.commit()
            yield sse_event("[DONE]")

    return StreamingResponse(gen(), media_type="text/event-stream")
```

Note: `flag_modified` is required for SQLAlchemy to detect mutations of JSONB columns (re-assigning the list also works, but the explicit flag is robust to both styles).

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_router.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/feynman.py backend/tests/test_feynman_router.py
git commit -m "feat(feynman): POST /feynman/{sid}/message with SSE streaming + transcript persistence"
```

---

## Task 13: Feynman `/end` endpoint with grading

**Files:**
- Modify: `backend/app/routers/feynman.py`
- Test: extend `backend/tests/test_feynman_router.py`

**Context:** Ending a session triggers a grading LLM call; we set `quality_score`, `ended_at`, and return both the score and the full session.

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_feynman_router.py`:

```python
async def test_end_session_grades_and_sets_score(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup(c)
        await _seed_with_paper(c, h, monkeypatch)

        class GW:
            async def chat(self, messages, stream=False):
                # When called with stream=True (impossible from /end, but defensive)
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
        # Score unchanged on re-end
        assert r2.json()["quality_score"] == s1
```

- [ ] **Step 2: Run test**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_router.py::test_end_session_grades_and_sets_score -v
```

Expected: 404.

- [ ] **Step 3: Implement**

Add to `backend/app/routers/feynman.py`:

```python
from app.schemas.feynman import FeynmanGradeOut
from app.services.feynman import grade_transcript


@router.post("/{sid}/end", response_model=FeynmanGradeOut)
async def end(sid: UUID, user: CurrentUser, db: DbSession) -> FeynmanGradeOut:
    s = (
        await db.execute(
            select(FeynmanSession).where(
                FeynmanSession.id == sid, FeynmanSession.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if s.ended_at is not None and s.quality_score is not None:
        return FeynmanGradeOut(quality_score=float(s.quality_score))

    gw = await build_user_gateway(db, user)
    # Strip system prompts from grading view; grader rates the user's
    # explanation quality against the assistant's probes.
    msgs = [t for t in (s.transcript or []) if t.get("role") in ("user", "assistant")]
    score = await grade_transcript(gw, msgs)

    s.ended_at = datetime.now(timezone.utc)
    s.quality_score = score
    await db.commit()
    return FeynmanGradeOut(quality_score=score)
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_router.py -v
cd backend && .venv/bin/pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/feynman.py backend/tests/test_feynman_router.py
git commit -m "feat(feynman): POST /feynman/{sid}/end grades transcript and persists score"
```

---

## Task 14: Frontend SSE consumer composable

**Files:**
- Create: `frontend/app/composables/useStream.ts`

**Context:** Wraps `fetch` + `ReadableStream` so callers can `for-await` over decoded SSE `data:` payloads. Uses the bearer token from the auth store automatically. EventSource can't send headers, so this is required.

- [ ] **Step 1: Implement**

Create `frontend/app/composables/useStream.ts`:

```ts
import { useAuthStore } from "~/stores/auth"

export function useStream() {
  const config = useRuntimeConfig()
  const auth = useAuthStore()

  async function* postSSE(path: string, body: unknown): AsyncGenerator<string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }
    if (auth.access) headers.Authorization = `Bearer ${auth.access}`

    const resp = await fetch(`${config.public.apiBase}${path}`, {
      method: "POST", headers, body: JSON.stringify(body),
    })
    if (!resp.ok || !resp.body) {
      const text = await resp.text()
      throw new Error(`${resp.status}: ${text}`)
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder("utf-8")
    let buf = ""
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const frames = buf.split("\n\n")
      buf = frames.pop() || ""
      for (const f of frames) {
        const lines = f.split("\n").filter(l => l.startsWith("data: "))
        if (!lines.length) continue
        const payload = lines.map(l => l.slice(6)).join("\n")
        if (payload === "[DONE]") return
        yield payload
      }
    }
  }

  return { postSSE }
}
```

- [ ] **Step 2: Build verification**

```bash
cd frontend && npm run build
```

Expected: clean build, no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/composables/useStream.ts
git commit -m "feat(frontend): useStream composable for fetch-based SSE consumption"
```

---

## Task 15: Frontend Feynman chat page

**Files:**
- Create: `frontend/app/pages/feynman/[sid].vue`

**Context:** Renders transcript, an input, send button, and end button. Sending consumes `useStream().postSSE` and appends the streamed text to a working assistant bubble. End submits to `/feynman/[sid]/end`, shows the score, and disables further input.

- [ ] **Step 1: Implement**

Create `frontend/app/pages/feynman/[sid].vue`:

```vue
<template>
  <div v-if="session" class="max-w-2xl mx-auto space-y-4">
    <NuxtLink to="/papers" class="text-sm underline">← back to papers</NuxtLink>
    <h1 class="text-xl font-semibold">Feynman session</h1>
    <div class="text-xs text-neutral-500">
      target: {{ session.target_concept_id.slice(0, 8) }} ·
      kind: {{ session.kind }} ·
      score: {{ session.quality_score ?? "—" }}
    </div>

    <div class="space-y-2 border border-neutral-200 dark:border-neutral-800 rounded p-3 max-h-[60vh] overflow-y-auto">
      <div v-for="(t, i) in displayTurns" :key="i"
           class="text-sm"
           :class="t.role === 'user' ? 'text-neutral-900 dark:text-neutral-100' : 'text-neutral-600 dark:text-neutral-400'">
        <span class="font-mono text-xs uppercase tracking-wide">{{ t.role }}</span>
        <p class="whitespace-pre-wrap">{{ t.content }}</p>
      </div>
      <div v-if="streaming" class="text-sm text-neutral-600 dark:text-neutral-400">
        <span class="font-mono text-xs uppercase tracking-wide">assistant</span>
        <p class="whitespace-pre-wrap">{{ assistantBuffer }}<span class="animate-pulse">▌</span></p>
      </div>
    </div>

    <form @submit.prevent="onSend" class="flex gap-2" v-if="!session.ended_at">
      <input v-model="draft" placeholder="explain it back…"
             :disabled="streaming"
             class="flex-1 input" />
      <button class="rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2"
              :disabled="streaming || !draft.trim()">
        Send
      </button>
      <button type="button" @click="onEnd"
              class="rounded border border-red-500 text-red-600 px-3 py-2 text-sm"
              :disabled="streaming">
        End
      </button>
    </form>
    <p v-else class="text-sm text-neutral-500">
      Session ended. quality score: <span class="font-mono">{{ session.quality_score }}</span>
    </p>
    <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
  </div>
  <p v-else-if="loading" class="text-sm text-neutral-500">Loading…</p>
  <p v-else class="text-sm text-red-600">Session not found.</p>
</template>

<style scoped>
@reference "tailwindcss";
.input { @apply rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2; }
</style>

<script setup lang="ts">
type Turn = { role: string; content: string; ts: string }
type Session = {
  id: string; user_id: string; paper_id: string | null;
  target_concept_id: string; kind: string;
  started_at: string; ended_at: string | null;
  quality_score: number | null;
  transcript: Turn[]
}
const route = useRoute()
const { call } = useApi()
const { postSSE } = useStream()

const session = ref<Session | null>(null)
const loading = ref(true)
const draft = ref("")
const assistantBuffer = ref("")
const streaming = ref(false)
const error = ref("")

const displayTurns = computed(() =>
  (session.value?.transcript ?? []).filter(t => t.role !== "system")
)

async function load() {
  try { session.value = await call<Session>(`/feynman/${route.params.sid}`) }
  catch { session.value = null }
  finally { loading.value = false }
}
onMounted(load)

async function onSend() {
  if (!draft.value.trim() || !session.value) return
  error.value = ""
  streaming.value = true
  assistantBuffer.value = ""
  const content = draft.value
  draft.value = ""
  // Optimistic local append
  session.value.transcript.push({
    role: "user", content, ts: new Date().toISOString(),
  })
  try {
    for await (const chunk of postSSE(`/feynman/${route.params.sid}/message`, { content })) {
      // server may send error frames as JSON
      try {
        const parsed = JSON.parse(chunk)
        if (parsed && typeof parsed === "object" && "error" in parsed) {
          error.value = parsed.error as string
          continue
        }
      } catch {/* plain text — fine */}
      assistantBuffer.value += chunk
    }
    session.value.transcript.push({
      role: "assistant", content: assistantBuffer.value, ts: new Date().toISOString(),
    })
  } catch (e: any) {
    error.value = e?.message || "stream failed"
  } finally {
    assistantBuffer.value = ""
    streaming.value = false
  }
}

async function onEnd() {
  try {
    const r = await call<{ quality_score: number }>(`/feynman/${route.params.sid}/end`, { method: "POST" })
    if (session.value) {
      session.value.quality_score = r.quality_score
      session.value.ended_at = new Date().toISOString()
    }
  } catch (e: any) {
    error.value = e?.message || "end failed"
  }
}
</script>
```

- [ ] **Step 2: Build**

```bash
cd frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/pages/feynman/[sid].vue
git commit -m "feat(frontend): /feynman/[sid] chat page with SSE streaming and end+score"
```

---

## Task 16: "Teach me back" button on `/papers/[id]`

**Files:**
- Modify: `frontend/app/pages/papers/[id].vue`

**Context:** Add a button visible when `paper.status === "parsed" && paper.concepts_count > 0`. Clicking POSTs `/feynman/start {paper_id, kind:"fresh"}` and navigates to the resulting session.

- [ ] **Step 1: Modify the page**

Edit `frontend/app/pages/papers/[id].vue`. After the action buttons, add:

```vue
    <button v-if="paper.status === 'parsed' && paper.concepts_count > 0"
            @click="startFeynman"
            class="rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2 text-sm">
      Teach me back
    </button>
```

In the script:

```ts
async function startFeynman() {
  const r = await call<{ id: string }>("/feynman/start", {
    method: "POST",
    body: JSON.stringify({ paper_id: route.params.id, kind: "fresh" }),
  })
  await router.push(`/feynman/${r.id}`)
}
```

Also update the `Paper` type to include the new fields:

```ts
type Paper = {
  id: string; title: string; uploaded_at: string; status: string;
  parse_error: string | null;
  chunks_count: number;
  concepts_count: number;
}
```

- [ ] **Step 2: Build**

```bash
cd frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/pages/papers/[id].vue
git commit -m "feat(frontend): Teach me back button on paper detail starts a Feynman session"
```

---

## Task 17: Playwright e2e — fresh Feynman from a paper

**Files:**
- Create: `frontend/tests/e2e/feynman.spec.ts`

**Context:** End-to-end exercises: signup → seed+activate llm-config → upload PDF → wait for parsed → click "Teach me back" → on chat page, send a message → see streamed assistant reply → end → see score. Backend gateway is the real local one but with a stub-friendly setup; we don't actually need the LLM to return anything sensible — just need responses to flow.

The simplest path is to use `page.route()` to intercept the backend `/feynman/*` and `/papers/*` calls and short-circuit them with synthetic SSE responses, OR run against a backend with a fake gateway (see `backend/tests/test_feynman_router.py` for the in-process pattern).

For this task: use Playwright's `page.route()` to mock the backend `POST /feynman/start`, `POST /feynman/.../message` (SSE), and `POST /feynman/.../end`. That keeps the test self-contained.

- [ ] **Step 1: Write spec**

Create `frontend/tests/e2e/feynman.spec.ts`:

```ts
import { test, expect } from "@playwright/test"

const unique = () => `u${Date.now()}@test.example`

test("teach-back: start, message stream, end with score", async ({ page }) => {
  const email = unique()
  const password = "correct horse battery staple"

  // Signup
  await page.goto("/signup")
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button:has-text("Sign up")')
  await expect(page.getByText(`Welcome, ${email}`)).toBeVisible()

  // Stub everything Feynman-related at the network layer.
  const sid = "00000000-0000-0000-0000-000000000001"
  const cid = "00000000-0000-0000-0000-000000000002"
  let getCount = 0
  await page.route("**/feynman/start", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: sid, user_id: "u", paper_id: null,
        target_concept_id: cid, kind: "fresh",
        started_at: new Date().toISOString(), ended_at: null,
        quality_score: null,
        transcript: [{ role: "system", content: "sys", ts: "" }],
      }),
    })
  })
  await page.route(`**/feynman/${sid}`, async (route) => {
    getCount += 1
    const ended = getCount > 2
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        id: sid, user_id: "u", paper_id: null,
        target_concept_id: cid, kind: "fresh",
        started_at: "", ended_at: ended ? new Date().toISOString() : null,
        quality_score: ended ? 0.42 : null,
        transcript: [{ role: "system", content: "sys", ts: "" }],
      }),
    })
  })
  await page.route(`**/feynman/${sid}/message`, async (route) => {
    const body = "data: Why\n\ndata:  self-attention?\n\ndata: [DONE]\n\n"
    await route.fulfill({
      status: 200, contentType: "text/event-stream", body,
    })
  })
  await page.route(`**/feynman/${sid}/end`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ quality_score: 0.42 }),
    })
  })

  // Land directly on the chat page (skips needing a real paper for this e2e).
  await page.goto(`/feynman/${sid}`)
  await expect(page.getByText("Feynman session")).toBeVisible()
  await page.fill('input[placeholder="explain it back…"]', "self-attention is when…")
  await page.click('button:has-text("Send")')
  await expect(page.getByText(/Why\s+self-attention\?/)).toBeVisible({ timeout: 5_000 })

  await page.click('button:has-text("End")')
  await expect(page.getByText("0.42")).toBeVisible()
})
```

- [ ] **Step 2: Run**

```bash
cd frontend && npm run test:e2e
```

Expected: 3 tests pass (foundation + papers + feynman).

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/feynman.spec.ts
git commit -m "test(frontend): Playwright e2e for Feynman chat with stubbed SSE"
```

---

## Task 18: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update sections**

Edit `README.md`:

- Add `Plan 3 (Feynman engine): docs/superpowers/plans/2026-04-27-feynman-engine.md` to the plans list.
- Under "What's live", add a new **Plan 3 (Feynman engine)** section describing:
  - `POST /feynman/start`, `GET /feynman/{sid}`, `POST /feynman/{sid}/message` (SSE), `POST /feynman/{sid}/end`.
  - `/feynman/[sid]` chat page with streaming.
  - "Teach me back" button on paper detail.
  - Plan 2 reviewer follow-ups: `embed_dim` Literal, dim-immutability, concept idempotency, paper-delete cleanup, paper size cap + magic-byte sniff, `cookie_secure`, `chunks_count`/`concepts_count`.
- Update "What's next" to point to Plan 4 (SM-2 scheduler + review queue + dashboard).

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README reflects Feynman engine and Plan 2 follow-ups"
```

---

## Self-Review Checklist

**Spec coverage (§3 v1 items handled by Plan 3):**
- [x] Fresh Feynman session (right after upload) — Tasks 11-13, 15-16
- [x] Plan 2 reviewer carries 1, 2, 3, 4, 5, 7 (the load-bearing ones) — Tasks 1-7

**Out of scope (deferred to Plan 4):** scheduled Feynman, SM-2, review_item, dashboard, /review and /dashboard pages. Reviewer Minor M1 (Storage singleton), M3 (reingest button on `uploaded`), M4 (head-chunks setting), M6 (test_concepts polling helper) — all non-load-bearing; can roll forward.

**Type / signature consistency:**
- `chunk_model_for(dim)` / `concept_model_for(dim)` — used identically in Tasks 2, 3, 4, 7, 11.
- `build_user_gateway(db, user)` — used in router/feynman + router/papers + still in router/llm_config. Single signature.
- `FeynmanKind` enum: `fresh|scheduled` — model + schema + router consistent.
- Transcript shape: `{role, content, ts}` — used in service/feynman + router/feynman + frontend. Consistent.
- `PaperOut.chunks_count`/`concepts_count` — Task 7 schema, Task 16 frontend type.
- `_to_out` rename: Task 7 changes paper router's helper from sync `_to_out` to async `_to_out_async`. All call sites updated in the same task.

**Placeholder scan:** none.

**Sequencing:**
- Tasks 1-7 are independent of each other except Task 7 (counts) doesn't depend on the others; Task 2 references Concept tables that already exist from Plan 2 — fine.
- Task 8 (model + migration) before any router work that touches `FeynmanSession`.
- Task 9 (SSE helpers) before Task 12 (uses `stream_chat`).
- Task 10 (service helpers) before Tasks 11 (uses `build_system_prompt`) and 13 (uses `grade_transcript`).
- Task 11 (start + get) before Task 12 (message uses session).
- Task 14 (useStream) before Task 15 (chat page).
- Task 15 + 16 before Task 17 (e2e).
- Linear order as written is valid.
