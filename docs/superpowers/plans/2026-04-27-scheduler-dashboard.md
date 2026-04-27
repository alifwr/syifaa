# Scheduler + Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out v1 by adding spaced-repetition scheduling for Feynman sessions and a dashboard surfacing concept count + quality-score trend.

**Architecture:** A new `review_item` row is upserted on every `/feynman/{sid}/end`; quality_score feeds an SM-2 update that sets `ease`, `interval_days`, `due_at`. `GET /review/due` lists items due now; `POST /review/start` opens a scheduled `FeynmanSession` for the chosen item. `GET /dashboard` returns concept count + recent (date, quality_score) pairs. The frontend gets `/review` (queue with start CTA) and `/dashboard` (count tile + simple table of scores). No chart library — the trend is rendered as a sortable table for v1; a sparkline can come later. Folds in the load-bearing carries from Plan 3's final review: streaming endpoint switches to a self-managed session, `feynman_session.embed_dim` persisted to defend against dim drift, `(user_id, started_at desc)` index, transcript size cap, and the off-by-one fix in `test_concept_match_is_case_insensitive`.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Alembic, pgvector, pure-function SM-2 scheduler, Nuxt 4, Playwright.

**Out of scope (Plan 5+):** atom-card flashcards, concept-map visualization, edge-curation UI, OCR, dim-transition migrator.

---

## File Structure

**Backend (new):**
- `backend/app/models/review_item.py` — `ReviewItem` ORM (one row per `(user_id, concept_id, embed_dim)`).
- `backend/app/services/sm2.py` — pure functions: `sm2_update(ease, interval_days, quality)` returning `(ease, interval_days)`. No DB.
- `backend/app/schemas/review.py` — `ReviewItemOut`, `ReviewStartIn`.
- `backend/app/schemas/dashboard.py` — `DashboardOut`, `SessionScorePoint`.
- `backend/app/routers/review.py` — `GET /review/due`, `POST /review/start`.
- `backend/app/routers/dashboard.py` — `GET /dashboard`.
- `backend/alembic/versions/<rev>_review_item_and_session_indices.py` — `review_item` table + composite index on `feynman_session(user_id, started_at desc)` + `embed_dim` column on `feynman_session`.
- `backend/tests/test_sm2.py`, `test_review_router.py`, `test_dashboard_router.py`, `test_streaming_session_lifecycle.py`, `test_transcript_size_cap.py`, `test_feynman_embed_dim_pinned.py`.

**Backend (modify):**
- `backend/app/models/feynman_session.py` — add `embed_dim: Mapped[int]` (NOT NULL).
- `backend/app/routers/feynman.py`:
  - `start` records the active dim onto the session row.
  - `message` opens its own `get_sessionmaker()()` session inside the SSE generator (Plan 3 reviewer Important #3).
  - `message` enforces a max-turns cap (`max_turns: int = 60` setting; reject 400 once the limit is hit).
  - `end` invokes SM-2 to upsert a `review_item`.
- `backend/app/config.py` — add `feynman_max_turns: int = 60`.
- `backend/app/main.py` — include `review_router`, `dashboard_router`.
- `backend/app/models/__init__.py` — export `ReviewItem`.
- `backend/tests/test_concept_idempotency.py` — fix off-by-one in `payloads[(calls["n"] - 1) % len(payloads)]` (Plan 3 reviewer Minor #5).

**Frontend (new):**
- `frontend/app/pages/review/index.vue` — list due items, "start review" buttons.
- `frontend/app/pages/dashboard.vue` — concept count tile + table of recent session scores.
- `frontend/tests/e2e/dashboard.spec.ts` — stubs `/dashboard`; asserts tile + table render.

**Frontend (modify):**
- `frontend/app/layouts/default.vue` — nav links to `/review` and `/dashboard` (auth-only).

---

## Task 1: Streaming `/message` uses a self-managed session

**Files:**
- Modify: `backend/app/routers/feynman.py`
- Test: `backend/tests/test_streaming_session_lifecycle.py`

**Context:** Plan 3 reviewer Important #3. Today the SSE generator captures the request-scoped `db` and re-uses it inside `finally` after the response has started. If the client disconnects mid-stream, the request session may be in a weird state. Open a fresh session inside the generator instead — same pattern `_run_ingest` uses in `papers.py`.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_streaming_session_lifecycle.py`:

```python
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
    """Regression: after streaming completes, the assistant turn is queryable
    from a brand-new DB session — i.e. the generator's commit really hit the
    database and didn't depend on the request session staying alive."""
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

        # Read with a fresh session, not the API client.
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
```

- [ ] **Step 2: Run test to verify it passes already (regression baseline)**

```bash
cd backend && .venv/bin/pytest tests/test_streaming_session_lifecycle.py -v
```

Today this test should already pass — confirm it does. We're locking in the contract before refactoring.

- [ ] **Step 3: Refactor message endpoint**

Edit `backend/app/routers/feynman.py`. Replace the `message` handler with:

```python
from app.db import get_sessionmaker


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

    llm_msgs = [{"role": t["role"], "content": t["content"]} for t in s.transcript]
    user_id = user.id  # capture before generator runs (avoid request-session attribute access later)

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
                # Use a self-managed session — the request-scoped `db` may
                # already be in cleanup by the time finally runs.
                maker = get_sessionmaker()
                async with maker() as bg_db:
                    fresh = (
                        await bg_db.execute(
                            select(FeynmanSession).where(
                                FeynmanSession.id == sid,
                                FeynmanSession.user_id == user_id,
                            )
                        )
                    ).scalar_one()
                    fresh.transcript = list(fresh.transcript or []) + [{
                        "role": "assistant", "content": assistant, "ts": _now_iso(),
                    }]
                    flag_modified(fresh, "transcript")
                    await bg_db.commit()
            yield sse_event("[DONE]")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Run tests to confirm both old and new pass**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_router.py tests/test_streaming_session_lifecycle.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/feynman.py backend/tests/test_streaming_session_lifecycle.py
git commit -m "fix(feynman): streaming /message commits via self-managed session"
```

---

## Task 2: Pin `embed_dim` on `FeynmanSession`

**Files:**
- Modify: `backend/app/models/feynman_session.py`
- Create: `backend/alembic/versions/<rev>_feynman_session_embed_dim.py`
- Modify: `backend/app/routers/feynman.py` (start sets it)
- Test: `backend/tests/test_feynman_embed_dim_pinned.py`

**Context:** Plan 3 reviewer Important #2 + #4. The session row references a concept by UUID alone; if the user somehow moves to a different dim, the concept disappears. Persist the dim at start time so we can validate cheaply later.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_feynman_embed_dim_pinned.py`:

```python
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


async def test_session_dim_column_not_null():
    cols = FeynmanSession.__table__.columns
    assert "embed_dim" in cols.keys()
    assert cols["embed_dim"].nullable is False
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_embed_dim_pinned.py -v
```

Expected: AttributeError on `row.embed_dim` / column not present.

- [ ] **Step 3: Update model**

Edit `backend/app/models/feynman_session.py`. Add column after `kind`:

```python
    embed_dim: Mapped[int] = mapped_column(Integer)
```

Add `Integer` to the imports from `sqlalchemy`.

- [ ] **Step 4: Generate migration**

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "feynman_session embed_dim and started_at index"
```

Read the generated file. Strip any spurious ivfflat / partial-unique drops (Plan 2/3 autogen quirk). Keep only:
- `op.add_column('feynman_session', sa.Column('embed_dim', sa.Integer(), nullable=True))` — start nullable
- A backfill: `op.execute("UPDATE feynman_session SET embed_dim = 1536 WHERE embed_dim IS NULL")` (1536 is the only dim used in dev so far; harmless if no rows).
- `op.alter_column('feynman_session', 'embed_dim', nullable=False)`
- `op.create_index('ix_feynman_session_user_started', 'feynman_session', ['user_id', sa.text('started_at DESC')])`

Downgrade reverses: `op.drop_index('ix_feynman_session_user_started', table_name='feynman_session')` then `op.drop_column('feynman_session', 'embed_dim')`.

Set `down_revision = "033233505aa3"`.

- [ ] **Step 5: Set on `start` handler**

Edit `backend/app/routers/feynman.py`. In `start(...)`, change the `FeynmanSession(...)` constructor to include `embed_dim=dim`:

```python
    session = FeynmanSession(
        user_id=user.id,
        paper_id=paper.id if paper else None,
        target_concept_id=candidate.id,
        kind=FeynmanKind(data.kind),
        embed_dim=dim,
        transcript=transcript,
    )
```

- [ ] **Step 6: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_embed_dim_pinned.py tests/test_migrations.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/feynman_session.py backend/app/routers/feynman.py backend/alembic/versions backend/tests/test_feynman_embed_dim_pinned.py
git commit -m "feat(feynman): pin embed_dim on session + index user_id, started_at desc"
```

---

## Task 3: Transcript size cap

**Files:**
- Modify: `backend/app/config.py`, `backend/app/routers/feynman.py`
- Test: `backend/tests/test_transcript_size_cap.py`

**Context:** Plan 3 reviewer Important #5 (Plan 4 punch list #5). An unbounded chat could push a single JSONB row to MB+ size. Refuse to append once a max-turns count is reached. 60 turns ≈ 30 user + 30 assistant exchanges = a long Feynman session.

- [ ] **Step 1: Add setting**

Edit `backend/app/config.py`:

```python
feynman_max_turns: int = 60
```

- [ ] **Step 2: Write failing test**

Create `backend/tests/test_transcript_size_cap.py`:

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
                    content='{"concepts":[{"name":"x","summary":"s"}]}'))])
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


async def test_message_rejected_after_max_turns(
    monkeypatch, s3_bucket, fernet_key, fresh_schema,
):
    monkeypatch.setenv("FEYNMAN_MAX_TURNS", "4")
    from app.config import get_settings
    get_settings.cache_clear()

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
                if stream: return FakeStream(["ok"])
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"score":0.5}'))])

        async def fake(db, u): return GW()
        monkeypatch.setattr("app.routers.feynman.build_user_gateway", fake)

        sid = (await c.post("/feynman/start", json={"kind":"fresh"}, headers=h)).json()["id"]

        # Each iteration adds 2 turns (user + assistant). Limit is 4.
        for i in range(2):
            async with c.stream(
                "POST", f"/feynman/{sid}/message",
                headers=h, json={"content": f"turn {i}"},
            ) as r:
                async for _ in r.aiter_lines(): pass

        # Third send should now be rejected: existing transcript already has
        # 4 non-system turns.
        r = await c.post(
            f"/feynman/{sid}/message",
            headers=h, json={"content": "third"},
        )
        assert r.status_code == 400
        assert "max" in r.json()["detail"].lower() or "turn" in r.json()["detail"].lower()
```

- [ ] **Step 3: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_transcript_size_cap.py -v
```

Expected: 200 instead of 400 on the third post.

- [ ] **Step 4: Implement guard**

Edit `backend/app/routers/feynman.py` `message` handler. After loading the session and the `ended_at` check, before `gw = await build_user_gateway(...)`, add:

```python
    settings = get_settings()
    non_system_turns = sum(1 for t in (s.transcript or []) if t.get("role") != "system")
    if non_system_turns >= settings.feynman_max_turns:
        raise HTTPException(
            status_code=400,
            detail=f"Max {settings.feynman_max_turns} turns reached; please end the session",
        )
```

Add `from app.config import get_settings` if not already imported.

- [ ] **Step 5: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_transcript_size_cap.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/routers/feynman.py backend/tests/test_transcript_size_cap.py
git commit -m "feat(feynman): cap session transcript at FEYNMAN_MAX_TURNS"
```

---

## Task 4: Fix `test_concept_match_is_case_insensitive` payload-cycle

**Files:**
- Modify: `backend/tests/test_concept_idempotency.py`

**Context:** Plan 3 reviewer Minor #5. The `payloads[calls["n"] % len(payloads) - 1]` expression has an off-by-one and is only coincidentally correct for the first 2 calls. Fix to `payloads[(calls["n"] - 1) % len(payloads)]`.

- [ ] **Step 1: Apply fix**

Edit `backend/tests/test_concept_idempotency.py` `test_concept_match_is_case_insensitive`. Replace:

```python
                content=payloads[calls["n"] % len(payloads) - 1]))])
```

with:

```python
                content=payloads[(calls["n"] - 1) % len(payloads)]))])
```

- [ ] **Step 2: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_concept_idempotency.py -v
```

Expected: still 3 green; the fix is semantically equivalent for the first 2 calls but correct for any number.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_concept_idempotency.py
git commit -m "test(ingest): correct payload-cycle indexing in concept idempotency test"
```

---

## Task 5: SM-2 pure function

**Files:**
- Create: `backend/app/services/sm2.py`
- Test: `backend/tests/test_sm2.py`

**Context:** SuperMemo-2 is a small pure function. Inputs: `ease` (float, default 2.5), `interval_days` (int, default 0 for new), `quality` (float in [0,1] from Feynman grader). Outputs: new `(ease, interval_days)`. Quality < 0.6 resets the streak (interval back to 1 day). The classic SM-2 uses a 0..5 integer; we map our 0..1 score to that range.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_sm2.py`:

```python
import pytest
from app.services.sm2 import sm2_update


def test_first_pass_high_quality_sets_one_day():
    ease, interval = sm2_update(ease=2.5, interval_days=0, quality=1.0)
    assert interval == 1
    assert ease >= 2.5  # ease can grow on perfect score


def test_second_pass_high_quality_sets_six_days():
    # After interval=1 + perfect, classic SM-2 jumps to 6.
    _, interval = sm2_update(ease=2.5, interval_days=1, quality=1.0)
    assert interval == 6


def test_third_pass_multiplies_by_ease():
    # interval=6, ease=2.5 → 6 * 2.5 = 15
    _, interval = sm2_update(ease=2.5, interval_days=6, quality=1.0)
    assert interval == 15


def test_low_quality_resets_streak():
    _, interval = sm2_update(ease=2.5, interval_days=10, quality=0.3)
    assert interval == 1


def test_low_quality_decreases_ease():
    ease, _ = sm2_update(ease=2.5, interval_days=10, quality=0.3)
    assert ease < 2.5


def test_ease_clamped_min():
    ease, _ = sm2_update(ease=1.4, interval_days=10, quality=0.0)
    assert ease >= 1.3


def test_ease_clamped_max():
    ease, _ = sm2_update(ease=2.9, interval_days=10, quality=1.0)
    assert ease <= 3.0


@pytest.mark.parametrize("q", [-0.5, 1.5, 999.0, -10])
def test_quality_clamped_to_unit_interval(q: float):
    sm2_update(ease=2.5, interval_days=0, quality=q)  # must not raise
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_sm2.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Create `backend/app/services/sm2.py`:

```python
"""Spaced-repetition scheduler — SM-2 variant.

Inputs:
    ease         : ease factor, clamped to [1.3, 3.0].
    interval_days: 0 for first pass, otherwise prior interval.
    quality      : 0.0..1.0 from the Feynman grader.

Output:
    (new_ease, new_interval_days)

We map quality to SuperMemo's 0..5 grade by `q5 = round(quality * 5)`.
A 0..1 score below 0.6 (i.e. q5 < 3) is treated as a "lapse": interval
resets to 1 day and ease shrinks. Otherwise the classic SM-2 schedule
applies: 1 → 6 → prior * ease.
"""
EASE_MIN = 1.3
EASE_MAX = 3.0


def sm2_update(*, ease: float, interval_days: int, quality: float) -> tuple[float, int]:
    q = max(0.0, min(1.0, quality))
    q5 = round(q * 5)

    if q5 < 3:
        new_ease = max(EASE_MIN, ease - 0.20)
        new_interval = 1
        return new_ease, new_interval

    delta = 0.1 - (5 - q5) * (0.08 + (5 - q5) * 0.02)
    new_ease = max(EASE_MIN, min(EASE_MAX, ease + delta))

    if interval_days <= 0:
        new_interval = 1
    elif interval_days == 1:
        new_interval = 6
    else:
        new_interval = round(interval_days * new_ease)

    return new_ease, new_interval
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_sm2.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sm2.py backend/tests/test_sm2.py
git commit -m "feat(scheduler): SM-2 pure function with ease clamping and lapse reset"
```

---

## Task 6: `ReviewItem` model + migration

**Files:**
- Create: `backend/app/models/review_item.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/<rev>_review_item.py`
- Test: `backend/tests/test_review_item_model.py`

**Context:** One row per `(user_id, concept_id, embed_dim)`. Stores SM-2 state plus `due_at`. `last_session_id` references `feynman_session.id` (nullable, SET NULL on cascade).

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_review_item_model.py`:

```python
from app.models import ReviewItem


def test_review_item_columns():
    cols = ReviewItem.__table__.columns.keys()
    for c in (
        "id", "user_id", "concept_id", "embed_dim",
        "ease", "interval_days", "due_at",
        "last_session_id", "last_score",
        "created_at", "updated_at",
    ):
        assert c in cols


def test_review_item_unique_index_on_user_concept_dim():
    """One review_item per (user_id, concept_id, embed_dim) — a uniqueness
    invariant the upsert path will lean on."""
    indexes = {ix.name: ix for ix in ReviewItem.__table__.indexes}
    assert "uq_review_item_user_concept_dim" in indexes
    assert indexes["uq_review_item_user_concept_dim"].unique is True
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_review_item_model.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement model**

Create `backend/app/models/review_item.py`:

```python
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime, Float, ForeignKey, Index, Integer, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReviewItem(Base):
    __tablename__ = "review_item"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    # Concept lives in a dim-sharded table; no FK, service layer enforces.
    concept_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    embed_dim: Mapped[int] = mapped_column(Integer)

    ease: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    last_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("feynman_session.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index(
            "uq_review_item_user_concept_dim",
            "user_id", "concept_id", "embed_dim",
            unique=True,
        ),
        Index(
            "ix_review_item_user_due",
            "user_id", "due_at",
        ),
    )
```

- [ ] **Step 4: Update `__init__.py`**

Append to `backend/app/models/__init__.py`:

```python
from app.models.review_item import ReviewItem
```

- [ ] **Step 5: Generate migration**

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "review_item"
```

Edit the generated file. Strip spurious autogen drops (ivfflat / partial-unique) per the Plan 2/3 pattern. Keep only the `create_table` and the two `create_index` calls. Set `down_revision = "<rev from Task 2>"`.

- [ ] **Step 6: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_review_item_model.py tests/test_migrations.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models backend/alembic/versions backend/tests/test_review_item_model.py
git commit -m "feat(models): review_item with SM-2 state and (user, concept, dim) uniqueness"
```

---

## Task 7: `/feynman/{sid}/end` upserts a `review_item` via SM-2

**Files:**
- Modify: `backend/app/routers/feynman.py`
- Test: extend `backend/tests/test_feynman_router.py`

**Context:** When a session ends with a quality_score, run `sm2_update` on the existing `review_item` for `(user_id, target_concept_id, embed_dim)` (or insert a fresh one with defaults), then commit alongside the `ended_at`/`quality_score` writes.

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_feynman_router.py`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_router.py::test_end_upserts_review_item -v
```

Expected: ReviewItem row not found.

- [ ] **Step 3: Implement upsert**

Edit `backend/app/routers/feynman.py`. Add imports:

```python
from datetime import datetime, timedelta, timezone

from app.models import ReviewItem
from app.services.sm2 import sm2_update
```

In `end(...)`, after the grading line `score = await grade_transcript(gw, msgs)` and before `s.ended_at = ...`, add:

```python
    ri = (
        await db.execute(
            select(ReviewItem).where(
                ReviewItem.user_id == user.id,
                ReviewItem.concept_id == s.target_concept_id,
                ReviewItem.embed_dim == s.embed_dim,
            )
        )
    ).scalar_one_or_none()
    if ri is None:
        new_ease, new_interval = sm2_update(ease=2.5, interval_days=0, quality=score)
        ri = ReviewItem(
            user_id=user.id,
            concept_id=s.target_concept_id,
            embed_dim=s.embed_dim,
            ease=new_ease,
            interval_days=new_interval,
            due_at=datetime.now(timezone.utc) + timedelta(days=new_interval),
            last_session_id=s.id,
            last_score=score,
        )
        db.add(ri)
    else:
        new_ease, new_interval = sm2_update(
            ease=ri.ease, interval_days=ri.interval_days, quality=score,
        )
        ri.ease = new_ease
        ri.interval_days = new_interval
        ri.due_at = datetime.now(timezone.utc) + timedelta(days=new_interval)
        ri.last_session_id = s.id
        ri.last_score = score
```

The single `await db.commit()` already at the end of the handler now persists both the session changes and the review_item upsert atomically.

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_feynman_router.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/feynman.py backend/tests/test_feynman_router.py
git commit -m "feat(scheduler): /feynman end upserts review_item via SM-2"
```

---

## Task 8: `GET /review/due` endpoint

**Files:**
- Create: `backend/app/schemas/review.py`, `backend/app/routers/review.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_review_router.py`

**Context:** List review_items where `due_at <= now`, scoped to the active dim. Each row joins to the concept name so the frontend can render without a second round-trip.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_review_router.py`:

```python
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
                message=types.SimpleNamespace(content=content)))])
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_review_router.py -v
```

Expected: 404 (router not registered).

- [ ] **Step 3: Implement schema**

Create `backend/app/schemas/review.py`:

```python
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class ReviewItemOut(BaseModel):
    id: UUID
    concept_id: UUID
    concept_name: str
    embed_dim: int
    ease: float
    interval_days: int
    due_at: datetime
    last_score: float | None


class ReviewStartIn(BaseModel):
    review_item_id: UUID
```

- [ ] **Step 4: Implement router**

Create `backend/app/routers/review.py`:

```python
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import LLMConfig, ReviewItem, concept_model_for
from app.schemas.review import ReviewItemOut

router = APIRouter(prefix="/review", tags=["review"])


async def _resolve_active_dim(db, user_id) -> int | None:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user_id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    return cfg.embed_dim if cfg else None


@router.get("/due", response_model=list[ReviewItemOut])
async def due(user: CurrentUser, db: DbSession) -> list[ReviewItemOut]:
    dim = await _resolve_active_dim(db, user.id)
    if dim is None:
        raise HTTPException(status_code=400, detail="No active LLM config")

    ConceptM = concept_model_for(dim)
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(ReviewItem).where(
                ReviewItem.user_id == user.id,
                ReviewItem.embed_dim == dim,
                ReviewItem.due_at <= now,
            ).order_by(ReviewItem.due_at)
        )
    ).scalars().all()

    if not rows:
        return []

    cids = [r.concept_id for r in rows]
    concepts = (
        await db.execute(
            select(ConceptM).where(ConceptM.id.in_(cids))
        )
    ).scalars().all()
    name_by_id = {c.id: c.name for c in concepts}

    return [
        ReviewItemOut(
            id=r.id, concept_id=r.concept_id,
            concept_name=name_by_id.get(r.concept_id, "(missing)"),
            embed_dim=r.embed_dim, ease=r.ease,
            interval_days=r.interval_days, due_at=r.due_at,
            last_score=float(r.last_score) if r.last_score is not None else None,
        )
        for r in rows
    ]
```

- [ ] **Step 5: Register router**

Edit `backend/app/main.py`:

```python
from app.routers import review as review_router
# ...
app.include_router(review_router.router)
```

- [ ] **Step 6: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_review_router.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/review.py backend/app/routers/review.py backend/app/main.py backend/tests/test_review_router.py
git commit -m "feat(api): GET /review/due lists items past due_at with concept names"
```

---

## Task 9: `POST /review/start` opens a scheduled `FeynmanSession`

**Files:**
- Modify: `backend/app/routers/review.py`
- Test: extend `backend/tests/test_review_router.py`

**Context:** Given a `review_item_id`, mint a `FeynmanSession(kind="scheduled", target_concept_id=<item.concept_id>, embed_dim=<item.embed_dim>)`. Returns the new session id so the frontend can `router.push(/feynman/<id>)`.

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_review_router.py`:

```python
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
        items = (await c.get("/review/due", headers=h1))
        # may be empty, but the row exists in DB; fetch it directly
        async with get_sessionmaker()() as db:
            ri = (await db.execute(select(ReviewItem))).scalar_one()
            iid = str(ri.id)

        h2 = await _signup(c)
        r = await c.post("/review/start", json={"review_item_id": iid}, headers=h2)
        assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_review_router.py::test_review_start_creates_scheduled_session -v
```

Expected: 404 / endpoint missing.

- [ ] **Step 3: Implement**

Edit `backend/app/routers/review.py`. Add imports:

```python
from datetime import datetime, timezone

from app.models import FeynmanSession, FeynmanKind
from app.schemas.feynman import FeynmanSessionOut
from app.schemas.review import ReviewStartIn
from app.services.feynman import build_system_prompt
```

Add endpoint:

```python
@router.post("/start", response_model=FeynmanSessionOut, status_code=status.HTTP_201_CREATED)
async def start_review(
    data: ReviewStartIn, user: CurrentUser, db: DbSession,
) -> FeynmanSessionOut:
    item = (
        await db.execute(
            select(ReviewItem).where(
                ReviewItem.id == data.review_item_id,
                ReviewItem.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    ConceptM = concept_model_for(item.embed_dim)
    concept = (
        await db.execute(
            select(ConceptM).where(
                ConceptM.id == item.concept_id, ConceptM.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if concept is None:
        raise HTTPException(status_code=404, detail="Concept not found for review item")

    sys_prompt = build_system_prompt(
        concept_name=concept.name, concept_summary=concept.summary,
    )
    transcript = [{
        "role": "system",
        "content": sys_prompt,
        "ts": datetime.now(timezone.utc).isoformat(),
    }]
    session = FeynmanSession(
        user_id=user.id,
        paper_id=None,
        target_concept_id=concept.id,
        kind=FeynmanKind.scheduled,
        embed_dim=item.embed_dim,
        transcript=transcript,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return FeynmanSessionOut(
        id=session.id, user_id=session.user_id, paper_id=session.paper_id,
        target_concept_id=session.target_concept_id, kind=session.kind.value,
        started_at=session.started_at, ended_at=session.ended_at,
        quality_score=None,
        transcript=[t for t in session.transcript if t["role"] != "system"],
    )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_review_router.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/review.py backend/tests/test_review_router.py
git commit -m "feat(api): POST /review/start opens a scheduled Feynman session"
```

---

## Task 10: `GET /dashboard` endpoint

**Files:**
- Create: `backend/app/schemas/dashboard.py`, `backend/app/routers/dashboard.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_dashboard_router.py`

**Context:** Returns `{concept_count, sessions: [{started_at, quality_score}]}`. Concept count is scoped to active dim. Sessions are the most-recent 30, ended only, ordered desc.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_dashboard_router.py`:

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
        # No active config — endpoint should still respond, but with zero counts.
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_dashboard_router.py -v
```

Expected: 404.

- [ ] **Step 3: Implement schema**

Create `backend/app/schemas/dashboard.py`:

```python
from datetime import datetime
from pydantic import BaseModel


class SessionScorePoint(BaseModel):
    started_at: datetime
    quality_score: float


class DashboardOut(BaseModel):
    concept_count: int
    sessions: list[SessionScorePoint]
```

- [ ] **Step 4: Implement router**

Create `backend/app/routers/dashboard.py`:

```python
from fastapi import APIRouter
from sqlalchemy import select, func

from app.deps import CurrentUser, DbSession
from app.models import FeynmanSession, LLMConfig, concept_model_for
from app.schemas.dashboard import DashboardOut, SessionScorePoint

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_RECENT_SESSIONS_LIMIT = 30


async def _resolve_active_dim(db, user_id) -> int | None:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user_id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    return cfg.embed_dim if cfg else None


@router.get("", response_model=DashboardOut)
async def dashboard(user: CurrentUser, db: DbSession) -> DashboardOut:
    dim = await _resolve_active_dim(db, user.id)
    concept_count = 0
    if dim is not None:
        ConceptM = concept_model_for(dim)
        concept_count = (
            await db.execute(
                select(func.count()).select_from(ConceptM)
                .where(ConceptM.user_id == user.id)
            )
        ).scalar() or 0

    rows = (
        await db.execute(
            select(FeynmanSession)
            .where(
                FeynmanSession.user_id == user.id,
                FeynmanSession.ended_at.is_not(None),
                FeynmanSession.quality_score.is_not(None),
            )
            .order_by(FeynmanSession.started_at.desc())
            .limit(_RECENT_SESSIONS_LIMIT)
        )
    ).scalars().all()

    sessions = [
        SessionScorePoint(
            started_at=r.started_at,
            quality_score=float(r.quality_score),
        )
        for r in rows
    ]
    return DashboardOut(concept_count=concept_count, sessions=sessions)
```

- [ ] **Step 5: Register router**

Edit `backend/app/main.py`:

```python
from app.routers import dashboard as dashboard_router
# ...
app.include_router(dashboard_router.router)
```

- [ ] **Step 6: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_dashboard_router.py -v
cd backend && .venv/bin/pytest -q
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/dashboard.py backend/app/routers/dashboard.py backend/app/main.py backend/tests/test_dashboard_router.py
git commit -m "feat(api): GET /dashboard returns concept count and recent session scores"
```

---

## Task 11: Frontend `/review` page

**Files:**
- Create: `frontend/app/pages/review/index.vue`
- Modify: `frontend/app/layouts/default.vue`

**Context:** List due items, with a "Start review" button per row that POSTs `/review/start` and routes to the new `/feynman/[sid]`.

- [ ] **Step 1: Add nav link**

Edit `frontend/app/layouts/default.vue`. After the Papers link (auth-only), add:

```vue
<NuxtLink v-if="auth.isLoggedIn" to="/review">Review</NuxtLink>
<NuxtLink v-if="auth.isLoggedIn" to="/dashboard">Dashboard</NuxtLink>
```

- [ ] **Step 2: Create page**

Create `frontend/app/pages/review/index.vue`:

```vue
<template>
  <div class="max-w-3xl mx-auto space-y-6">
    <h1 class="text-xl font-semibold">Review queue</h1>
    <p v-if="!items.length" class="text-sm text-neutral-500">Nothing due. Come back later.</p>
    <ul v-else class="space-y-2">
      <li v-for="it in items" :key="it.id"
          class="flex items-center justify-between border border-neutral-200 dark:border-neutral-800 rounded px-3 py-2">
        <div>
          <div class="font-medium">{{ it.concept_name }}</div>
          <div class="text-xs text-neutral-500">
            due {{ new Date(it.due_at).toLocaleString() }} ·
            interval {{ it.interval_days }}d ·
            ease {{ it.ease.toFixed(2) }} ·
            last score {{ it.last_score?.toFixed(2) ?? "—" }}
          </div>
        </div>
        <button @click="start(it.id)" :disabled="starting === it.id"
                class="rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2 text-sm">
          {{ starting === it.id ? "starting…" : "Start review" }}
        </button>
      </li>
    </ul>
    <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
type Item = {
  id: string; concept_id: string; concept_name: string;
  embed_dim: number; ease: number; interval_days: number;
  due_at: string; last_score: number | null;
}
const { call } = useApi()
const router = useRouter()
const items = ref<Item[]>([])
const starting = ref("")
const error = ref("")

async function refresh() { items.value = await call<Item[]>("/review/due") }
onMounted(refresh)

async function start(id: string) {
  error.value = ""; starting.value = id
  try {
    const r = await call<{ id: string }>("/review/start", {
      method: "POST",
      body: JSON.stringify({ review_item_id: id }),
    })
    await router.push(`/feynman/${r.id}`)
  } catch (e: any) {
    error.value = e?.message || "start failed"
  } finally { starting.value = "" }
}
</script>
```

- [ ] **Step 3: Build**

```bash
cd frontend && npm run build
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/pages/review/index.vue frontend/app/layouts/default.vue
git commit -m "feat(frontend): /review page with due queue + start CTA"
```

---

## Task 12: Frontend `/dashboard` page

**Files:**
- Create: `frontend/app/pages/dashboard.vue`

**Context:** A concept-count tile + a table of (date, score) for recent sessions. No chart library; v1 ships a sortable table.

- [ ] **Step 1: Implement**

Create `frontend/app/pages/dashboard.vue`:

```vue
<template>
  <div class="max-w-3xl mx-auto space-y-6">
    <h1 class="text-xl font-semibold">Dashboard</h1>

    <div class="border border-neutral-200 dark:border-neutral-800 rounded p-4">
      <div class="text-xs uppercase tracking-wide text-neutral-500">Concepts</div>
      <div class="text-3xl font-mono">{{ data?.concept_count ?? "—" }}</div>
    </div>

    <section class="space-y-2">
      <h2 class="font-medium">Recent Feynman sessions</h2>
      <table v-if="data && data.sessions.length" class="w-full text-sm">
        <thead class="text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr><th class="py-1">When</th><th class="py-1">Score</th></tr>
        </thead>
        <tbody>
          <tr v-for="(s, i) in data.sessions" :key="i" class="border-t border-neutral-200 dark:border-neutral-800">
            <td class="py-1">{{ new Date(s.started_at).toLocaleString() }}</td>
            <td class="py-1 font-mono">{{ s.quality_score.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="text-sm text-neutral-500">No completed sessions yet.</p>
    </section>
  </div>
</template>

<script setup lang="ts">
type DashboardData = {
  concept_count: number
  sessions: { started_at: string; quality_score: number }[]
}
const { call } = useApi()
const data = ref<DashboardData | null>(null)
async function load() { data.value = await call<DashboardData>("/dashboard") }
onMounted(load)
</script>
```

- [ ] **Step 2: Build**

```bash
cd frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/pages/dashboard.vue
git commit -m "feat(frontend): /dashboard page with concept count + score table"
```

---

## Task 13: Playwright e2e for dashboard + review

**Files:**
- Create: `frontend/tests/e2e/dashboard.spec.ts`

**Context:** Stub the backend at the network layer; assert the dashboard tile and review queue render. We don't need to drive a real Feynman roundtrip — that's covered by `feynman.spec.ts`.

- [ ] **Step 1: Write spec**

Create `frontend/tests/e2e/dashboard.spec.ts`:

```ts
import { test, expect } from "@playwright/test"

const unique = () => `u${Date.now()}@test.example`

test("dashboard tile + score table render with stubbed data", async ({ page }) => {
  const email = unique()
  const password = "correct horse battery staple"

  await page.goto("/signup")
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button:has-text("Sign up")')
  await expect(page.getByText(`Welcome, ${email}`)).toBeVisible()

  await page.route("**/dashboard", async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        concept_count: 17,
        sessions: [
          { started_at: "2026-04-25T10:00:00Z", quality_score: 0.78 },
          { started_at: "2026-04-24T10:00:00Z", quality_score: 0.62 },
        ],
      }),
    })
  })

  await page.goto("/dashboard")
  await expect(page.getByText("Dashboard")).toBeVisible()
  await expect(page.getByText("17", { exact: true })).toBeVisible()
  await expect(page.getByText("0.78")).toBeVisible()
  await expect(page.getByText("0.62")).toBeVisible()
})


test("review page lists due items and start button routes to feynman", async ({ page }) => {
  const email = unique()
  const password = "correct horse battery staple"

  await page.goto("/signup")
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button:has-text("Sign up")')
  await expect(page.getByText(`Welcome, ${email}`)).toBeVisible()

  const itemId = "00000000-0000-0000-0000-000000000010"
  const sid = "00000000-0000-0000-0000-000000000020"

  await page.route("**/review/due", async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify([{
        id: itemId, concept_id: "c1", concept_name: "Self-attention",
        embed_dim: 1536, ease: 2.5, interval_days: 1,
        due_at: new Date().toISOString(), last_score: 0.7,
      }]),
    })
  })
  await page.route("**/review/start", async (route) => {
    await route.fulfill({
      status: 201, contentType: "application/json",
      body: JSON.stringify({
        id: sid, user_id: "u", paper_id: null,
        target_concept_id: "c1", kind: "scheduled",
        started_at: new Date().toISOString(), ended_at: null,
        quality_score: null, transcript: [],
      }),
    })
  })
  await page.route(`**/feynman/${sid}`, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        id: sid, user_id: "u", paper_id: null,
        target_concept_id: "c1", kind: "scheduled",
        started_at: new Date().toISOString(), ended_at: null,
        quality_score: null, transcript: [],
      }),
    })
  })

  await page.goto("/review")
  await expect(page.getByText("Review queue")).toBeVisible()
  await expect(page.getByText("Self-attention")).toBeVisible()
  await page.click('button:has-text("Start review")')
  await expect(page).toHaveURL(new RegExp(`/feynman/${sid}$`))
})
```

- [ ] **Step 2: Run**

```bash
cd frontend && npm run test:e2e
```

Expected: 5 tests pass (foundation, papers, feynman, dashboard, review-start).

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/dashboard.spec.ts
git commit -m "test(frontend): Playwright e2e for dashboard and review queue"
```

---

## Task 14: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update sections**

Edit `README.md`:

- Add `Plan 4 (scheduler + dashboard): docs/superpowers/plans/2026-04-27-scheduler-dashboard.md` to the plans list.
- Under "What's live", add a new **Plan 4 (scheduler + dashboard)** section describing:
  - `GET /review/due`, `POST /review/start`.
  - `GET /dashboard`.
  - SM-2 spaced-repetition; `review_item` table; `feynman_session.embed_dim` pinned at start.
  - Frontend: `/review` queue, `/dashboard` count + score table.
  - Plan 3 reviewer carries: streaming endpoint uses self-managed session, transcript size cap, `(user_id, started_at desc)` index, idempotency-test fix.
- Update "What's next" to summarise v1 completeness and point to v2 candidates: concept-map UI, edge-curation UI, atom flashcards, OCR.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README reflects scheduler + dashboard; v1 feature-complete"
```

---

## Self-Review Checklist

**Spec coverage (§3 v1 items handled by Plan 4):**
- [x] Scheduled Feynman session via SM-2 — Tasks 5, 6, 7, 9
- [x] `/review/due` queue — Task 8
- [x] Dashboard: concept count + Feynman quality-score trend — Tasks 10, 12
- [x] Frontend review + dashboard pages + nav — Tasks 11, 12

**Plan 3 reviewer carries handled:**
- [x] Streaming `/message` self-managed session — Task 1
- [x] `feynman_session.embed_dim` pinned + `(user_id, started_at desc)` index — Task 2
- [x] Transcript size cap — Task 3
- [x] `test_concept_match_is_case_insensitive` off-by-one — Task 4

**Out of scope (v2+):** dim-transition migrator, concept-map UI, atom-card flashcards, OCR. All flagged in spec §9.

**Type / signature consistency:**
- `sm2_update(*, ease, interval_days, quality) -> (ease, interval_days)` — Task 5 + Task 7 call site identical kwargs.
- `concept_model_for(dim)` — Tasks 8, 9, 10 use it identically.
- `ReviewItemOut` shape consistent: Task 8 emits, Task 11 frontend consumes.
- `DashboardOut` shape consistent: Task 10 emits, Task 12 frontend consumes.
- `FeynmanSessionOut` shape consistent: Task 9 returns it, frontend re-uses Plan 3's typing.

**Sequencing:**
- Tasks 1, 2, 3, 4 are independent of each other.
- Task 5 (SM-2) is prereq for Task 7 (end upserts).
- Task 6 (ReviewItem model) is prereq for Tasks 7, 8, 9.
- Task 2 (pin embed_dim on session) is prereq for Task 7 (uses `s.embed_dim`).
- Task 8 (`/review/due`) is prereq for Task 9 (extends same router).
- Task 9 is prereq for Task 11 (frontend consumes).
- Task 10 (`/dashboard`) is prereq for Task 12 (frontend consumes).
- Tasks 11 + 12 prereq for Task 13 (Playwright covers both).
- Linear order as written is valid.

**Placeholder scan:** none.
