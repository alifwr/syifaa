# Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the foundation of the PhD Study Companion: a user can sign up with email/password or Google, log in, configure their LLM endpoint (chat + embedding), and press "test" to verify the endpoint works.

**Architecture:** Monorepo with `backend/` (FastAPI + SQLAlchemy async + Postgres + pgvector) and `frontend/` (Nuxt latest + Tailwind). Auth issues JWT access + refresh tokens. Google OAuth via `authlib`. LLM API keys encrypted at rest with Fernet. LLM calls go through a single gateway module using the `openai` SDK with a configurable `base_url`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, Alembic, Postgres 16 + pgvector, `passlib[bcrypt]`, `pyjwt`, `authlib`, `cryptography` (Fernet), `openai` SDK, `pymupdf` (later plans), `pytest` + `httpx` + `testcontainers`; Nuxt latest, Vue 3, Pinia, Tailwind, Vitest, Playwright.

---

## Self-Review Checklist (from spec §3 MVP — Foundation slice)

- [x] Password signup + login
- [x] Google OAuth
- [x] LLM config (chat + embed endpoints, encrypted keys)
- [x] Test-connection endpoint
- [ ] Paper upload / ingest — **out of this plan** (Plan 2)
- [ ] Feynman / review / dashboard — **out of this plan** (Plan 3)

---

## File Structure

```
syifa/
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI app factory
│   │   ├── config.py              # Settings via pydantic-settings
│   │   ├── db.py                  # Async engine + session
│   │   ├── security.py            # bcrypt, JWT, Fernet
│   │   ├── deps.py                # FastAPI dependencies
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # Declarative base
│   │   │   ├── user.py
│   │   │   ├── oauth_account.py
│   │   │   └── llm_config.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   └── llm_config.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── oauth.py
│   │   │   └── llm_config.py
│   │   └── services/
│   │       ├── __init__.py
│   │       └── llm_gateway.py
│   └── tests/
│       ├── conftest.py
│       ├── test_auth.py
│       ├── test_oauth.py
│       ├── test_llm_config.py
│       └── test_llm_gateway.py
├── frontend/
│   ├── package.json
│   ├── nuxt.config.ts
│   ├── tailwind.config.ts
│   ├── app.vue
│   ├── layouts/default.vue
│   ├── pages/
│   │   ├── index.vue
│   │   ├── login.vue
│   │   ├── signup.vue
│   │   └── settings/llm.vue
│   ├── composables/
│   │   ├── useAuth.ts
│   │   └── useApi.ts
│   ├── middleware/
│   │   └── auth.global.ts
│   ├── stores/
│   │   └── auth.ts
│   └── tests/
│       └── e2e/
│           └── foundation.spec.ts
└── docker-compose.yml           # Postgres + pgvector for dev
```

---

## Task 1: Repo scaffold + docker-compose for Postgres

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/` (empty tree)
- Create: `frontend/` (empty tree)
- Create: `.gitignore`

- [ ] **Step 1: Write `docker-compose.yml` for Postgres + pgvector**

```yaml
# docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16
    restart: unless-stopped
    environment:
      POSTGRES_USER: syifa
      POSTGRES_PASSWORD: syifa_dev
      POSTGRES_DB: syifa
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes:
  pgdata:
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
# python
__pycache__/
*.pyc
.venv/
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/

# node
node_modules/
.nuxt/
.output/
dist/
.env
.env.*
!.env.example

# editor / os
.DS_Store
.vscode/
.idea/
```

- [ ] **Step 3: Bring Postgres up**

Run: `docker compose up -d db`
Expected: `Container ... Started`. Verify: `docker compose exec db psql -U syifa -d syifa -c 'SELECT version();'` returns PostgreSQL 16.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .gitignore
git commit -m "chore: add docker-compose for Postgres + pgvector"
```

---

## Task 2: Backend scaffold — pyproject, app factory, health endpoint

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py` (empty)
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`
- Create: `backend/.env.example`

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "syifa-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "sqlalchemy[asyncio]>=2.0",
  "asyncpg>=0.29",
  "alembic>=1.13",
  "pgvector>=0.3",
  "passlib[bcrypt]>=1.7",
  "pyjwt>=2.9",
  "authlib>=1.3",
  "httpx>=0.27",
  "cryptography>=43",
  "openai>=1.50",
  "pymupdf>=1.24",
  "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
  "pytest-cov>=5",
  "ruff>=0.6",
  "mypy>=1.11",
  "testcontainers[postgres]>=4.8",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Write `backend/.env.example`**

```env
DATABASE_URL=postgresql+asyncpg://syifa:syifa_dev@localhost:5432/syifa
JWT_SECRET=change-me-in-prod-make-it-long-and-random
JWT_ACCESS_TTL_MIN=30
JWT_REFRESH_TTL_DAYS=30
FERNET_KEY=generate-with-cryptography-fernet-generate-key
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/google/callback
FRONTEND_ORIGIN=http://localhost:3000
```

- [ ] **Step 3: Install deps**

Run: `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'`
Expected: installs complete; `pip list | grep fastapi` shows FastAPI.

- [ ] **Step 4: Write the failing test for the health endpoint**

```python
# backend/tests/test_health.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app

@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

async def test_health_returns_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd backend && pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 6: Write `backend/app/config.py`**

```python
# backend/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    jwt_secret: str
    jwt_access_ttl_min: int = 30
    jwt_refresh_ttl_days: int = 30
    fernet_key: str
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:3000/auth/google/callback"
    frontend_origin: str = "http://localhost:3000"

def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 7: Write `backend/app/main.py`**

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings

def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="syifa")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app

app = create_app()
```

- [ ] **Step 8: Write `backend/tests/conftest.py`**

```python
# backend/tests/conftest.py
import os
# Ensure env vars exist for Settings() during unit tests that don't hit DB.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-xxxxxxx")
os.environ.setdefault("FERNET_KEY", "0123456789abcdef0123456789abcdef0123456789AB=")
```

Note: the placeholder `FERNET_KEY` above is not a valid Fernet key; tests that actually encrypt will generate one in-test (see Task 10).

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && pytest tests/test_health.py -v`
Expected: PASS — 1 passed.

- [ ] **Step 10: Commit**

```bash
git add backend/
git commit -m "feat(backend): scaffold FastAPI app with /health and config"
```

---

## Task 3: Database engine + session dependency

**Files:**
- Create: `backend/app/db.py`
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/base.py`
- Create: `backend/app/deps.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_db.py`

- [ ] **Step 1: Write `backend/app/models/base.py`**

```python
# backend/app/models/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

- [ ] **Step 2: Write `backend/app/db.py`**

```python
# backend/app/db.py
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)
from app.config import get_settings

_engine: AsyncEngine | None = None
_maker: async_sessionmaker[AsyncSession] | None = None

def get_engine() -> AsyncEngine:
    global _engine, _maker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(s.database_url, pool_pre_ping=True)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine

def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _maker is not None
    return _maker

async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as sess:
        yield sess
```

- [ ] **Step 3: Write `backend/app/deps.py`**

```python
# backend/app/deps.py
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session

DbSession = Annotated[AsyncSession, Depends(get_session)]
```

- [ ] **Step 4: Update `backend/tests/conftest.py` to spin up Postgres via testcontainers**

```python
# backend/tests/conftest.py
import os
import pytest
from testcontainers.postgres import PostgresContainer

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-xxxxxxx")
os.environ.setdefault("FERNET_KEY", "placeholder-overridden-per-test")

@pytest.fixture(scope="session")
def pg_url():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        raw = pg.get_connection_url()                     # postgresql+psycopg2://...
        url = raw.replace("+psycopg2", "+asyncpg")
        os.environ["DATABASE_URL"] = url
        yield url

@pytest.fixture(autouse=True)
def _require_pg(pg_url):
    # Every test gets DATABASE_URL pointing at the container.
    yield
```

- [ ] **Step 5: Write the failing test for the engine**

```python
# backend/tests/test_db.py
import pytest
from sqlalchemy import text
from app.db import get_engine

@pytest.mark.asyncio
async def test_engine_can_connect():
    eng = get_engine()
    async with eng.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
```

- [ ] **Step 6: Run test**

Run: `cd backend && pytest tests/test_db.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db.py backend/app/models/ backend/app/deps.py backend/tests/conftest.py backend/tests/test_db.py
git commit -m "feat(backend): async SQLAlchemy engine + session dep"
```

---

## Task 4: Alembic setup + first migration (users, oauth_account, llm_config)

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/` (empty dir)
- Create: `backend/app/models/user.py`
- Create: `backend/app/models/oauth_account.py`
- Create: `backend/app/models/llm_config.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Init Alembic**

Run: `cd backend && alembic init -t async alembic`
Expected: creates `alembic.ini`, `alembic/env.py`, `alembic/versions/`.

- [ ] **Step 2: Edit `backend/alembic.ini`** — change `sqlalchemy.url` line to empty (we'll set from env):

```ini
sqlalchemy.url =
```

- [ ] **Step 3: Replace `backend/alembic/env.py`**

```python
# backend/alembic/env.py
import asyncio
from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from app.config import get_settings
from app.models import Base           # populated in Step 6
import app.models                      # noqa: F401 — import side-effect registers tables

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Write `backend/app/models/user.py`**

```python
# backend/app/models/user.py
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class User(Base):
    __tablename__ = "user"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    pw_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 5: Write `backend/app/models/oauth_account.py`**

```python
# backend/app/models/oauth_account.py
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, String, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class OAuthAccount(Base):
    __tablename__ = "oauth_account"
    __table_args__ = (UniqueConstraint("provider", "provider_sub"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_sub: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 6: Write `backend/app/models/llm_config.py`**

```python
# backend/app/models/llm_config.py
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, String, Integer, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class LLMConfig(Base):
    __tablename__ = "llm_config"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))

    chat_base_url: Mapped[str] = mapped_column(String(500))
    chat_api_key_enc: Mapped[str] = mapped_column(Text)
    chat_model: Mapped[str] = mapped_column(String(200))

    embed_base_url: Mapped[str] = mapped_column(String(500))
    embed_api_key_enc: Mapped[str] = mapped_column(Text)
    embed_model: Mapped[str] = mapped_column(String(200))
    embed_dim: Mapped[int] = mapped_column(Integer)

    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 7: Write `backend/app/models/__init__.py`**

```python
# backend/app/models/__init__.py
from app.models.base import Base
from app.models.user import User
from app.models.oauth_account import OAuthAccount
from app.models.llm_config import LLMConfig

__all__ = ["Base", "User", "OAuthAccount", "LLMConfig"]
```

- [ ] **Step 8: Generate migration**

Run: `cd backend && source .venv/bin/activate && alembic revision --autogenerate -m "initial schema"`
Expected: creates `backend/alembic/versions/<hash>_initial_schema.py` with `op.create_table('user', ...)`, etc.

- [ ] **Step 9: Apply migration**

Run: `cd backend && alembic upgrade head`
Expected: `Running upgrade  -> <hash>, initial schema`.

Verify: `docker compose exec db psql -U syifa -d syifa -c '\dt'` shows `user`, `oauth_account`, `llm_config`, `alembic_version`.

- [ ] **Step 10: Write the failing test that asserts the tables exist**

```python
# backend/tests/test_migrations.py
import pytest
from sqlalchemy import text
from app.db import get_engine

@pytest.mark.asyncio
async def test_core_tables_exist_after_migration():
    # The conftest `pg_url` fixture has set DATABASE_URL; the test runner
    # can apply migrations via alembic in a separate step before tests run.
    # For now, verify our models create tables directly.
    from app.models import Base
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with eng.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        ))).all()
        names = {r[0] for r in rows}
    assert {"user", "oauth_account", "llm_config"}.issubset(names)
```

- [ ] **Step 11: Run test**

Run: `cd backend && pytest tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add backend/alembic.ini backend/alembic/ backend/app/models/ backend/tests/test_migrations.py
git commit -m "feat(backend): initial schema (user, oauth_account, llm_config)"
```

---

## Task 5: Password hashing + JWT utilities

**Files:**
- Create: `backend/app/security.py`
- Create: `backend/tests/test_security.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_security.py
import pytest
from datetime import timedelta
from app.security import hash_password, verify_password, make_jwt, decode_jwt, InvalidToken

def test_hash_and_verify_password_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False

def test_hash_password_not_plaintext():
    h = hash_password("secret")
    assert "secret" not in h

def test_jwt_roundtrip():
    tok = make_jwt({"sub": "u1", "kind": "access"}, ttl=timedelta(minutes=5))
    payload = decode_jwt(tok)
    assert payload["sub"] == "u1"
    assert payload["kind"] == "access"

def test_jwt_invalid_signature_rejected():
    tok = make_jwt({"sub": "u1"}, ttl=timedelta(minutes=5))
    tampered = tok[:-2] + ("AB" if tok[-2:] != "AB" else "CD")
    with pytest.raises(InvalidToken):
        decode_jwt(tampered)

def test_jwt_expired_rejected():
    tok = make_jwt({"sub": "u1"}, ttl=timedelta(seconds=-1))
    with pytest.raises(InvalidToken):
        decode_jwt(tok)
```

- [ ] **Step 2: Run test — expect fail**

Run: `cd backend && pytest tests/test_security.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.security'`.

- [ ] **Step 3: Write `backend/app/security.py`**

```python
# backend/app/security.py
from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
from passlib.context import CryptContext
from app.config import get_settings

class InvalidToken(Exception):
    pass

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return _pwd.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)

def make_jwt(claims: dict[str, Any], ttl: timedelta) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {**claims, "iat": int(now.timestamp()), "exp": int((now + ttl).timestamp())}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")

def decode_jwt(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise InvalidToken(str(e)) from e
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd backend && pytest tests/test_security.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/security.py backend/tests/test_security.py
git commit -m "feat(backend): bcrypt + JWT helpers"
```

---

## Task 6: Signup + login endpoints

**Files:**
- Create: `backend/app/schemas/__init__.py` (empty)
- Create: `backend/app/schemas/auth.py`
- Create: `backend/app/routers/__init__.py` (empty)
- Create: `backend/app/routers/auth.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_auth.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_auth.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models import Base
from app.db import get_engine

@pytest.fixture
async def client():
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

async def test_signup_creates_user(client):
    r = await client.post("/auth/signup", json={
        "email": "a@b.com", "password": "correct horse battery staple",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "a@b.com"
    assert "id" in body
    assert "password" not in body and "pw_hash" not in body

async def test_signup_duplicate_email_returns_409(client):
    payload = {"email": "dup@b.com", "password": "pw_long_enough_xx"}
    await client.post("/auth/signup", json=payload)
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 409

async def test_signup_short_password_rejected(client):
    r = await client.post("/auth/signup", json={"email": "x@y.com", "password": "short"})
    assert r.status_code == 422

async def test_login_success_returns_tokens(client):
    await client.post("/auth/signup", json={"email": "l@b.com", "password": "pw_long_enough_xx"})
    r = await client.post("/auth/login", json={"email": "l@b.com", "password": "pw_long_enough_xx"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body and "refresh_token" in body
    assert body["token_type"] == "bearer"

async def test_login_wrong_password_returns_401(client):
    await client.post("/auth/signup", json={"email": "w@b.com", "password": "pw_long_enough_xx"})
    r = await client.post("/auth/login", json={"email": "w@b.com", "password": "wrong_password_xx"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run — expect fail**

Run: `cd backend && pytest tests/test_auth.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `backend/app/schemas/auth.py`**

```python
# backend/app/schemas/auth.py
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field

class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)

class UserOut(BaseModel):
    id: UUID
    email: EmailStr

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshIn(BaseModel):
    refresh_token: str
```

- [ ] **Step 4: Write `backend/app/routers/auth.py`**

```python
# backend/app/routers/auth.py
from datetime import timedelta
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.deps import DbSession
from app.models import User
from app.schemas.auth import SignupIn, LoginIn, UserOut, TokenPair, RefreshIn
from app.security import hash_password, verify_password, make_jwt, decode_jwt, InvalidToken
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

def _issue_pair(user_id: str) -> TokenPair:
    s = get_settings()
    access = make_jwt({"sub": user_id, "kind": "access"}, timedelta(minutes=s.jwt_access_ttl_min))
    refresh = make_jwt({"sub": user_id, "kind": "refresh"}, timedelta(days=s.jwt_refresh_ttl_days))
    return TokenPair(access_token=access, refresh_token=refresh)

@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(data: SignupIn, db: DbSession) -> UserOut:
    user = User(email=data.email, pw_hash=hash_password(data.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.refresh(user)
    return UserOut(id=user.id, email=user.email)

@router.post("/login", response_model=TokenPair)
async def login(data: LoginIn, db: DbSession) -> TokenPair:
    row = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    if row is None or row.pw_hash is None or not verify_password(data.password, row.pw_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _issue_pair(str(row.id))

@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshIn) -> TokenPair:
    try:
        payload = decode_jwt(data.refresh_token)
    except InvalidToken:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("kind") != "refresh":
        raise HTTPException(status_code=401, detail="Wrong token kind")
    return _issue_pair(payload["sub"])
```

- [ ] **Step 5: Wire router into `backend/app/main.py`**

Replace the file with:

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.routers import auth as auth_router

def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="syifa")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(auth_router.router)
    return app

app = create_app()
```

- [ ] **Step 6: Run tests — expect pass**

Run: `cd backend && pytest tests/test_auth.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/ backend/app/schemas/ backend/app/main.py backend/tests/test_auth.py
git commit -m "feat(backend): signup, login, refresh endpoints"
```

---

## Task 7: Current-user dependency + protected route

**Files:**
- Modify: `backend/app/deps.py`
- Modify: `backend/app/routers/auth.py` (add `/auth/me`)
- Modify: `backend/tests/test_auth.py`

- [ ] **Step 1: Append a failing test for `/auth/me`**

Add to `backend/tests/test_auth.py`:

```python
async def test_me_requires_auth(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401

async def test_me_returns_current_user(client):
    await client.post("/auth/signup", json={"email": "me@b.com", "password": "pw_long_enough_xx"})
    tok = (await client.post("/auth/login", json={
        "email": "me@b.com", "password": "pw_long_enough_xx"
    })).json()["access_token"]
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["email"] == "me@b.com"
```

- [ ] **Step 2: Run — expect fail**

Run: `cd backend && pytest tests/test_auth.py::test_me_requires_auth tests/test_auth.py::test_me_returns_current_user -v`
Expected: FAIL — 404 (route missing).

- [ ] **Step 3: Update `backend/app/deps.py`**

```python
# backend/app/deps.py
from typing import Annotated
from uuid import UUID
from fastapi import Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.models import User
from app.security import decode_jwt, InvalidToken

DbSession = Annotated[AsyncSession, Depends(get_session)]

async def current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt(token)
    except InvalidToken:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("kind") != "access":
        raise HTTPException(status_code=401, detail="Wrong token kind")
    user = (await db.execute(select(User).where(User.id == UUID(payload["sub"])))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

CurrentUser = Annotated[User, Depends(current_user)]
```

- [ ] **Step 4: Add `/auth/me` to `backend/app/routers/auth.py`**

Append to the router:

```python
from app.deps import CurrentUser

@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id, email=user.email)
```

- [ ] **Step 5: Run tests — expect pass**

Run: `cd backend && pytest tests/test_auth.py -v`
Expected: PASS — 7 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/deps.py backend/app/routers/auth.py backend/tests/test_auth.py
git commit -m "feat(backend): /auth/me with current_user dependency"
```

---

## Task 8: Google OAuth

**Files:**
- Create: `backend/app/routers/oauth.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_oauth.py`

**Design:** We do NOT embed `authlib`'s full redirect dance in tests (that needs a real Google). Instead, we split responsibilities: (a) `/auth/google/login` returns the upstream authorization URL; (b) `/auth/google/callback` accepts `?code=...`, and internally uses an injectable `fetch_userinfo(code)` function — which in production calls Google, and in tests is monkeypatched.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_oauth.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models import Base
from app.db import get_engine
from app.routers import oauth as oauth_mod

@pytest.fixture
async def client(monkeypatch):
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

async def test_google_login_returns_authorization_url(client):
    r = await client.get("/auth/google/login")
    assert r.status_code == 200
    assert "authorization_url" in r.json()
    url = r.json()["authorization_url"]
    assert "accounts.google.com" in url
    assert "client_id=" in url

async def test_google_callback_creates_user_and_issues_tokens(client, monkeypatch):
    async def fake(code: str):
        assert code == "FAKE-CODE"
        return {"sub": "google-sub-1", "email": "g@b.com"}
    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake)

    r = await client.get("/auth/google/callback", params={"code": "FAKE-CODE"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body and "refresh_token" in body

async def test_google_callback_reuses_existing_oauth_link(client, monkeypatch):
    async def fake(code: str):
        return {"sub": "google-sub-2", "email": "g2@b.com"}
    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake)
    r1 = await client.get("/auth/google/callback", params={"code": "C1"})
    r2 = await client.get("/auth/google/callback", params={"code": "C2"})
    assert r1.status_code == 200 and r2.status_code == 200

async def test_google_callback_rejects_sub_mismatch_same_email(client, monkeypatch):
    async def fake_a(code: str):
        return {"sub": "sub-A", "email": "shared@b.com"}
    async def fake_b(code: str):
        return {"sub": "sub-B", "email": "shared@b.com"}

    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake_a)
    r1 = await client.get("/auth/google/callback", params={"code": "X"})
    assert r1.status_code == 200

    monkeypatch.setattr(oauth_mod, "fetch_userinfo", fake_b)
    r2 = await client.get("/auth/google/callback", params={"code": "Y"})
    assert r2.status_code == 409
```

- [ ] **Step 2: Run — expect fail**

Run: `cd backend && pytest tests/test_oauth.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/routers/oauth.py`**

```python
# backend/app/routers/oauth.py
from datetime import timedelta
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from app.config import get_settings
from app.deps import DbSession
from app.models import User, OAuthAccount
from app.schemas.auth import TokenPair
from app.security import make_jwt

router = APIRouter(prefix="/auth/google", tags=["oauth"])

GOOGLE_AUTHZ = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

async def fetch_userinfo(code: str) -> dict:
    """Exchange authorization code for userinfo. Overridden in tests."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as h:
        tok = await h.post(GOOGLE_TOKEN, data={
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": s.google_redirect_uri,
            "grant_type": "authorization_code",
        })
        tok.raise_for_status()
        access = tok.json()["access_token"]
        info = await h.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"})
        info.raise_for_status()
        return info.json()  # contains "sub", "email", ...

@router.get("/login")
async def login_start():
    s = get_settings()
    qs = urlencode({
        "client_id": s.google_client_id,
        "redirect_uri": s.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
    })
    return {"authorization_url": f"{GOOGLE_AUTHZ}?{qs}"}

@router.get("/callback", response_model=TokenPair)
async def callback(code: str, db: DbSession) -> TokenPair:
    info = await fetch_userinfo(code)
    sub = info["sub"]
    email = info["email"]

    oa = (await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == "google",
            OAuthAccount.provider_sub == sub,
        )
    )).scalar_one_or_none()

    if oa is not None:
        user_id = oa.user_id
    else:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None:
            # Email collision with a different Google sub or a password-only account.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use; link Google from settings.",
            )
        user = User(email=email, pw_hash=None)
        db.add(user)
        await db.flush()
        db.add(OAuthAccount(user_id=user.id, provider="google", provider_sub=sub, email=email))
        await db.commit()
        user_id = user.id

    s = get_settings()
    access = make_jwt({"sub": str(user_id), "kind": "access"}, timedelta(minutes=s.jwt_access_ttl_min))
    refresh = make_jwt({"sub": str(user_id), "kind": "refresh"}, timedelta(days=s.jwt_refresh_ttl_days))
    return TokenPair(access_token=access, refresh_token=refresh)
```

- [ ] **Step 4: Wire router in `backend/app/main.py`**

Add next to `auth_router.router`:

```python
from app.routers import oauth as oauth_router
# ...
app.include_router(oauth_router.router)
```

- [ ] **Step 5: Set env for tests**

Add to `backend/tests/conftest.py` (top, before imports that need them):

```python
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:3000/auth/google/callback")
```

- [ ] **Step 6: Run tests — expect pass**

Run: `cd backend && pytest tests/test_oauth.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/oauth.py backend/app/main.py backend/tests/test_oauth.py backend/tests/conftest.py
git commit -m "feat(backend): Google OAuth login + callback"
```

---

## Task 9: Fernet encryption for API keys

**Files:**
- Modify: `backend/app/security.py` (append)
- Create: `backend/tests/test_fernet.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_fernet.py
import os
import pytest
from cryptography.fernet import Fernet
from app.security import encrypt_secret, decrypt_secret

@pytest.fixture(autouse=True)
def real_fernet_key(monkeypatch):
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    # Force reload of cached settings, if any. (get_settings() creates fresh each call.)
    yield

def test_encrypt_then_decrypt_roundtrip():
    tok = encrypt_secret("sk-live-1234567890")
    assert tok != "sk-live-1234567890"
    assert decrypt_secret(tok) == "sk-live-1234567890"

def test_encrypt_is_nondeterministic():
    # Fernet uses random IV; same plaintext gives different ciphertext.
    a = encrypt_secret("same")
    b = encrypt_secret("same")
    assert a != b

def test_decrypt_rejects_bogus():
    with pytest.raises(Exception):
        decrypt_secret("not-a-real-fernet-token")
```

- [ ] **Step 2: Run — expect fail**

Run: `cd backend && pytest tests/test_fernet.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Append to `backend/app/security.py`**

```python
# backend/app/security.py — append at bottom
from cryptography.fernet import Fernet

def _fernet() -> Fernet:
    return Fernet(get_settings().fernet_key.encode())

def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()

def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd backend && pytest tests/test_fernet.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/security.py backend/tests/test_fernet.py
git commit -m "feat(backend): Fernet encrypt/decrypt for stored secrets"
```

---

## Task 10: LLM gateway (chat + embed wrappers)

**Files:**
- Create: `backend/app/services/__init__.py` (empty)
- Create: `backend/app/services/llm_gateway.py`
- Create: `backend/tests/test_llm_gateway.py`

**Design:** `LLMGateway` holds decrypted creds for one user's active config. It exposes `.ping_chat()`, `.ping_embed()`, `.chat(messages, stream)`, `.embed(texts)`. We use `openai.AsyncOpenAI(base_url=..., api_key=...)` with separate clients for chat and embed. Tests mock the client class so we do not hit the network.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_llm_gateway.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.llm_gateway import LLMGateway, LLMConnectionError

def _cfg(**kw):
    return {
        "chat_base_url": "http://chat/v1",
        "chat_api_key": "k1",
        "chat_model": "gpt-mock",
        "embed_base_url": "http://embed/v1",
        "embed_api_key": "k2",
        "embed_model": "emb-mock",
        "embed_dim": 8,
        **kw,
    }

@pytest.mark.asyncio
async def test_ping_chat_success():
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=MagicMock(
        choices=[MagicMock(message=MagicMock(content="pong"))]
    ))
    with patch("app.services.llm_gateway.AsyncOpenAI", return_value=fake):
        gw = LLMGateway(**_cfg())
        assert await gw.ping_chat() is True

@pytest.mark.asyncio
async def test_ping_chat_failure_raises():
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(side_effect=RuntimeError("401 unauthorized"))
    with patch("app.services.llm_gateway.AsyncOpenAI", return_value=fake):
        gw = LLMGateway(**_cfg())
        with pytest.raises(LLMConnectionError) as exc:
            await gw.ping_chat()
        assert "401" in str(exc.value)

@pytest.mark.asyncio
async def test_ping_embed_validates_dim():
    fake = MagicMock()
    fake.embeddings.create = AsyncMock(return_value=MagicMock(
        data=[MagicMock(embedding=[0.1] * 8)]
    ))
    with patch("app.services.llm_gateway.AsyncOpenAI", return_value=fake):
        gw = LLMGateway(**_cfg(embed_dim=8))
        assert await gw.ping_embed() is True

@pytest.mark.asyncio
async def test_ping_embed_dim_mismatch_raises():
    fake = MagicMock()
    fake.embeddings.create = AsyncMock(return_value=MagicMock(
        data=[MagicMock(embedding=[0.1] * 4)]
    ))
    with patch("app.services.llm_gateway.AsyncOpenAI", return_value=fake):
        gw = LLMGateway(**_cfg(embed_dim=8))
        with pytest.raises(LLMConnectionError) as exc:
            await gw.ping_embed()
        assert "dim" in str(exc.value).lower()
```

- [ ] **Step 2: Run — expect fail**

Run: `cd backend && pytest tests/test_llm_gateway.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/services/llm_gateway.py`**

```python
# backend/app/services/llm_gateway.py
from openai import AsyncOpenAI

class LLMConnectionError(Exception):
    pass

class LLMGateway:
    def __init__(
        self,
        chat_base_url: str, chat_api_key: str, chat_model: str,
        embed_base_url: str, embed_api_key: str, embed_model: str,
        embed_dim: int,
    ):
        self._chat = AsyncOpenAI(base_url=chat_base_url, api_key=chat_api_key)
        self._embed = AsyncOpenAI(base_url=embed_base_url, api_key=embed_api_key)
        self._chat_model = chat_model
        self._embed_model = embed_model
        self._embed_dim = embed_dim

    async def ping_chat(self) -> bool:
        try:
            await self._chat.chat.completions.create(
                model=self._chat_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
        except Exception as e:
            raise LLMConnectionError(f"chat ping failed: {e}") from e
        return True

    async def ping_embed(self) -> bool:
        try:
            r = await self._embed.embeddings.create(model=self._embed_model, input=["ping"])
        except Exception as e:
            raise LLMConnectionError(f"embed ping failed: {e}") from e
        got = len(r.data[0].embedding)
        if got != self._embed_dim:
            raise LLMConnectionError(
                f"embed dim mismatch: config says {self._embed_dim}, endpoint returned {got}"
            )
        return True

    async def chat(self, messages: list[dict], stream: bool = False):
        try:
            return await self._chat.chat.completions.create(
                model=self._chat_model, messages=messages, stream=stream,
            )
        except Exception as e:
            raise LLMConnectionError(f"chat failed: {e}") from e

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = await self._embed.embeddings.create(model=self._embed_model, input=texts)
        except Exception as e:
            raise LLMConnectionError(f"embed failed: {e}") from e
        return [d.embedding for d in r.data]
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd backend && pytest tests/test_llm_gateway.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ backend/tests/test_llm_gateway.py
git commit -m "feat(backend): LLM gateway wrapping openai SDK"
```

---

## Task 11: LLM config CRUD endpoints + test-connection

**Files:**
- Create: `backend/app/schemas/llm_config.py`
- Create: `backend/app/routers/llm_config.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_llm_config.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_llm_config.py
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models import Base
from app.db import get_engine

@pytest.fixture
async def client(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

async def _auth_header(client):
    await client.post("/auth/signup", json={"email": "u@b.com", "password": "pw_long_enough_xx"})
    tok = (await client.post("/auth/login", json={
        "email": "u@b.com", "password": "pw_long_enough_xx"
    })).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}

_PAYLOAD = {
    "name": "openrouter",
    "chat_base_url": "https://openrouter.ai/api/v1",
    "chat_api_key": "sk-or-xyz",
    "chat_model": "anthropic/claude-3.5-sonnet",
    "embed_base_url": "https://api.openai.com/v1",
    "embed_api_key": "sk-openai-xyz",
    "embed_model": "text-embedding-3-small",
    "embed_dim": 1536,
}

async def test_create_llm_config_requires_auth(client):
    r = await client.post("/llm-config", json=_PAYLOAD)
    assert r.status_code == 401

async def test_create_and_list_llm_config(client):
    h = await _auth_header(client)
    r = await client.post("/llm-config", json=_PAYLOAD, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "openrouter"
    assert "chat_api_key" not in body  # secrets never leak
    assert "chat_api_key_enc" not in body

    r2 = await client.get("/llm-config", headers=h)
    assert r2.status_code == 200
    assert len(r2.json()) == 1

async def test_activate_llm_config(client):
    h = await _auth_header(client)
    cid = (await client.post("/llm-config", json=_PAYLOAD, headers=h)).json()["id"]
    r = await client.post(f"/llm-config/{cid}/activate", headers=h)
    assert r.status_code == 200
    r2 = await client.get("/llm-config", headers=h)
    active = [c for c in r2.json() if c["is_active"]]
    assert len(active) == 1 and active[0]["id"] == cid

async def test_test_connection_success(client):
    h = await _auth_header(client)
    cid = (await client.post("/llm-config", json=_PAYLOAD, headers=h)).json()["id"]
    with patch("app.routers.llm_config.LLMGateway") as GW:
        inst = GW.return_value
        inst.ping_chat = AsyncMock(return_value=True)
        inst.ping_embed = AsyncMock(return_value=True)
        r = await client.post(f"/llm-config/{cid}/test", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body == {"chat": "ok", "embed": "ok"}

async def test_test_connection_chat_failure_reports_error(client):
    h = await _auth_header(client)
    cid = (await client.post("/llm-config", json=_PAYLOAD, headers=h)).json()["id"]
    with patch("app.routers.llm_config.LLMGateway") as GW:
        inst = GW.return_value
        from app.services.llm_gateway import LLMConnectionError
        inst.ping_chat = AsyncMock(side_effect=LLMConnectionError("401 unauthorized"))
        inst.ping_embed = AsyncMock(return_value=True)
        r = await client.post(f"/llm-config/{cid}/test", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["chat"].startswith("error:")
    assert body["embed"] == "ok"
```

- [ ] **Step 2: Run — expect fail**

Run: `cd backend && pytest tests/test_llm_config.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `backend/app/schemas/llm_config.py`**

```python
# backend/app/schemas/llm_config.py
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl

class LLMConfigIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    chat_base_url: HttpUrl
    chat_api_key: str = Field(min_length=1, max_length=500)
    chat_model: str = Field(min_length=1, max_length=200)
    embed_base_url: HttpUrl
    embed_api_key: str = Field(min_length=1, max_length=500)
    embed_model: str = Field(min_length=1, max_length=200)
    embed_dim: int = Field(ge=1, le=8192)

class LLMConfigOut(BaseModel):
    id: UUID
    name: str
    chat_base_url: str
    chat_model: str
    embed_base_url: str
    embed_model: str
    embed_dim: int
    is_active: bool

class TestConnectionOut(BaseModel):
    chat: str
    embed: str
```

- [ ] **Step 4: Write `backend/app/routers/llm_config.py`**

```python
# backend/app/routers/llm_config.py
from uuid import UUID
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update
from app.deps import DbSession, CurrentUser
from app.models import LLMConfig
from app.schemas.llm_config import LLMConfigIn, LLMConfigOut, TestConnectionOut
from app.security import encrypt_secret, decrypt_secret
from app.services.llm_gateway import LLMGateway, LLMConnectionError

router = APIRouter(prefix="/llm-config", tags=["llm-config"])

def _to_out(c: LLMConfig) -> LLMConfigOut:
    return LLMConfigOut(
        id=c.id, name=c.name,
        chat_base_url=c.chat_base_url, chat_model=c.chat_model,
        embed_base_url=c.embed_base_url, embed_model=c.embed_model,
        embed_dim=c.embed_dim, is_active=c.is_active,
    )

@router.post("", response_model=LLMConfigOut, status_code=status.HTTP_201_CREATED)
async def create(data: LLMConfigIn, user: CurrentUser, db: DbSession) -> LLMConfigOut:
    cfg = LLMConfig(
        user_id=user.id,
        name=data.name,
        chat_base_url=str(data.chat_base_url).rstrip("/"),
        chat_api_key_enc=encrypt_secret(data.chat_api_key),
        chat_model=data.chat_model,
        embed_base_url=str(data.embed_base_url).rstrip("/"),
        embed_api_key_enc=encrypt_secret(data.embed_api_key),
        embed_model=data.embed_model,
        embed_dim=data.embed_dim,
        is_active=False,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return _to_out(cfg)

@router.get("", response_model=list[LLMConfigOut])
async def list_(user: CurrentUser, db: DbSession) -> list[LLMConfigOut]:
    rows = (await db.execute(
        select(LLMConfig).where(LLMConfig.user_id == user.id).order_by(LLMConfig.created_at)
    )).scalars().all()
    return [_to_out(r) for r in rows]

@router.post("/{cid}/activate", response_model=LLMConfigOut)
async def activate(cid: UUID, user: CurrentUser, db: DbSession) -> LLMConfigOut:
    target = (await db.execute(
        select(LLMConfig).where(LLMConfig.id == cid, LLMConfig.user_id == user.id)
    )).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Config not found")
    await db.execute(
        update(LLMConfig).where(LLMConfig.user_id == user.id).values(is_active=False)
    )
    target.is_active = True
    await db.commit()
    await db.refresh(target)
    return _to_out(target)

@router.delete("/{cid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(cid: UUID, user: CurrentUser, db: DbSession) -> None:
    target = (await db.execute(
        select(LLMConfig).where(LLMConfig.id == cid, LLMConfig.user_id == user.id)
    )).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Config not found")
    await db.delete(target)
    await db.commit()

@router.post("/{cid}/test", response_model=TestConnectionOut)
async def test_connection(cid: UUID, user: CurrentUser, db: DbSession) -> TestConnectionOut:
    cfg = (await db.execute(
        select(LLMConfig).where(LLMConfig.id == cid, LLMConfig.user_id == user.id)
    )).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=404, detail="Config not found")

    gw = LLMGateway(
        chat_base_url=cfg.chat_base_url,
        chat_api_key=decrypt_secret(cfg.chat_api_key_enc),
        chat_model=cfg.chat_model,
        embed_base_url=cfg.embed_base_url,
        embed_api_key=decrypt_secret(cfg.embed_api_key_enc),
        embed_model=cfg.embed_model,
        embed_dim=cfg.embed_dim,
    )

    async def _safe(coro) -> str:
        try:
            await coro
            return "ok"
        except LLMConnectionError as e:
            return f"error: {e}"

    return TestConnectionOut(
        chat=await _safe(gw.ping_chat()),
        embed=await _safe(gw.ping_embed()),
    )
```

- [ ] **Step 5: Wire router in `backend/app/main.py`**

Add:

```python
from app.routers import llm_config as llm_config_router
app.include_router(llm_config_router.router)
```

- [ ] **Step 6: Run tests — expect pass**

Run: `cd backend && pytest tests/test_llm_config.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 7: Run full backend suite**

Run: `cd backend && pytest -v`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/llm_config.py backend/app/routers/llm_config.py backend/app/main.py backend/tests/test_llm_config.py
git commit -m "feat(backend): LLM config CRUD + test-connection endpoint"
```

---

## Task 12: Frontend scaffold (Nuxt + Tailwind)

**Files:**
- Create: `frontend/package.json`, `frontend/nuxt.config.ts`, `frontend/tsconfig.json`
- Create: `frontend/app.vue`
- Create: `frontend/layouts/default.vue`
- Create: `frontend/pages/index.vue`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/assets/css/main.css`

- [ ] **Step 1: Init Nuxt project**

Run: `cd frontend && npx nuxi@latest init . --package-manager pnpm --no-git-init --force`
Expected: creates Nuxt project files in current dir.

- [ ] **Step 2: Install Tailwind v4 + Pinia**

Run: `cd frontend && pnpm add tailwindcss @tailwindcss/vite @pinia/nuxt pinia`
Expected: installed.

- [ ] **Step 3: Replace `frontend/nuxt.config.ts`**

```ts
// frontend/nuxt.config.ts
import tailwindcss from "@tailwindcss/vite"

export default defineNuxtConfig({
  compatibilityDate: "2026-04-01",
  devtools: { enabled: true },
  modules: ["@pinia/nuxt"],
  css: ["~/assets/css/main.css"],
  vite: { plugins: [tailwindcss()] },
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE ?? "http://localhost:8000",
    },
  },
})
```

- [ ] **Step 4: Write `frontend/assets/css/main.css`**

```css
@import "tailwindcss";

:root { color-scheme: light dark; }
body { @apply bg-white text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100; }
```

- [ ] **Step 5: Write `frontend/layouts/default.vue`**

```vue
<!-- frontend/layouts/default.vue -->
<template>
  <div class="min-h-screen flex flex-col">
    <header class="border-b border-neutral-200 dark:border-neutral-800 px-6 py-3 flex justify-between">
      <NuxtLink to="/" class="font-semibold">syifa</NuxtLink>
      <nav class="flex gap-4 text-sm">
        <NuxtLink to="/settings/llm">LLM</NuxtLink>
        <NuxtLink v-if="!auth.isLoggedIn" to="/login">Login</NuxtLink>
        <button v-else @click="auth.logout()" class="text-neutral-500 hover:underline">Logout</button>
      </nav>
    </header>
    <main class="flex-1 p-6"><slot /></main>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "~/stores/auth"
const auth = useAuthStore()
</script>
```

- [ ] **Step 6: Write `frontend/pages/index.vue`**

```vue
<!-- frontend/pages/index.vue -->
<template>
  <div class="space-y-4">
    <h1 class="text-2xl font-semibold">syifa — PhD study companion</h1>
    <p v-if="auth.isLoggedIn">Welcome, {{ auth.user?.email }}.</p>
    <p v-else>
      <NuxtLink to="/login" class="underline">Log in</NuxtLink> or
      <NuxtLink to="/signup" class="underline">sign up</NuxtLink> to get started.
    </p>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "~/stores/auth"
const auth = useAuthStore()
</script>
```

- [ ] **Step 7: Dev smoke test**

Run: `cd frontend && pnpm run dev`
Expected: Nuxt serves on `http://localhost:3000`. Open browser — home page renders "syifa — PhD study companion" and a login link. Stop with Ctrl-C.

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): scaffold Nuxt + Tailwind + Pinia"
```

---

## Task 13: Frontend auth store + API composable

**Files:**
- Create: `frontend/stores/auth.ts`
- Create: `frontend/composables/useApi.ts`
- Create: `frontend/middleware/auth.global.ts`

- [ ] **Step 1: Write `frontend/composables/useApi.ts`**

```ts
// frontend/composables/useApi.ts
import { useAuthStore } from "~/stores/auth"

export const useApi = () => {
  const config = useRuntimeConfig()
  const auth = useAuthStore()

  const call = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
    const headers = new Headers(init.headers || {})
    headers.set("Content-Type", "application/json")
    if (auth.access) headers.set("Authorization", `Bearer ${auth.access}`)

    const resp = await fetch(`${config.public.apiBase}${path}`, { ...init, headers })

    if (resp.status === 401 && auth.refresh) {
      const refreshed = await auth.tryRefresh()
      if (refreshed) {
        headers.set("Authorization", `Bearer ${auth.access}`)
        const retry = await fetch(`${config.public.apiBase}${path}`, { ...init, headers })
        return handle<T>(retry)
      }
      auth.clear()
    }
    return handle<T>(resp)
  }

  return { call }
}

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`${resp.status}: ${body}`)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}
```

- [ ] **Step 2: Write `frontend/stores/auth.ts`**

```ts
// frontend/stores/auth.ts
import { defineStore } from "pinia"

type User = { id: string; email: string }
type TokenPair = { access_token: string; refresh_token: string; token_type: string }

export const useAuthStore = defineStore("auth", {
  state: () => ({
    access: (import.meta.client ? localStorage.getItem("access") : null) as string | null,
    refresh: (import.meta.client ? localStorage.getItem("refresh") : null) as string | null,
    user: null as User | null,
  }),
  getters: {
    isLoggedIn: (s) => !!s.access,
  },
  actions: {
    _persist() {
      if (!import.meta.client) return
      if (this.access) localStorage.setItem("access", this.access)
      else localStorage.removeItem("access")
      if (this.refresh) localStorage.setItem("refresh", this.refresh)
      else localStorage.removeItem("refresh")
    },
    set(pair: TokenPair) {
      this.access = pair.access_token
      this.refresh = pair.refresh_token
      this._persist()
    },
    clear() {
      this.access = null
      this.refresh = null
      this.user = null
      this._persist()
    },
    async fetchMe() {
      const cfg = useRuntimeConfig()
      if (!this.access) return
      const r = await fetch(`${cfg.public.apiBase}/auth/me`, {
        headers: { Authorization: `Bearer ${this.access}` },
      })
      if (r.ok) this.user = (await r.json()) as User
      else this.clear()
    },
    async tryRefresh(): Promise<boolean> {
      if (!this.refresh) return false
      const cfg = useRuntimeConfig()
      const r = await fetch(`${cfg.public.apiBase}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: this.refresh }),
      })
      if (!r.ok) { this.clear(); return false }
      this.set(await r.json())
      return true
    },
    async logout() {
      this.clear()
      await navigateTo("/login")
    },
  },
})
```

- [ ] **Step 3: Write `frontend/middleware/auth.global.ts`**

```ts
// frontend/middleware/auth.global.ts
import { useAuthStore } from "~/stores/auth"

const PROTECTED = [/^\/settings/, /^\/papers/, /^\/review/, /^\/dashboard/]

export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuthStore()
  if (auth.access && !auth.user) await auth.fetchMe()
  if (PROTECTED.some((p) => p.test(to.path)) && !auth.isLoggedIn) {
    return navigateTo("/login")
  }
})
```

- [ ] **Step 4: Smoke test**

Run: `cd frontend && pnpm run dev`
Expected: app still loads at `/`. Visiting `/settings/llm` redirects to `/login` (once login page exists; for now it 404s — that's fine).

- [ ] **Step 5: Commit**

```bash
git add frontend/stores frontend/composables frontend/middleware
git commit -m "feat(frontend): auth store + api composable + route guard"
```

---

## Task 14: Login and signup pages

**Files:**
- Create: `frontend/pages/login.vue`
- Create: `frontend/pages/signup.vue`

- [ ] **Step 1: Write `frontend/pages/signup.vue`**

```vue
<!-- frontend/pages/signup.vue -->
<template>
  <div class="max-w-sm mx-auto space-y-4">
    <h1 class="text-xl font-semibold">Create account</h1>
    <form @submit.prevent="submit" class="space-y-3">
      <input v-model="email" type="email" placeholder="email" required
             class="w-full rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2" />
      <input v-model="password" type="password" placeholder="password (min 12 chars)" minlength="12" required
             class="w-full rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2" />
      <button class="w-full rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2">
        Sign up
      </button>
    </form>
    <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
    <p class="text-sm">
      Or <button class="underline" @click="google">continue with Google</button>.
    </p>
    <p class="text-sm">Already have an account? <NuxtLink to="/login" class="underline">Log in</NuxtLink>.</p>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "~/stores/auth"
const auth = useAuthStore()
const { call } = useApi()
const email = ref("")
const password = ref("")
const error = ref("")

async function submit() {
  error.value = ""
  try {
    await call("/auth/signup", { method: "POST", body: JSON.stringify({ email: email.value, password: password.value }) })
    const pair = await call<{ access_token: string; refresh_token: string; token_type: string }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email: email.value, password: password.value }) },
    )
    auth.set(pair)
    await auth.fetchMe()
    await navigateTo("/")
  } catch (e: any) {
    error.value = e.message
  }
}

async function google() {
  const cfg = useRuntimeConfig()
  const r = await fetch(`${cfg.public.apiBase}/auth/google/login`)
  const { authorization_url } = await r.json()
  window.location.href = authorization_url
}
</script>
```

- [ ] **Step 2: Write `frontend/pages/login.vue`**

```vue
<!-- frontend/pages/login.vue -->
<template>
  <div class="max-w-sm mx-auto space-y-4">
    <h1 class="text-xl font-semibold">Log in</h1>
    <form @submit.prevent="submit" class="space-y-3">
      <input v-model="email" type="email" placeholder="email" required
             class="w-full rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2" />
      <input v-model="password" type="password" placeholder="password" required
             class="w-full rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2" />
      <button class="w-full rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2">
        Log in
      </button>
    </form>
    <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
    <p class="text-sm">
      Or <button class="underline" @click="google">continue with Google</button>.
    </p>
    <p class="text-sm">No account? <NuxtLink to="/signup" class="underline">Sign up</NuxtLink>.</p>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "~/stores/auth"
const auth = useAuthStore()
const { call } = useApi()
const email = ref("")
const password = ref("")
const error = ref("")

async function submit() {
  error.value = ""
  try {
    const pair = await call<{ access_token: string; refresh_token: string; token_type: string }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email: email.value, password: password.value }) },
    )
    auth.set(pair)
    await auth.fetchMe()
    await navigateTo("/")
  } catch (e: any) {
    error.value = e.message
  }
}

async function google() {
  const cfg = useRuntimeConfig()
  const r = await fetch(`${cfg.public.apiBase}/auth/google/login`)
  const { authorization_url } = await r.json()
  window.location.href = authorization_url
}
</script>
```

- [ ] **Step 3: Smoke test**

Run backend: `cd backend && source .venv/bin/activate && uvicorn app.main:app --reload`
Run frontend (new terminal): `cd frontend && pnpm run dev`
Open `http://localhost:3000/signup`. Sign up with a dummy account. Expect redirect to `/` with "Welcome, <email>".

- [ ] **Step 4: Commit**

```bash
git add frontend/pages/login.vue frontend/pages/signup.vue
git commit -m "feat(frontend): signup + login pages"
```

---

## Task 15: Google OAuth callback page

**Files:**
- Create: `frontend/pages/auth/google/callback.vue`

- [ ] **Step 1: Write the callback page**

```vue
<!-- frontend/pages/auth/google/callback.vue -->
<template>
  <div class="max-w-sm mx-auto text-center py-16">
    <p v-if="!error">Signing you in…</p>
    <p v-else class="text-red-600 text-sm">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "~/stores/auth"
const auth = useAuthStore()
const route = useRoute()
const cfg = useRuntimeConfig()
const error = ref("")

onMounted(async () => {
  const code = route.query.code as string | undefined
  if (!code) { error.value = "Missing code"; return }
  try {
    const r = await fetch(`${cfg.public.apiBase}/auth/google/callback?code=${encodeURIComponent(code)}`)
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`)
    const pair = await r.json()
    auth.set(pair)
    await auth.fetchMe()
    await navigateTo("/")
  } catch (e: any) {
    error.value = e.message
  }
})
</script>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/pages/auth/google/callback.vue
git commit -m "feat(frontend): Google OAuth callback page"
```

Manual verification (requires real Google client ID/secret): follow `/auth/google/login` from signup page end-to-end. Skip for now if credentials aren't set.

---

## Task 16: LLM config settings page with test button

**Files:**
- Create: `frontend/pages/settings/llm.vue`

- [ ] **Step 1: Write the settings page**

```vue
<!-- frontend/pages/settings/llm.vue -->
<template>
  <div class="max-w-2xl mx-auto space-y-6">
    <h1 class="text-xl font-semibold">LLM configuration</h1>

    <section class="space-y-2">
      <h2 class="font-medium">Your configs</h2>
      <ul v-if="configs.length" class="space-y-2">
        <li v-for="c in configs" :key="c.id"
            class="flex items-center justify-between border border-neutral-200 dark:border-neutral-800 rounded px-3 py-2">
          <div>
            <div class="font-mono text-sm">{{ c.name }} <span v-if="c.is_active" class="text-green-600">(active)</span></div>
            <div class="text-xs text-neutral-500">chat: {{ c.chat_model }} · embed: {{ c.embed_model }} (dim {{ c.embed_dim }})</div>
          </div>
          <div class="flex gap-2">
            <button @click="activate(c.id)" :disabled="c.is_active"
                    class="text-sm underline disabled:opacity-40">Activate</button>
            <button @click="test(c.id)" class="text-sm underline">Test</button>
            <button @click="remove(c.id)" class="text-sm underline text-red-600">Delete</button>
          </div>
        </li>
      </ul>
      <p v-else class="text-sm text-neutral-500">No configs yet.</p>
      <p v-if="testResult" class="text-sm font-mono">{{ testResult }}</p>
    </section>

    <section class="space-y-3">
      <h2 class="font-medium">Add new config</h2>
      <form @submit.prevent="create" class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <input v-model="form.name" placeholder="name (e.g. openrouter)" required class="input" />
        <div />
        <input v-model="form.chat_base_url" placeholder="chat base_url (https://...)" required class="input" />
        <input v-model="form.chat_model" placeholder="chat model" required class="input" />
        <input v-model="form.chat_api_key" placeholder="chat API key" type="password" required class="input" />
        <div />
        <input v-model="form.embed_base_url" placeholder="embed base_url" required class="input" />
        <input v-model="form.embed_model" placeholder="embed model" required class="input" />
        <input v-model="form.embed_api_key" placeholder="embed API key" type="password" required class="input" />
        <input v-model.number="form.embed_dim" type="number" min="1" max="8192" placeholder="embed dim" required class="input" />
        <button class="col-span-full rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2">
          Save
        </button>
      </form>
      <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
    </section>
  </div>
</template>

<style scoped>
.input { @apply rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2; }
</style>

<script setup lang="ts">
type Cfg = {
  id: string; name: string; chat_model: string; embed_model: string;
  embed_dim: number; is_active: boolean;
  chat_base_url: string; embed_base_url: string;
}
const { call } = useApi()
const configs = ref<Cfg[]>([])
const error = ref("")
const testResult = ref("")

const form = reactive({
  name: "", chat_base_url: "", chat_api_key: "", chat_model: "",
  embed_base_url: "", embed_api_key: "", embed_model: "", embed_dim: 1536,
})

async function refresh() { configs.value = await call<Cfg[]>("/llm-config") }
onMounted(refresh)

async function create() {
  error.value = ""
  try {
    await call("/llm-config", { method: "POST", body: JSON.stringify(form) })
    Object.assign(form, {
      name: "", chat_base_url: "", chat_api_key: "", chat_model: "",
      embed_base_url: "", embed_api_key: "", embed_model: "", embed_dim: 1536,
    })
    await refresh()
  } catch (e: any) { error.value = e.message }
}

async function activate(id: string) { await call(`/llm-config/${id}/activate`, { method: "POST" }); await refresh() }
async function remove(id: string) { await call(`/llm-config/${id}`, { method: "DELETE" }); await refresh() }
async function test(id: string) {
  testResult.value = "testing…"
  const r = await call<{ chat: string; embed: string }>(`/llm-config/${id}/test`, { method: "POST" })
  testResult.value = `chat: ${r.chat} · embed: ${r.embed}`
}
</script>
```

- [ ] **Step 2: Smoke test end-to-end**

Backend running, frontend running. Steps:
1. Sign up / log in.
2. Go to `/settings/llm`.
3. Save a config (use a real OpenRouter or local vLLM endpoint).
4. Click "Test" — expect `chat: ok · embed: ok` (or error text surfaced clearly).
5. Click "Activate" — chosen config now marked `(active)`.

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/settings/llm.vue
git commit -m "feat(frontend): LLM config settings page with test button"
```

---

## Task 17: E2E Playwright test (signup → login → save config → test)

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/tests/e2e/foundation.spec.ts`
- Modify: `frontend/package.json` (add Playwright deps + script)

- [ ] **Step 1: Install Playwright**

Run: `cd frontend && pnpm add -D @playwright/test && pnpm exec playwright install chromium`
Expected: installed + browser downloaded.

- [ ] **Step 2: Write `frontend/playwright.config.ts`**

```ts
// frontend/playwright.config.ts
import { defineConfig } from "@playwright/test"
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: { baseURL: "http://localhost:3000", headless: true },
  webServer: {
    command: "pnpm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
```

- [ ] **Step 3: Write `frontend/tests/e2e/foundation.spec.ts`**

```ts
// frontend/tests/e2e/foundation.spec.ts
import { test, expect } from "@playwright/test"

const unique = () => `u${Date.now()}@test.example`

test("signup, save llm config, test connection surfaces a result", async ({ page }) => {
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

  await expect(page.getByText("fake", { exact: false })).toBeVisible()
  await page.click('button:has-text("Test")')
  // Endpoint is fake → expect the result line shows an error for chat and embed.
  await expect(page.locator("text=chat:")).toContainText(/(ok|error:)/)
  await expect(page.locator("text=embed:")).toContainText(/(ok|error:)/)
})
```

- [ ] **Step 4: Add script to `frontend/package.json`**

Ensure `scripts` contains:

```json
{
  "scripts": {
    "dev": "nuxt dev",
    "build": "nuxt build",
    "preview": "nuxt preview",
    "test:e2e": "playwright test"
  }
}
```

- [ ] **Step 5: Run Playwright (backend must be running)**

Terminal A: `cd backend && source .venv/bin/activate && uvicorn app.main:app`
Terminal B: `cd frontend && pnpm run test:e2e`
Expected: 1 test passes.

- [ ] **Step 6: Commit**

```bash
git add frontend/playwright.config.ts frontend/tests/ frontend/package.json frontend/pnpm-lock.yaml
git commit -m "test(frontend): Playwright e2e for foundation flow"
```

---

## Task 18: README + developer bootstrap

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# syifa — PhD study companion

Monorepo: `backend/` (FastAPI) + `frontend/` (Nuxt).

## Dev bootstrap

```bash
# 1. Postgres
docker compose up -d db

# 2. Backend
cd backend
cp .env.example .env                                    # fill JWT_SECRET, FERNET_KEY, Google creds
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload                            # :8000

# 3. Frontend (new terminal)
cd frontend
pnpm install
pnpm run dev                                             # :3000
```

## Generate a Fernet key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Tests

- Backend unit + integration: `cd backend && pytest`
- Frontend e2e: `cd frontend && pnpm run test:e2e` (requires backend running)

## Plans

Design and implementation plans live under `docs/superpowers/`.
- Spec: `docs/superpowers/specs/2026-04-23-phd-study-companion-design.md`
- Plan 1 (this one): `docs/superpowers/plans/2026-04-23-foundation.md`
- Plan 2 (paper library): to be written after Plan 1 ships.
- Plan 3 (Feynman + scheduler + dashboard): after Plan 2.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with dev bootstrap"
```

---

## Done criteria (Plan 1)

All of the following must hold before Plan 2 starts:

- `cd backend && pytest -v` — all green.
- `cd frontend && pnpm run test:e2e` — green, with backend running.
- Manual: signup, login, logout, Google OAuth callback (if credentials set), save LLM config, press Test — visible result line.
- Database holds three tables (`user`, `oauth_account`, `llm_config`) with correct columns.
- No plaintext API keys stored in DB — verify with: `docker compose exec db psql -U syifa -d syifa -c 'SELECT chat_api_key_enc FROM llm_config LIMIT 1;'` (Fernet ciphertext, starts with `gAAAA...`).

## Open risks & follow-ups

- **Migrations in tests:** The current test suite calls `Base.metadata.create_all` directly. When Plan 2 adds pgvector types, we should switch tests to running `alembic upgrade head` inside the container so tests exercise real migrations.
- **Google OAuth state/PKCE:** For v1 we skip CSRF `state` on the `/login` endpoint. Add before any public deployment.
- **Refresh-token rotation:** Current refresh endpoint issues a new pair without invalidating the old one. Rotation + a blocklist for revoked refresh tokens is a hardening task before production.
- **LLM test-endpoint cost:** `ping_chat` issues a real `max_tokens=1` call against the configured provider — cheap but not free. Document this on the settings page before public ship.
