# syifa — PhD study companion

Monorepo: `backend/` (FastAPI) + `frontend/` (Nuxt 4).

The goal of this app is to help a PhD candidate understand, retain, and connect material from research papers via AI-driven Feynman teach-back sessions, a hybrid concept map, and spaced review.

Design and implementation plans live under `docs/superpowers/`:
- Spec: `docs/superpowers/specs/2026-04-23-phd-study-companion-design.md`
- Plan 1 (foundation): `docs/superpowers/plans/2026-04-23-foundation.md`
- Plan 2 (paper library): `docs/superpowers/plans/2026-04-24-paper-library.md`
- Plan 3 (Feynman engine): `docs/superpowers/plans/2026-04-27-feynman-engine.md`

## Dev bootstrap

### 1. Start Postgres

```bash
docker compose up -d db
```

### 2. Backend

```bash
cd backend
cp .env.example .env
# fill in JWT_SECRET (any 32+ char string), FERNET_KEY (see below), Google creds (optional)

python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

alembic upgrade head
uvicorn app.main:app --reload   # http://localhost:8000
```

Generate a Fernet key for `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Frontend (new terminal)

```bash
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

## Tests

```bash
# backend (async pytest + testcontainers; spins up Postgres + localstack S3)
cd backend && source .venv/bin/activate && pytest -v

# frontend end-to-end (needs backend running + localstack S3 reachable)
cd frontend && npm run test:e2e
```

Backend tests use `testcontainers` to start ephemeral `pgvector/pgvector:pg16` and `localstack/localstack:3` containers; no manual setup beyond a running Docker daemon.

## Repo layout

```
syifa/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI factory + /health
│   │   ├── config.py            Settings (pydantic-settings, lru_cache)
│   │   ├── db.py                async engine + session dep + dispose_engine
│   │   ├── deps.py              DbSession, CurrentUser
│   │   ├── security.py          bcrypt (SHA-256 pre-hash), JWT, Fernet
│   │   ├── models/              User, OAuthAccount, LLMConfig, Paper, per-dim PaperChunk/Concept, ConceptEdge, FeynmanSession
│   │   ├── schemas/             Pydantic I/O models
│   │   ├── routers/             auth, oauth (Google + state CSRF), llm_config, papers, concepts, feynman
│   │   └── services/            llm_gateway, user_llm (factory), storage (S3), pdf_ingest, ingest (pipeline), sse, feynman
│   ├── alembic/                 migrations
│   └── tests/
├── frontend/                    Nuxt 4 (srcDir=app/)
│   ├── app/
│   │   ├── pages/               index, login, signup, settings/llm, papers (list + [id]), feynman/[sid], auth/google/callback
│   │   ├── stores/auth.ts       Pinia auth store
│   │   ├── composables/         useApi (call + callUpload), useStream (fetch+ReadableStream SSE)
│   │   ├── middleware/auth.global.ts
│   │   └── assets/css/main.css  Tailwind v4
│   └── tests/e2e/               foundation + papers + feynman
├── docs/superpowers/            spec + plans
└── docker-compose.yml           Postgres 16 + pgvector for local dev
```

## What's live

### Plan 1 (foundation)
- Email/password signup + login + refresh with JWT access + refresh tokens.
- Google OAuth (login URL + callback, `email_verified` enforced, upstream errors mapped to 4xx/5xx, signed `state` cookie for CSRF).
- `/auth/me` protected route + reusable `current_user` dependency with uniform 401.
- `LLMConfig` CRUD endpoints (create, list, activate, delete) with Fernet-encrypted API keys at rest. Postgres-level partial unique index enforces one active config per user.
- `POST /llm-config/:id/test` — pings chat + embed endpoints and reports per-leg `ok` or `error: <msg>`.
- Frontend: login, signup, Google callback, LLM settings page (add/activate/delete/test).

### Plan 2 (paper library)
- `POST /papers` (multipart) — upload PDF; stores blob to S3-compatible store, enqueues background ingest.
- `GET /papers`, `GET /papers/:id`, `POST /papers/:id/reingest`, `DELETE /papers/:id`.
- Ingest pipeline: pymupdf extract → token-bounded chunk → LLM embed → per-dim `paper_chunk_<dim>` rows → concept extraction (strict-JSON LLM call) → concept embed → cosine-similarity edge proposals (`concept_edge`).
- `GET /concepts` — list a user's concepts scoped to their active `embed_dim`.
- Frontend: `/papers` list + upload form (status polling), `/papers/:id` detail with reingest + delete.

### Plan 3 (Feynman engine)
- `POST /feynman/start` — picks a target concept (paper-scoped if `paper_id` given, else any of user's), seeds transcript with curious-student system prompt.
- `GET /feynman/:sid` — owner-scoped session detail.
- `POST /feynman/:sid/message` — appends user turn, streams the model reply over SSE (`text/event-stream`), persists assistant turn on completion. Frontend uses `fetch` + `ReadableStream` (so it can send the bearer token) instead of `EventSource`.
- `POST /feynman/:sid/end` — grades the transcript via a JSON-mode LLM call, persists `quality_score` + `ended_at`, idempotent.
- Frontend: `/feynman/[sid]` chat page with streaming buffer + end button + score display. "Teach me back" button on `/papers/:id` (visible when `parsed && concepts_count > 0`) starts a fresh session and routes to it.
- Plan 2 reviewer carries: `embed_dim` constrained to `Literal[768, 1024, 1536]`; switching dim mid-data returns 409; concept idempotency across reingest (case-insensitive name match, merges `source_paper_ids`); `DELETE /papers/:id` prunes orphan concepts and edges; PDF upload size cap (`PAPER_MAX_BYTES`, default 50 MB) + `%PDF-` magic-byte check; OAuth state cookie `Secure` flag now driven by `cookie_secure` setting; `PaperOut` exposes `chunks_count` + `concepts_count`.

## What's next

- **Plan 4 (scheduler + dashboard):** SM-2 review queue, `/review/due` endpoint, scheduled Feynman sessions, dashboard with concept-count + quality-score trend chart.
