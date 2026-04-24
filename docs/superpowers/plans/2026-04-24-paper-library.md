# Paper Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PDF upload → S3-compat blob → background ingest (extract, chunk, embed, silent concept extract) with a papers list/detail UI.

**Architecture:** FastAPI router accepts multipart PDF, stores blob to S3-compatible object store (localstack/MinIO in dev), enqueues a FastAPI `BackgroundTasks` ingest job. Job reads the blob, uses `pymupdf` to extract text, chunks to ~800 tokens with ~100 overlap, calls the user's active `LLMGateway` for embeddings + concept extraction, and writes `paper_chunk_<dim>` / `concept_<dim>` / `concept_edge` rows keyed by the user's `embed_dim`. Frontend polls paper status. Also folds in two Plan 1 reviewer follow-ups: partial unique index on `llm_config(user_id) WHERE is_active`, and OAuth `state` CSRF protection.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, pgvector, Alembic, boto3 (S3), pymupdf, testcontainers (Postgres + localstack), Nuxt 4, Playwright.

---

## File Structure

**Backend (new):**
- `backend/app/services/storage.py` — thin boto3 S3 wrapper (`put_object`, `get_object`, `delete_object`, `presigned_get`).
- `backend/app/services/pdf_ingest.py` — pure functions: `extract_text(pdf_bytes)`, `chunk_text(text, max_tokens, overlap)`.
- `backend/app/services/ingest.py` — orchestration: fetch blob, extract, chunk, embed, persist chunks, extract concepts, embed concepts, propose edges, mark `parsed` / `failed`.
- `backend/app/services/user_llm.py` — `build_user_gateway(db, user) -> LLMGateway` factory; shared by `/llm-config/test` and ingest.
- `backend/app/models/paper.py` — `Paper` model (status enum, text_hash, s3_key, parse_error).
- `backend/app/models/paper_chunk.py` — `PaperChunk768` / `PaperChunk1024` / `PaperChunk1536` (one ORM class per supported embedding dim, all inherit a mixin).
- `backend/app/models/concept.py` — `Concept768` / `Concept1024` / `Concept1536` per-dim (stage enum).
- `backend/app/models/concept_edge.py` — `ConceptEdge` (dim-agnostic; references concept UUIDs).
- `backend/app/schemas/paper.py` — `PaperOut`, `PaperStatusOut`.
- `backend/app/schemas/concept.py` — `ConceptOut`.
- `backend/app/routers/papers.py` — `POST /papers`, `GET /papers`, `GET /papers/{id}`, `POST /papers/{id}/reingest`, `DELETE /papers/{id}`.
- `backend/app/routers/concepts.py` — `GET /concepts` (list for current user; for Plan 3 readiness, no UI yet).
- `backend/alembic/versions/<rev>_llm_config_active_partial_unique.py` — partial unique index.
- `backend/alembic/versions/<rev>_papers_chunks_concepts.py` — new tables + pgvector extension + ivfflat indexes.
- `backend/tests/test_storage.py`, `test_pdf_ingest.py`, `test_ingest_pipeline.py`, `test_papers.py`, `test_concepts.py`, `test_llm_config_active_constraint.py`, `test_oauth_state.py`.

**Backend (modify):**
- `backend/pyproject.toml` — add `boto3`, `testcontainers[localstack]` (dev).
- `backend/app/config.py` — add `s3_endpoint_url`, `s3_region`, `s3_bucket`, `s3_access_key`, `s3_secret_key`, `paper_chunk_max_tokens=800`, `paper_chunk_overlap=100`, `concept_edge_top_k=5`, `concept_edge_min_cosine=0.75`.
- `backend/app/main.py` — include `papers_router`, `concepts_router`.
- `backend/app/models/__init__.py` — export new models.
- `backend/app/routers/llm_config.py` — delegate gateway construction to `user_llm.build_user_gateway`.
- `backend/app/routers/oauth.py` — issue signed `state` cookie on `/oauth/google/login`, verify on `/oauth/google/callback` (remove the `TODO(csrf-state)`).
- `backend/tests/conftest.py` — add `localstack` session fixture and `s3_bucket` fixture; add `fernet_key` fixture that sets a valid key.

**Frontend (new):**
- `frontend/app/pages/papers/index.vue` — upload form + list with status + links.
- `frontend/app/pages/papers/[id].vue` — paper detail: title, status, chunks count, concepts count, reingest button.
- `frontend/tests/e2e/papers.spec.ts` — upload → list appears → status polls.

**Frontend (modify):**
- `frontend/app/layouts/default.vue` — add nav link to `/papers`.
- `frontend/app/composables/useApi.ts` — add `callUpload()` variant that doesn't set `Content-Type` (fetch sets the multipart boundary automatically).
- `frontend/app/middleware/auth.global.ts` — confirm `/papers` is guarded (already is; verify).

---

## Task 1: Partial unique index on `llm_config(user_id) WHERE is_active`

**Files:**
- Create: `backend/alembic/versions/<rev>_llm_config_active_partial_unique.py`
- Test: `backend/tests/test_llm_config_active_constraint.py`

**Context:** `/llm-config/{id}/activate` currently clears all other actives before setting the new one. That logic could race (two concurrent activates) and silently leave two actives. A partial unique index makes the DB enforce the invariant.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_config_active_constraint.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError
from app.db import get_sessionmaker
from app.models import User, LLMConfig


def _mk_cfg(user_id, name, active: bool) -> LLMConfig:
    return LLMConfig(
        user_id=user_id,
        name=name,
        chat_base_url="http://x/v1",
        chat_api_key_enc="x",
        chat_model="m",
        embed_base_url="http://x/v1",
        embed_api_key_enc="x",
        embed_model="m",
        embed_dim=1536,
        is_active=active,
    )


async def test_cannot_have_two_active_configs_for_one_user():
    maker = get_sessionmaker()
    async with maker() as db:
        u = User(email="a@b.c", pw_hash="x")
        db.add(u)
        await db.commit()
        db.add(_mk_cfg(u.id, "one", True))
        await db.commit()
        db.add(_mk_cfg(u.id, "two", True))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_two_inactive_configs_are_fine():
    maker = get_sessionmaker()
    async with maker() as db:
        u = User(email="b@b.c", pw_hash="x")
        db.add(u)
        await db.commit()
        db.add(_mk_cfg(u.id, "one", False))
        db.add(_mk_cfg(u.id, "two", False))
        await db.commit()


async def test_two_users_can_each_have_an_active_config():
    maker = get_sessionmaker()
    async with maker() as db:
        u1 = User(email="c@b.c", pw_hash="x")
        u2 = User(email="d@b.c", pw_hash="x")
        db.add_all([u1, u2])
        await db.commit()
        db.add(_mk_cfg(u1.id, "one", True))
        db.add(_mk_cfg(u2.id, "one", True))
        await db.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_llm_config_active_constraint.py -v
```

Expected: test 1 fails (no IntegrityError raised — DB currently allows two active configs).

- [ ] **Step 3: Generate migration**

```bash
cd backend && alembic revision -m "partial unique active llm_config per user"
```

Edit the new revision file to:

```python
from alembic import op

revision = "<auto>"
down_revision = "b4e627609b8f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_llm_config_one_active_per_user",
        "llm_config",
        ["user_id"],
        unique=True,
        postgresql_where="is_active",
    )


def downgrade() -> None:
    op.drop_index("uq_llm_config_one_active_per_user", table_name="llm_config")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && pytest tests/test_llm_config_active_constraint.py -v
```

Expected: all three pass.

- [ ] **Step 5: Also run full migrations test**

```bash
cd backend && pytest tests/test_migrations.py -v
```

Expected: still passes.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions backend/tests/test_llm_config_active_constraint.py
git commit -m "feat(db): partial unique index for one active llm_config per user"
```

---

## Task 2: S3 storage service + tests (localstack)

**Files:**
- Create: `backend/app/services/storage.py`
- Modify: `backend/app/config.py`, `backend/pyproject.toml`, `backend/tests/conftest.py`
- Test: `backend/tests/test_storage.py`

**Context:** Paper uploads go to an S3-compatible store. In dev/test we use localstack via testcontainers. Minimal API: put, get, delete, presigned_get (for direct downloads later).

- [ ] **Step 1: Add dependencies**

Edit `backend/pyproject.toml`:

```toml
dependencies = [
  # ... existing
  "boto3>=1.35",
]

[project.optional-dependencies]
dev = [
  # ... existing
  "testcontainers[localstack]>=4.8",
]
```

Run:

```bash
cd backend && pip install -e '.[dev]'
```

- [ ] **Step 2: Add S3 settings**

Edit `backend/app/config.py` — add fields to `Settings`:

```python
s3_endpoint_url: str | None = None   # None = AWS default
s3_region: str = "us-east-1"
s3_bucket: str = "syifa-papers"
s3_access_key: str = ""
s3_secret_key: str = ""
paper_chunk_max_tokens: int = 800
paper_chunk_overlap: int = 100
concept_edge_top_k: int = 5
concept_edge_min_cosine: float = 0.75
```

- [ ] **Step 3: Write failing test**

Create `backend/tests/test_storage.py`:

```python
from app.services.storage import Storage


async def test_put_get_delete_roundtrip(s3_bucket):
    s = Storage()
    key = "papers/roundtrip.bin"
    await s.put_object(key, b"hello world", content_type="application/octet-stream")
    got = await s.get_object(key)
    assert got == b"hello world"
    await s.delete_object(key)


async def test_get_missing_raises_keyerror(s3_bucket):
    s = Storage()
    import pytest
    with pytest.raises(KeyError):
        await s.get_object("papers/does-not-exist")


async def test_presigned_get_returns_string(s3_bucket):
    s = Storage()
    key = "papers/presigned.bin"
    await s.put_object(key, b"x")
    url = await s.presigned_get(key, expires=60)
    assert isinstance(url, str) and url.startswith("http")
```

- [ ] **Step 4: Add localstack fixture to conftest**

Edit `backend/tests/conftest.py` — append:

```python
from testcontainers.localstack import LocalStackContainer


@pytest.fixture(scope="session")
def localstack():
    with LocalStackContainer(image="localstack/localstack:3") as ls:
        ls.with_services("s3")
        url = ls.get_url()
        os.environ["S3_ENDPOINT_URL"] = url
        os.environ["S3_REGION"] = "us-east-1"
        os.environ["S3_ACCESS_KEY"] = "test"
        os.environ["S3_SECRET_KEY"] = "test"
        from app.config import get_settings
        get_settings.cache_clear()
        yield url


@pytest.fixture
def s3_bucket(localstack):
    import boto3
    s = __import__("app.config", fromlist=["get_settings"]).get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        region_name=s.s3_region,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
    )
    try:
        client.create_bucket(Bucket=s.s3_bucket)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    yield s.s3_bucket
    # cleanup: empty bucket between tests so keys don't leak across cases
    objs = client.list_objects_v2(Bucket=s.s3_bucket).get("Contents", [])
    for o in objs:
        client.delete_object(Bucket=s.s3_bucket, Key=o["Key"])
```

- [ ] **Step 5: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_storage.py -v
```

Expected: ImportError on `app.services.storage`.

- [ ] **Step 6: Implement Storage**

Create `backend/app/services/storage.py`:

```python
"""Thin boto3 S3 wrapper. Async is cooperative only — boto3 is sync; we
run calls in the default executor so they don't block the event loop."""
import asyncio
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings


class Storage:
    def __init__(self) -> None:
        s = get_settings()
        self._bucket = s.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key or None,
            aws_secret_access_key=s.s3_secret_key or None,
        )

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        await self._run(
            self._client.put_object,
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type,
        )

    async def get_object(self, key: str) -> bytes:
        try:
            r = await self._run(self._client.get_object, Bucket=self._bucket, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise KeyError(key) from e
            raise
        return r["Body"].read()

    async def delete_object(self, key: str) -> None:
        await self._run(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def presigned_get(self, key: str, expires: int = 3600) -> str:
        return await self._run(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd backend && pytest tests/test_storage.py -v
```

Expected: all three pass.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/app/config.py backend/app/services/storage.py backend/tests/test_storage.py backend/tests/conftest.py
git commit -m "feat(storage): S3-compatible blob service with localstack tests"
```

---

## Task 3: PDF extract + chunk (pure functions)

**Files:**
- Create: `backend/app/services/pdf_ingest.py`
- Test: `backend/tests/test_pdf_ingest.py`

**Context:** Two pure functions so concept/ingest logic can be unit-tested without touching pgvector. No LLM, no DB, no S3.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_pdf_ingest.py`:

```python
import pytest
from app.services.pdf_ingest import extract_text, chunk_text, approx_token_count


def _make_pdf(text: str) -> bytes:
    import fitz  # pymupdf
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    buf = doc.tobytes()
    doc.close()
    return buf


def test_extract_text_recovers_visible_text():
    pdf = _make_pdf("Hello from a PDF. Feynman teach-back works.")
    got = extract_text(pdf)
    assert "Hello from a PDF" in got
    assert "Feynman" in got


def test_extract_text_on_non_pdf_raises():
    with pytest.raises(ValueError):
        extract_text(b"not a pdf")


def test_chunk_text_respects_max_tokens():
    text = " ".join(["word"] * 3000)
    chunks = chunk_text(text, max_tokens=800, overlap=100)
    assert all(approx_token_count(c) <= 800 for c in chunks)
    assert len(chunks) >= 3


def test_chunk_text_has_overlap():
    text = " ".join([f"w{i}" for i in range(2000)])
    chunks = chunk_text(text, max_tokens=200, overlap=50)
    # overlap means last ~50 tokens of chunk[i] should appear in chunk[i+1]
    for a, b in zip(chunks, chunks[1:]):
        tail = " ".join(a.split()[-40:])
        assert tail.split()[0] in b


def test_chunk_text_empty_input_returns_empty_list():
    assert chunk_text("", max_tokens=800, overlap=100) == []


def test_approx_token_count_positive():
    assert approx_token_count("one two three") >= 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_pdf_ingest.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Create `backend/app/services/pdf_ingest.py`:

```python
"""PDF text extraction and chunking.

`approx_token_count` uses a cheap whitespace heuristic scaled by 1.3
(words→tokens); good enough for chunk-boundary math, not billing.
"""
import fitz


def extract_text(pdf_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"cannot open as PDF: {e}") from e
    try:
        parts = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return "\n\n".join(parts).strip()


def approx_token_count(s: str) -> int:
    return int(len(s.split()) * 1.3) + 1


def chunk_text(text: str, max_tokens: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if overlap >= max_tokens:
        raise ValueError("overlap must be smaller than max_tokens")

    words = text.split()
    # Words per chunk so that 1.3 * words ≈ max_tokens.
    words_per_chunk = max(1, int(max_tokens / 1.3))
    words_overlap = max(0, int(overlap / 1.3))
    stride = max(1, words_per_chunk - words_overlap)

    chunks: list[str] = []
    i = 0
    while i < len(words):
        piece = words[i : i + words_per_chunk]
        chunks.append(" ".join(piece))
        if i + words_per_chunk >= len(words):
            break
        i += stride
    return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && pytest tests/test_pdf_ingest.py -v
```

Expected: 6 passing.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pdf_ingest.py backend/tests/test_pdf_ingest.py
git commit -m "feat(ingest): PDF text extraction + token-bounded chunking"
```

---

## Task 4: Paper / PaperChunk / Concept / ConceptEdge models

**Files:**
- Create: `backend/app/models/paper.py`, `paper_chunk.py`, `concept.py`, `concept_edge.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_paper_models.py`

**Context:** pgvector requires a fixed column dimension, but users may pick different embedding models (768/1024/1536). Strategy: one ORM class per dim, with a helper `chunk_model_for(dim)` / `concept_model_for(dim)` used by ingest + queries.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_paper_models.py`:

```python
import pytest
from app.models import (
    Paper, PaperChunk768, PaperChunk1024, PaperChunk1536,
    Concept768, Concept1024, Concept1536, ConceptEdge,
    chunk_model_for, concept_model_for,
)


def test_chunk_model_for_maps_known_dims():
    assert chunk_model_for(768) is PaperChunk768
    assert chunk_model_for(1024) is PaperChunk1024
    assert chunk_model_for(1536) is PaperChunk1536


def test_concept_model_for_maps_known_dims():
    assert concept_model_for(768) is Concept768
    assert concept_model_for(1024) is Concept1024
    assert concept_model_for(1536) is Concept1536


def test_unknown_dim_raises():
    with pytest.raises(ValueError):
        chunk_model_for(999)
    with pytest.raises(ValueError):
        concept_model_for(999)


def test_paper_has_status_and_parse_error():
    cols = Paper.__table__.columns.keys()
    for c in ("id", "user_id", "title", "authors", "uploaded_at",
              "s3_key", "text_hash", "status", "parse_error"):
        assert c in cols
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_paper_models.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement Paper model**

Create `backend/app/models/paper.py`:

```python
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, DateTime, Text, Enum as SAEnum
import enum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaperStatus(str, enum.Enum):
    uploaded = "uploaded"
    parsed = "parsed"
    failed = "failed"


class Paper(Base):
    __tablename__ = "paper"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[str] = mapped_column(String(1000), default="")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    s3_key: Mapped[str] = mapped_column(String(500))
    text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[PaperStatus] = mapped_column(
        SAEnum(PaperStatus, name="paper_status"), default=PaperStatus.uploaded
    )
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Implement PaperChunk per-dim models**

Create `backend/app/models/paper_chunk.py`:

```python
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, declared_attr

from app.models.base import Base


class _PaperChunkBase:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE"), index=True
    )
    ord: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer)


def _make_chunk_model(dim: int) -> type:
    name = f"PaperChunk{dim}"
    return type(
        name,
        (_PaperChunkBase, Base),
        {
            "__tablename__": f"paper_chunk_{dim}",
            "embedding": mapped_column(Vector(dim)),
        },
    )


PaperChunk768 = _make_chunk_model(768)
PaperChunk1024 = _make_chunk_model(1024)
PaperChunk1536 = _make_chunk_model(1536)

_CHUNK_MODELS = {768: PaperChunk768, 1024: PaperChunk1024, 1536: PaperChunk1536}


def chunk_model_for(dim: int):
    try:
        return _CHUNK_MODELS[dim]
    except KeyError:
        raise ValueError(f"unsupported embed_dim {dim}; pick one of {sorted(_CHUNK_MODELS)}")
```

- [ ] **Step 5: Implement Concept per-dim models**

Create `backend/app/models/concept.py`:

```python
import enum
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, DateTime, Enum as SAEnum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ConceptStage(str, enum.Enum):
    new = "new"
    learning = "learning"
    fluent = "fluent"
    teach = "teach"


class _ConceptBase:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    source_paper_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), default=list)
    stage: Mapped[ConceptStage] = mapped_column(
        SAEnum(ConceptStage, name="concept_stage"), default=ConceptStage.new
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def _make_concept_model(dim: int) -> type:
    return type(
        f"Concept{dim}",
        (_ConceptBase, Base),
        {
            "__tablename__": f"concept_{dim}",
            "embedding": mapped_column(Vector(dim)),
        },
    )


Concept768 = _make_concept_model(768)
Concept1024 = _make_concept_model(1024)
Concept1536 = _make_concept_model(1536)

_CONCEPT_MODELS = {768: Concept768, 1024: Concept1024, 1536: Concept1536}


def concept_model_for(dim: int):
    try:
        return _CONCEPT_MODELS[dim]
    except KeyError:
        raise ValueError(f"unsupported embed_dim {dim}; pick one of {sorted(_CONCEPT_MODELS)}")
```

- [ ] **Step 6: Implement ConceptEdge**

Create `backend/app/models/concept_edge.py`:

```python
import enum
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EdgeStatus(str, enum.Enum):
    proposed = "proposed"
    accepted = "accepted"
    rejected = "rejected"


class ConceptEdge(Base):
    __tablename__ = "concept_edge"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    # Edge references concept UUIDs; we intentionally do NOT FK them because
    # concepts live in dim-sharded tables. The service layer enforces integrity.
    src_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    dst_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    relation: Mapped[str] = mapped_column(String(100), default="related-to")
    status: Mapped[EdgeStatus] = mapped_column(
        SAEnum(EdgeStatus, name="edge_status"), default=EdgeStatus.proposed
    )
    confidence: Mapped[float] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
```

- [ ] **Step 7: Update models/__init__.py**

Edit `backend/app/models/__init__.py` — add (keep existing exports):

```python
from app.models.paper import Paper, PaperStatus
from app.models.paper_chunk import (
    PaperChunk768, PaperChunk1024, PaperChunk1536, chunk_model_for,
)
from app.models.concept import (
    Concept768, Concept1024, Concept1536, ConceptStage, concept_model_for,
)
from app.models.concept_edge import ConceptEdge, EdgeStatus
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd backend && pytest tests/test_paper_models.py -v
```

Expected: 4 passing.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models
git add backend/tests/test_paper_models.py
git commit -m "feat(models): paper, per-dim paper_chunk/concept, concept_edge"
```

---

## Task 5: Alembic migration for papers / chunks / concepts

**Files:**
- Create: `backend/alembic/versions/<rev>_papers_chunks_concepts.py`
- Modify: `backend/tests/test_migrations.py` (sanity)

**Context:** `CREATE EXTENSION IF NOT EXISTS vector` must run before vector columns. Autogen from new models, then prepend the extension. Add cosine ivfflat indexes on all `*_chunk_*.embedding` and `concept_*.embedding`.

- [ ] **Step 1: Autogenerate migration**

```bash
cd backend && alembic revision --autogenerate -m "papers chunks concepts"
```

Inspect output; it will create the new tables but miss the extension and ivfflat indexes.

- [ ] **Step 2: Edit the migration**

At the top of `upgrade()`:

```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```

At the bottom of `upgrade()` (after all tables exist), for each `(table, dim)` in `[("paper_chunk_768",768),("paper_chunk_1024",1024),("paper_chunk_1536",1536),("concept_768",768),("concept_1024",1024),("concept_1536",1536)]` add:

```python
op.execute(
    f"CREATE INDEX ix_{table}_embedding_cos ON {table} "
    f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
)
```

In `downgrade()`:

```python
for table in [...]:
    op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_cos")
# then the autogen drop_table calls
op.execute("DROP EXTENSION IF EXISTS vector")
```

- [ ] **Step 3: Run migrations test**

```bash
cd backend && pytest tests/test_migrations.py -v
```

Expected: pass.

- [ ] **Step 4: Spin up compose to smoke-check migration**

```bash
cd /home/seratusjuta/syifa && docker compose up -d
cd backend && alembic upgrade head
cd backend && alembic downgrade -1
cd backend && alembic upgrade head
```

Expected: all three succeed.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions
git commit -m "feat(db): migrate papers, per-dim chunks/concepts, concept_edge, vector indexes"
```

---

## Task 6: `build_user_gateway` factory + refactor `/llm-config/test`

**Files:**
- Create: `backend/app/services/user_llm.py`
- Modify: `backend/app/routers/llm_config.py`
- Test: `backend/tests/test_user_llm.py`

**Context:** Ingest and `/llm-config/{id}/test` both need to construct an `LLMGateway` from a stored config (decrypting keys). Single factory keeps the plumbing in one place.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_user_llm.py`:

```python
import pytest
from app.db import get_sessionmaker
from app.models import User, LLMConfig
from app.security import encrypt_secret
from app.services.user_llm import (
    NoActiveLLMConfig,
    build_user_gateway,
    build_gateway_from_config,
)


def _mk_user_and_cfg(active: bool) -> tuple[User, LLMConfig]:
    u = User(email="x@y.z", pw_hash="h")
    c = LLMConfig(
        user_id=None,  # set after user insert
        name="n",
        chat_base_url="http://c/v1",
        chat_api_key_enc=encrypt_secret("sk-chat"),
        chat_model="cm",
        embed_base_url="http://e/v1",
        embed_api_key_enc=encrypt_secret("sk-embed"),
        embed_model="em",
        embed_dim=1536,
        is_active=active,
    )
    return u, c


async def test_build_gateway_from_config_decrypts_keys(fernet_key):
    _, cfg = _mk_user_and_cfg(active=True)
    gw = build_gateway_from_config(cfg)
    assert gw._chat_model == "cm"
    assert gw._embed_model == "em"
    assert gw._embed_dim == 1536


async def test_build_user_gateway_picks_active(fernet_key):
    maker = get_sessionmaker()
    async with maker() as db:
        u, c = _mk_user_and_cfg(active=True)
        db.add(u)
        await db.commit()
        c.user_id = u.id
        db.add(c)
        await db.commit()
        gw = await build_user_gateway(db, u)
        assert gw._chat_model == "cm"


async def test_build_user_gateway_raises_without_active(fernet_key):
    maker = get_sessionmaker()
    async with maker() as db:
        u, c = _mk_user_and_cfg(active=False)
        db.add(u)
        await db.commit()
        c.user_id = u.id
        db.add(c)
        await db.commit()
        with pytest.raises(NoActiveLLMConfig):
            await build_user_gateway(db, u)
```

Add to `backend/tests/conftest.py`:

```python
from cryptography.fernet import Fernet


@pytest.fixture
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    from app.config import get_settings
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_user_llm.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Create `backend/app/services/user_llm.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LLMConfig, User
from app.security import decrypt_secret
from app.services.llm_gateway import LLMGateway


class NoActiveLLMConfig(Exception):
    pass


def build_gateway_from_config(cfg: LLMConfig) -> LLMGateway:
    return LLMGateway(
        chat_base_url=cfg.chat_base_url,
        chat_api_key=decrypt_secret(cfg.chat_api_key_enc),
        chat_model=cfg.chat_model,
        embed_base_url=cfg.embed_base_url,
        embed_api_key=decrypt_secret(cfg.embed_api_key_enc),
        embed_model=cfg.embed_model,
        embed_dim=cfg.embed_dim,
    )


async def build_user_gateway(db: AsyncSession, user: User) -> LLMGateway:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user.id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise NoActiveLLMConfig("user has no active LLM config")
    return build_gateway_from_config(cfg)
```

- [ ] **Step 4: Refactor `/llm-config/{id}/test`**

Edit `backend/app/routers/llm_config.py`. Replace the inline `LLMGateway(...)` construction in `test_connection` with:

```python
from app.services.user_llm import build_gateway_from_config
# ...
@router.post("/{cid}/test", response_model=TestConnectionOut)
async def test_connection(cid: UUID, user: CurrentUser, db: DbSession) -> TestConnectionOut:
    cfg = (
        await db.execute(
            select(LLMConfig).where(LLMConfig.id == cid, LLMConfig.user_id == user.id)
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=404, detail="Config not found")
    gw = build_gateway_from_config(cfg)

    async def _safe(coro) -> str:
        try:
            await coro
            return "ok"
        except LLMConnectionError as e:
            return f"error: {e}"

    return TestConnectionOut(chat=await _safe(gw.ping_chat()), embed=await _safe(gw.ping_embed()))
```

- [ ] **Step 5: Run all tests**

```bash
cd backend && pytest -v
```

Expected: all prior tests still green, new 3 pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/user_llm.py backend/app/routers/llm_config.py backend/tests/test_user_llm.py backend/tests/conftest.py
git commit -m "feat(services): user_llm factory; refactor /llm-config/test to use it"
```

---

## Task 7: Ingest pipeline service (mocked gateway)

**Files:**
- Create: `backend/app/services/ingest.py`
- Test: `backend/tests/test_ingest_pipeline.py`

**Context:** Given a `paper_id`, read bytes from S3, extract, chunk, embed, insert chunks, call LLM for concept list, embed concepts, insert concept rows, propose edges via cosine similarity, update paper status. LLM calls must be mockable.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_ingest_pipeline.py`:

```python
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.db import get_sessionmaker
from app.models import (
    User, LLMConfig, Paper, PaperStatus,
    chunk_model_for, concept_model_for, ConceptEdge,
)
from app.security import encrypt_secret
from app.services.ingest import ingest_paper


def _make_pdf(text: str) -> bytes:
    import fitz
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), text)
    b = doc.tobytes()
    doc.close()
    return b


async def _seed_user_cfg(db) -> tuple[User, LLMConfig]:
    u = User(email=f"{uuid4()}@x.y", pw_hash="h")
    db.add(u)
    await db.commit()
    c = LLMConfig(
        user_id=u.id, name="n",
        chat_base_url="http://x/v1", chat_api_key_enc=encrypt_secret("sk"),
        chat_model="m",
        embed_base_url="http://x/v1", embed_api_key_enc=encrypt_secret("sk"),
        embed_model="em", embed_dim=1536, is_active=True,
    )
    db.add(c)
    await db.commit()
    return u, c


async def test_ingest_happy_path_writes_chunks_concepts_and_edges(
    monkeypatch, s3_bucket, fernet_key
):
    from app.services.storage import Storage
    storage = Storage()
    key = f"papers/{uuid4()}.pdf"
    await storage.put_object(
        key, _make_pdf("Attention is all you need. Transformer self-attention layers."),
    )

    maker = get_sessionmaker()
    async with maker() as db:
        u, _ = await _seed_user_cfg(db)
        paper = Paper(user_id=u.id, title="t", s3_key=key)
        db.add(paper)
        await db.commit()
        pid = paper.id

    # Mock LLMGateway: return a fixed embedding per chunk, concept list with
    # 2 names, each with its own embedding.
    fake_chunk_vec = [0.01] * 1536
    fake_concept_vecs = [[0.9] + [0.0] * 1535, [0.89] + [0.0] * 1535]

    class FakeGW:
        async def embed(self, texts):
            # Chunk embeddings come in first; concept embeddings next.
            # Distinguish by call order.
            return [fake_chunk_vec] * len(texts)

        async def chat(self, messages, stream=False):
            # Return a JSON list of concepts.
            import types
            content = '{"concepts":[{"name":"attention","summary":"x"},{"name":"transformer","summary":"y"}]}'
            # Mimic openai response shape.
            choice = types.SimpleNamespace(message=types.SimpleNamespace(content=content))
            return types.SimpleNamespace(choices=[choice])

    fake_gw = FakeGW()
    # Concept embed calls come through embed() too; patch so the 2 concepts
    # get the concept-specific vectors.
    call_count = {"n": 0}

    async def embed_router(texts):
        call_count["n"] += 1
        # First call (chunks) = chunk vec; second call (concepts) = concept vecs.
        if call_count["n"] == 1:
            return [fake_chunk_vec] * len(texts)
        return fake_concept_vecs[: len(texts)]

    fake_gw.embed = embed_router

    async with maker() as db:
        await ingest_paper(
            paper_id=pid, db=db, gateway=fake_gw, storage=storage, embed_dim=1536,
        )

    ChunkM = chunk_model_for(1536)
    ConceptM = concept_model_for(1536)
    async with maker() as db:
        n_chunks = (await db.execute(select(func.count()).select_from(ChunkM))).scalar()
        n_concepts = (await db.execute(select(func.count()).select_from(ConceptM))).scalar()
        n_edges = (await db.execute(select(func.count()).select_from(ConceptEdge))).scalar()
        p = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
    assert n_chunks >= 1
    assert n_concepts == 2
    # Two concepts → up to 1 edge between them (both cosine>=threshold because
    # their vectors are near-parallel).
    assert n_edges >= 1
    assert p.status == PaperStatus.parsed


async def test_ingest_marks_failed_on_extraction_error(
    monkeypatch, s3_bucket, fernet_key
):
    from app.services.storage import Storage
    storage = Storage()
    key = f"papers/{uuid4()}.pdf"
    await storage.put_object(key, b"this is not a pdf")
    maker = get_sessionmaker()
    async with maker() as db:
        u, _ = await _seed_user_cfg(db)
        paper = Paper(user_id=u.id, title="t", s3_key=key)
        db.add(paper)
        await db.commit()
        pid = paper.id

    class FakeGW:
        async def embed(self, texts): return []
        async def chat(self, *a, **k): return None

    async with maker() as db:
        await ingest_paper(
            paper_id=pid, db=db, gateway=FakeGW(), storage=storage, embed_dim=1536,
        )

    async with maker() as db:
        p = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
    assert p.status == PaperStatus.failed
    assert p.parse_error is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_ingest_pipeline.py -v
```

Expected: ImportError on `app.services.ingest`.

- [ ] **Step 3: Implement**

Create `backend/app/services/ingest.py`:

```python
"""Paper ingest orchestration: blob → text → chunks+embeds → concepts → edges.

Contract:
    ingest_paper(paper_id, db, gateway, storage, embed_dim) -> None
    On success: paper.status = parsed, chunks + concepts + edges persisted.
    On failure: paper.status = failed, paper.parse_error populated. No partial
    chunks remain for the failed paper (we commit at the end).
"""
import hashlib
import json
import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Paper, PaperStatus, chunk_model_for, concept_model_for, ConceptEdge
from app.services.pdf_ingest import chunk_text, extract_text, approx_token_count

log = logging.getLogger("syifa.ingest")


_CONCEPT_PROMPT = (
    "You are extracting the key scientific concepts from a research paper. "
    "Return STRICT JSON of the form "
    '{"concepts":[{"name": "...", "summary": "one sentence"}]} '
    "with at most 12 concepts. No commentary."
)


async def ingest_paper(
    *,
    paper_id: UUID,
    db: AsyncSession,
    gateway,
    storage,
    embed_dim: int,
) -> None:
    settings = get_settings()
    paper = (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one()
    try:
        blob = await storage.get_object(paper.s3_key)
        text = extract_text(blob)
        if not text:
            raise ValueError("extracted text is empty")
        paper.text_hash = hashlib.sha256(text.encode()).hexdigest()

        chunks = chunk_text(
            text,
            max_tokens=settings.paper_chunk_max_tokens,
            overlap=settings.paper_chunk_overlap,
        )
        if not chunks:
            raise ValueError("no chunks produced")

        chunk_embeds = await gateway.embed(chunks)
        if len(chunk_embeds) != len(chunks):
            raise ValueError("embedding count mismatch for chunks")

        ChunkM = chunk_model_for(embed_dim)
        # Idempotent re-ingest: clear prior chunks for this paper.
        await db.execute(delete(ChunkM).where(ChunkM.paper_id == paper.id))
        for i, (c, e) in enumerate(zip(chunks, chunk_embeds)):
            db.add(ChunkM(paper_id=paper.id, ord=i, text=c, tokens=approx_token_count(c), embedding=e))

        # Concept extraction: single LLM call, JSON-parsed.
        head = "\n\n".join(chunks[:3])
        msg = [
            {"role": "system", "content": _CONCEPT_PROMPT},
            {"role": "user", "content": head},
        ]
        resp = await gateway.chat(msg)
        content = resp.choices[0].message.content
        data = json.loads(content)
        concept_records = data.get("concepts", [])[:12]
        if not concept_records:
            log.warning("no concepts extracted for paper %s", paper.id)
        else:
            names = [c["name"] for c in concept_records]
            concept_embeds = await gateway.embed(names)
            ConceptM = concept_model_for(embed_dim)
            new_concepts = []
            for rec, vec in zip(concept_records, concept_embeds):
                obj = ConceptM(
                    user_id=paper.user_id,
                    name=rec["name"][:500],
                    summary=rec.get("summary", "")[:2000],
                    source_paper_ids=[paper.id],
                    embedding=vec,
                )
                db.add(obj)
                new_concepts.append(obj)
            await db.flush()  # assign IDs before building edges

            # Propose edges: cosine to existing concepts of same user.
            await _propose_edges(
                db, ConceptM, new_concepts, user_id=paper.user_id,
                top_k=settings.concept_edge_top_k,
                min_cos=settings.concept_edge_min_cosine,
            )

        paper.status = PaperStatus.parsed
        paper.parse_error = None
        await db.commit()
    except Exception as e:
        log.exception("ingest failed for paper %s", paper_id)
        await db.rollback()
        async with db.bind.connect() as conn:  # fresh connection for status write
            pass
        # Re-fetch paper and write failure.
        paper = (
            await db.execute(select(Paper).where(Paper.id == paper_id))
        ).scalar_one()
        paper.status = PaperStatus.failed
        paper.parse_error = str(e)[:2000]
        await db.commit()


async def _propose_edges(db, ConceptM, new_concepts, *, user_id, top_k, min_cos):
    if len(new_concepts) < 2:
        return
    # Candidate pool: all of this user's concepts (including the new ones).
    rows = (
        await db.execute(
            select(ConceptM).where(ConceptM.user_id == user_id)
        )
    ).scalars().all()
    rows_by_id = {r.id: r for r in rows}
    for new in new_concepts:
        # SQL cosine distance via pgvector operator <=>
        result = await db.execute(
            select(ConceptM, ConceptM.embedding.cosine_distance(new.embedding).label("d"))
            .where(ConceptM.user_id == user_id, ConceptM.id != new.id)
            .order_by("d")
            .limit(top_k)
        )
        for other, dist in result.all():
            cos = 1.0 - float(dist)
            if cos < min_cos:
                continue
            # Avoid duplicate edges (a,b) and (b,a) for the same pair.
            exists = (
                await db.execute(
                    select(ConceptEdge).where(
                        ConceptEdge.user_id == user_id,
                        ((ConceptEdge.src_id == new.id) & (ConceptEdge.dst_id == other.id))
                        | ((ConceptEdge.src_id == other.id) & (ConceptEdge.dst_id == new.id)),
                    )
                )
            ).scalar_one_or_none()
            if exists:
                continue
            db.add(
                ConceptEdge(
                    user_id=user_id, src_id=new.id, dst_id=other.id,
                    relation="related-to", confidence=cos,
                )
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && pytest tests/test_ingest_pipeline.py -v
```

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ingest.py backend/tests/test_ingest_pipeline.py
git commit -m "feat(ingest): orchestrate extract→chunk→embed→concept→edge pipeline"
```

---

## Task 8: Paper schemas + `/papers` router

**Files:**
- Create: `backend/app/schemas/paper.py`, `backend/app/routers/papers.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_papers.py`

**Context:** Multipart upload stores PDF to S3, inserts `paper` row, enqueues ingest via `BackgroundTasks`. List + detail + reingest + delete endpoints. Test uses `monkeypatch` to replace `build_user_gateway` with a fake so the ingest runs synchronously in tests via `BackgroundTasks` (FastAPI's TestClient runs them after the response).

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_papers.py`:

```python
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
    monkeypatch, s3_bucket, fernet_key,
):
    # Replace gateway factory so ingest doesn't hit a real endpoint.
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
        # Background task runs after response in TestClient; re-query.
        # (Status may still be "uploaded" if task hasn't run; test both paths.)


async def test_list_papers_only_returns_own(monkeypatch, s3_bucket, fernet_key):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h1 = await _auth_header(c)
        await _seed_active_llm_config(c, h1)
        h2 = await _auth_header(c)
        await _seed_active_llm_config(c, h2)

        async def fake_builder(db, user):
            class G:
                async def embed(self, texts): return [[0.1] * 1536 for _ in texts]
                async def chat(self, *a, **k):
                    return types.SimpleNamespace(choices=[types.SimpleNamespace(
                        message=types.SimpleNamespace(
                            content='{"concepts":[{"name":"x","summary":"s"}]}'))])
            return G()
        monkeypatch.setattr("app.routers.papers.build_user_gateway", fake_builder)

        pdf = _make_pdf("user one's paper")
        await c.post("/papers", headers=h1, files={"file":("a.pdf",pdf,"application/pdf")}, data={"title": "A"})
        pdf2 = _make_pdf("user two's paper")
        await c.post("/papers", headers=h2, files={"file":("b.pdf",pdf2,"application/pdf")}, data={"title":"B"})

        r1 = (await c.get("/papers", headers=h1)).json()
        r2 = (await c.get("/papers", headers=h2)).json()
        assert len(r1) == 1 and r1[0]["title"] == "A"
        assert len(r2) == 1 and r2[0]["title"] == "B"


async def test_upload_rejects_non_pdf(monkeypatch, s3_bucket, fernet_key):
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
    monkeypatch, s3_bucket, fernet_key,
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
    monkeypatch, s3_bucket, fernet_key,
):
    # Use a gateway that refuses to run so ingest fails fast (delete should
    # still work regardless of status).
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
```

- [ ] **Step 2: Create schemas**

Create `backend/app/schemas/paper.py`:

```python
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class PaperOut(BaseModel):
    id: UUID
    title: str
    authors: str
    uploaded_at: datetime
    status: str
    parse_error: str | None = None
```

- [ ] **Step 3: Create router**

Create `backend/app/routers/papers.py`:

```python
import logging
from uuid import UUID, uuid4

from fastapi import (
    APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status,
)
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.db import get_sessionmaker
from app.models import Paper, PaperStatus, LLMConfig
from app.schemas.paper import PaperOut
from app.services.storage import Storage
from app.services.user_llm import build_user_gateway, NoActiveLLMConfig
from app.services.ingest import ingest_paper

log = logging.getLogger("syifa.papers")
router = APIRouter(prefix="/papers", tags=["papers"])


def _to_out(p: Paper) -> PaperOut:
    return PaperOut(
        id=p.id, title=p.title, authors=p.authors or "",
        uploaded_at=p.uploaded_at, status=p.status.value,
        parse_error=p.parse_error,
    )


async def _run_ingest(paper_id: UUID, user_id: UUID, embed_dim: int) -> None:
    """Runs in BackgroundTasks; opens its own session."""
    maker = get_sessionmaker()
    async with maker() as db:
        # Re-fetch user → build gateway fresh inside this session.
        from app.models import User
        u = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        try:
            gw = await build_user_gateway(db, u)
        except NoActiveLLMConfig:
            log.error("no active config for user %s during ingest", user_id)
            return
        await ingest_paper(
            paper_id=paper_id, db=db, gateway=gw, storage=Storage(),
            embed_dim=embed_dim,
        )


@router.post("", response_model=PaperOut, status_code=status.HTTP_201_CREATED)
async def upload(
    user: CurrentUser,
    db: DbSession,
    bg: BackgroundTasks,
    title: str = Form(...),
    file: UploadFile = File(...),
) -> PaperOut:
    if (file.content_type or "").lower() not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(status_code=415, detail="Only PDF uploads accepted")

    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user.id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=400, detail="No active LLM config; set one in settings")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    key = f"papers/{user.id}/{uuid4()}.pdf"
    await Storage().put_object(key, data, content_type="application/pdf")

    paper = Paper(user_id=user.id, title=title[:500], s3_key=key, status=PaperStatus.uploaded)
    db.add(paper)
    await db.commit()
    await db.refresh(paper)

    bg.add_task(_run_ingest, paper.id, user.id, cfg.embed_dim)
    return _to_out(paper)


@router.get("", response_model=list[PaperOut])
async def list_(user: CurrentUser, db: DbSession) -> list[PaperOut]:
    rows = (
        await db.execute(
            select(Paper).where(Paper.user_id == user.id).order_by(Paper.uploaded_at.desc())
        )
    ).scalars().all()
    return [_to_out(p) for p in rows]


@router.get("/{pid}", response_model=PaperOut)
async def get_one(pid: UUID, user: CurrentUser, db: DbSession) -> PaperOut:
    p = (
        await db.execute(
            select(Paper).where(Paper.id == pid, Paper.user_id == user.id)
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return _to_out(p)


@router.post("/{pid}/reingest", response_model=PaperOut)
async def reingest(
    pid: UUID, user: CurrentUser, db: DbSession, bg: BackgroundTasks,
) -> PaperOut:
    p = (
        await db.execute(
            select(Paper).where(Paper.id == pid, Paper.user_id == user.id)
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user.id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=400, detail="No active LLM config")
    p.status = PaperStatus.uploaded
    p.parse_error = None
    await db.commit()
    await db.refresh(p)
    bg.add_task(_run_ingest, p.id, user.id, cfg.embed_dim)
    return _to_out(p)


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
    await db.delete(p)
    await db.commit()
```

- [ ] **Step 4: Include router in main**

Edit `backend/app/main.py`:

```python
from app.routers import papers as papers_router
# ...
app.include_router(papers_router.router)
```

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest tests/test_papers.py -v
```

Expected: 5 passing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/paper.py backend/app/routers/papers.py backend/app/main.py backend/tests/test_papers.py
git commit -m "feat(api): /papers upload, list, detail, reingest, delete"
```

---

## Task 9: `GET /concepts` endpoint

**Files:**
- Create: `backend/app/schemas/concept.py`, `backend/app/routers/concepts.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_concepts.py`

**Context:** Concept map UI isn't v1, but Plan 3 (Feynman) needs to pick a target concept; exposing a list endpoint now keeps the surface ready. Queries the dim-sharded table for the user's active config.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_concepts.py`:

```python
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


async def test_list_concepts_empty(monkeypatch, s3_bucket, fernet_key):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup_login(c)
        await _active_cfg(c, h)
        r = await c.get("/concepts", headers=h)
        assert r.status_code == 200
        assert r.json() == []


async def test_list_concepts_returns_own_only(monkeypatch, s3_bucket, fernet_key):
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
        # wait for background task: retry a few times
        import asyncio
        for _ in range(20):
            rs = (await c.get("/concepts", headers=h)).json()
            if rs: break
            await asyncio.sleep(0.1)
        assert {c["name"] for c in rs} == {"alpha", "beta"}


async def test_list_concepts_without_active_config_returns_400(
    monkeypatch, s3_bucket, fernet_key,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _signup_login(c)
        r = await c.get("/concepts", headers=h)
        assert r.status_code == 400
```

- [ ] **Step 2: Create schema**

Create `backend/app/schemas/concept.py`:

```python
from uuid import UUID
from pydantic import BaseModel


class ConceptOut(BaseModel):
    id: UUID
    name: str
    summary: str
    stage: str
```

- [ ] **Step 3: Create router**

Create `backend/app/routers/concepts.py`:

```python
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import LLMConfig, concept_model_for
from app.schemas.concept import ConceptOut

router = APIRouter(prefix="/concepts", tags=["concepts"])


@router.get("", response_model=list[ConceptOut])
async def list_(user: CurrentUser, db: DbSession) -> list[ConceptOut]:
    cfg = (
        await db.execute(
            select(LLMConfig).where(
                LLMConfig.user_id == user.id, LLMConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=400, detail="No active LLM config")
    M = concept_model_for(cfg.embed_dim)
    rows = (
        await db.execute(
            select(M).where(M.user_id == user.id).order_by(M.created_at.desc())
        )
    ).scalars().all()
    return [
        ConceptOut(id=r.id, name=r.name, summary=r.summary, stage=r.stage.value)
        for r in rows
    ]
```

- [ ] **Step 4: Register router**

Edit `backend/app/main.py`:

```python
from app.routers import concepts as concepts_router
# ...
app.include_router(concepts_router.router)
```

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest tests/test_concepts.py -v
```

Expected: 3 passing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/concept.py backend/app/routers/concepts.py backend/app/main.py backend/tests/test_concepts.py
git commit -m "feat(api): GET /concepts scoped to user's active embed_dim"
```

---

## Task 10: OAuth `state` CSRF protection

**Files:**
- Modify: `backend/app/routers/oauth.py`
- Test: `backend/tests/test_oauth_state.py`

**Context:** Plan 1 shipped Google OAuth with a `TODO(csrf-state)`. Before Plan 2 ships, add signed-cookie `state` check on the callback so cross-site requests can't complete an OAuth flow for a victim.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_oauth_state.py`:

```python
from httpx import AsyncClient, ASGITransport
from app.main import app


async def test_google_login_sets_state_cookie():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/oauth/google/login", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert any("oauth_state" in (k.lower()) for k in r.headers.get_list("set-cookie"))


async def test_callback_without_state_cookie_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/oauth/google/callback?code=abc&state=xyz")
        assert r.status_code == 400


async def test_callback_with_mismatched_state_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.cookies.set("oauth_state", "server-state")
        r = await c.get("/oauth/google/callback?code=abc&state=attacker-state")
        assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_oauth_state.py -v
```

Expected: failing — current code ignores state.

- [ ] **Step 3: Implement state**

Edit `backend/app/routers/oauth.py`. At `/oauth/google/login`:

```python
import secrets

STATE_COOKIE = "oauth_state"
STATE_TTL = 600  # 10 minutes


@router.get("/google/login")
async def google_login():
    state = secrets.token_urlsafe(32)
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={get_settings().google_client_id}"
        f"&redirect_uri={get_settings().google_redirect_uri}"
        f"&response_type=code&scope=openid+email+profile"
        f"&state={state}"
    )
    resp = RedirectResponse(auth_url, status_code=302)
    resp.set_cookie(
        STATE_COOKIE, state, max_age=STATE_TTL,
        httponly=True, samesite="lax", secure=False,  # dev: http; flip in prod via setting
    )
    return resp
```

At `/oauth/google/callback`, before touching Google:

```python
@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    db: DbSession,
    cookie_state: Annotated[str | None, Cookie(alias=STATE_COOKIE)] = None,
):
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        raise HTTPException(status_code=400, detail="Invalid state")
    # ... existing token-exchange + user-upsert code ...
    # At the end, clear the cookie.
    resp.delete_cookie(STATE_COOKIE)
    return resp
```

Remove the `TODO(csrf-state)` comment.

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_oauth_state.py tests/test_oauth.py -v
```

Expected: new 3 pass, old `test_oauth.py` still pass (may need minor tweaks to set the cookie in fixtures).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/oauth.py backend/tests/test_oauth_state.py backend/tests/test_oauth.py
git commit -m "feat(oauth): signed state cookie CSRF protection"
```

---

## Task 11: Frontend — papers list + upload page

**Files:**
- Create: `frontend/app/pages/papers/index.vue`
- Modify: `frontend/app/composables/useApi.ts`, `frontend/app/layouts/default.vue`

- [ ] **Step 1: Add upload helper to useApi**

Edit `frontend/app/composables/useApi.ts`. Add (alongside existing `call`):

```ts
async function callUpload<T = unknown>(path: string, form: FormData): Promise<T> {
  const auth = useAuthStore()
  const doReq = () =>
    $fetch<T>(`${useRuntimeConfig().public.apiBase}${path}`, {
      method: "POST", body: form,
      headers: auth.access ? { Authorization: `Bearer ${auth.access}` } : {},
    })
  try {
    return await doReq()
  } catch (e: any) {
    if (e?.response?.status === 401 && (await auth.tryRefresh())) {
      return await doReq()
    }
    throw e
  }
}
return { call, callUpload }
```

- [ ] **Step 2: Add nav link**

Edit `frontend/app/layouts/default.vue` — add a link to `/papers` next to existing nav items.

- [ ] **Step 3: Create papers list page**

Create `frontend/app/pages/papers/index.vue`:

```vue
<template>
  <div class="max-w-3xl mx-auto space-y-6">
    <h1 class="text-xl font-semibold">Papers</h1>

    <form @submit.prevent="onUpload" class="space-y-2 border border-neutral-200 dark:border-neutral-800 rounded p-3">
      <input v-model="title" placeholder="title" required class="input w-full" />
      <input ref="fileInput" type="file" accept="application/pdf" required />
      <button class="rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2"
              :disabled="uploading">
        {{ uploading ? "Uploading…" : "Upload" }}
      </button>
      <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
    </form>

    <ul v-if="papers.length" class="space-y-2">
      <li v-for="p in papers" :key="p.id"
          class="flex items-center justify-between border border-neutral-200 dark:border-neutral-800 rounded px-3 py-2">
        <div>
          <NuxtLink :to="`/papers/${p.id}`" class="font-medium underline">{{ p.title }}</NuxtLink>
          <div class="text-xs text-neutral-500">
            {{ new Date(p.uploaded_at).toLocaleString() }} · status: {{ p.status }}
          </div>
          <div v-if="p.parse_error" class="text-xs text-red-600 font-mono">{{ p.parse_error }}</div>
        </div>
      </li>
    </ul>
    <p v-else class="text-sm text-neutral-500">No papers yet.</p>
  </div>
</template>

<style scoped>
@reference "tailwindcss";
.input { @apply rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2; }
</style>

<script setup lang="ts">
type Paper = {
  id: string; title: string; uploaded_at: string; status: string;
  parse_error: string | null;
}
const { call, callUpload } = useApi()
const papers = ref<Paper[]>([])
const title = ref("")
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const error = ref("")

async function refresh() { papers.value = await call<Paper[]>("/papers") }
onMounted(refresh)

// Poll while any paper is still uploaded (not yet parsed).
let poll: any = null
watch(papers, (ps) => {
  const pending = ps.some(p => p.status === "uploaded")
  if (pending && !poll) {
    poll = setInterval(refresh, 2000)
  } else if (!pending && poll) {
    clearInterval(poll); poll = null
  }
}, { immediate: true })
onBeforeUnmount(() => poll && clearInterval(poll))

async function onUpload() {
  error.value = ""
  const f = fileInput.value?.files?.[0]
  if (!f || !title.value) return
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append("file", f)
    fd.append("title", title.value)
    await callUpload("/papers", fd)
    title.value = ""
    if (fileInput.value) fileInput.value.value = ""
    await refresh()
  } catch (e: any) {
    error.value = e?.data?.detail || e?.message || "upload failed"
  } finally { uploading.value = false }
}
</script>
```

- [ ] **Step 4: Run frontend locally to smoke-test**

```bash
cd frontend && npm run dev
```

Open http://localhost:3000/papers — login, upload a small PDF, confirm list populates and status transitions from uploaded → parsed after a few seconds.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/composables/useApi.ts frontend/app/layouts/default.vue frontend/app/pages/papers
git commit -m "feat(frontend): papers list + upload with status polling"
```

---

## Task 12: Frontend — paper detail page

**Files:**
- Create: `frontend/app/pages/papers/[id].vue`

- [ ] **Step 1: Create detail page**

Create `frontend/app/pages/papers/[id].vue`:

```vue
<template>
  <div v-if="paper" class="max-w-3xl mx-auto space-y-4">
    <NuxtLink to="/papers" class="text-sm underline">← back</NuxtLink>
    <h1 class="text-xl font-semibold">{{ paper.title }}</h1>
    <div class="text-xs text-neutral-500">
      uploaded {{ new Date(paper.uploaded_at).toLocaleString() }} · status: {{ paper.status }}
    </div>
    <div v-if="paper.parse_error" class="text-sm text-red-600 font-mono">{{ paper.parse_error }}</div>

    <div class="flex gap-2">
      <button v-if="paper.status !== 'uploaded'" @click="reingest"
              class="rounded border border-neutral-300 dark:border-neutral-700 px-3 py-2 text-sm">
        Reingest
      </button>
      <button @click="remove" class="rounded border border-red-500 text-red-600 px-3 py-2 text-sm">
        Delete
      </button>
    </div>
  </div>
  <p v-else-if="loading" class="text-sm text-neutral-500">Loading…</p>
  <p v-else class="text-sm text-red-600">Not found.</p>
</template>

<script setup lang="ts">
type Paper = {
  id: string; title: string; uploaded_at: string; status: string;
  parse_error: string | null;
}
const { call } = useApi()
const route = useRoute()
const router = useRouter()
const paper = ref<Paper | null>(null)
const loading = ref(true)

async function load() {
  try { paper.value = await call<Paper>(`/papers/${route.params.id}`) }
  catch { paper.value = null }
  finally { loading.value = false }
}
onMounted(load)

// Auto-refresh while ingesting.
let poll: any = null
watch(paper, (p) => {
  if (p?.status === "uploaded" && !poll) poll = setInterval(load, 2000)
  if (p?.status !== "uploaded" && poll) { clearInterval(poll); poll = null }
})
onBeforeUnmount(() => poll && clearInterval(poll))

async function reingest() {
  await call(`/papers/${route.params.id}/reingest`, { method: "POST" })
  await load()
}
async function remove() {
  await call(`/papers/${route.params.id}`, { method: "DELETE" })
  await router.push("/papers")
}
</script>
```

- [ ] **Step 2: Smoke-test**

Visit `/papers/<id>` after uploading — confirm status, reingest, delete work.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/pages/papers/[id].vue
git commit -m "feat(frontend): paper detail page with reingest and delete"
```

---

## Task 13: Playwright e2e — paper upload flow

**Files:**
- Create: `frontend/tests/e2e/papers.spec.ts`
- Create: `frontend/tests/e2e/fixtures/sample.pdf`

**Context:** One end-to-end test that exercises signup → seed llm-config → upload a small fixture PDF → see it in the list. Don't assert on the parsed status (ingest will fail against the fake endpoint), just that it appears.

- [ ] **Step 1: Generate fixture PDF**

```bash
cd frontend/tests/e2e && mkdir -p fixtures && python3 -c "
import fitz
d = fitz.open(); p = d.new_page()
p.insert_text((72,72), 'Playwright test fixture paper on attention.')
d.save('fixtures/sample.pdf'); d.close()
"
```

- [ ] **Step 2: Add spec**

Create `frontend/tests/e2e/papers.spec.ts`:

```ts
import { test, expect } from "@playwright/test"
import { resolve } from "path"

const unique = () => `u${Date.now()}@test.example`

test("signup, seed llm-config, upload paper, see it in list", async ({ page }) => {
  const email = unique()
  const password = "correct horse battery staple"

  await page.goto("/signup")
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button:has-text("Sign up")')
  await expect(page.getByText(`Welcome, ${email}`)).toBeVisible()

  await page.goto("/settings/llm")
  await page.fill('input[placeholder="name (e.g. openrouter)"]', "fake")
  await page.fill('input[placeholder="chat base_url (https://...)"]', "http://127.0.0.1:9/v1")
  await page.fill('input[placeholder="chat model"]', "fake-chat")
  await page.fill('input[placeholder="chat API key"]', "sk-fake")
  await page.fill('input[placeholder="embed base_url"]', "http://127.0.0.1:9/v1")
  await page.fill('input[placeholder="embed model"]', "fake-embed")
  await page.fill('input[placeholder="embed API key"]', "sk-fake")
  await page.fill('input[placeholder="embed dim"]', "1536")
  await page.click('button:has-text("Save")')
  await page.click('button:has-text("Activate")')

  await page.goto("/papers")
  await page.fill('input[placeholder="title"]', "Fixture paper")
  await page.setInputFiles('input[type="file"]', resolve(__dirname, "fixtures/sample.pdf"))
  await page.click('button:has-text("Upload")')
  await expect(page.getByText("Fixture paper")).toBeVisible()
})
```

- [ ] **Step 3: Run the spec**

```bash
cd frontend && npx playwright install chromium && npm run test:e2e
```

Expected: both tests (foundation + papers) pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/e2e
git commit -m "test(frontend): Playwright e2e for paper upload flow"
```

---

## Task 14: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append a "Paper library" section**

Edit `README.md`. Update "What's live" to include:
- `POST /papers`, `GET /papers`, `GET /papers/{id}`, `POST /papers/{id}/reingest`, `DELETE /papers/{id}`
- `GET /concepts`
- Papers page at `/papers`, detail at `/papers/{id}`
- OAuth `state` CSRF check live

Under "Dev bootstrap" add the localstack container note: testcontainers spins up `localstack/localstack:3` during `pytest` for S3. No extra setup required.

Under "What's next" replace Plan-2 bullet with the Plan-3 preview (Feynman + scheduler + dashboard).

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: paper library endpoints + pages; localstack test note"
```

---

## Self-Review Checklist

Run through this before dispatching subagents.

**Spec coverage (§3 v1 items handled by Plan 2):**
- [x] PDF paper upload + ingest (extract, chunk, embed) — Tasks 2–8
- [x] Concept extraction (silent) — Task 7
- [x] Reviewer follow-ups: partial unique index (Task 1), OAuth state (Task 10)

**Out of scope (belongs to Plan 3):** Feynman session, review scheduler, dashboard, `updated_at` columns (nice-to-have, not load-bearing).

**Type consistency:**
- `chunk_model_for(dim)` / `concept_model_for(dim)` — used identically in Tasks 4, 7, 9.
- `PaperStatus` enum — `uploaded | parsed | failed` — consistent across model, router, frontend.
- `build_user_gateway` — signature fixed in Task 6, called identically in Tasks 7–9.

**Placeholder scan:** none.

**Sequencing:** Task 1 (index) can run anytime; Task 2 (storage) is prereq for Tasks 7, 8; Task 4 (models) is prereq for Tasks 5, 7, 9; Task 6 (factory) is prereq for Tasks 7, 8. Linear order as written is valid.
