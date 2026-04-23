# PhD Study Companion — Design Spec

**Date:** 2026-04-23
**Status:** Draft, awaiting user review
**Author:** seratusjuta (with Claude)

## 1. Problem

PhD work requires continuous self-directed study of research papers. Four pain points drive this project:

1. **Understanding** — new concepts in papers don't click on first read.
2. **Retention** — material learned this week is forgotten next week.
3. **Connection** — new ideas don't link to prior knowledge.
4. **Progress** — no sense of moving forward; feeling lost in the material.

Target user: a PhD candidate (self, initially; SaaS-shippable later) whose field is not yet fixed. Field-general tool; depth comes from AI reasoning, not domain-specific rendering.

## 2. Solution Summary

A web app where the user uploads research papers and engages in daily AI-driven **Feynman teach-back** sessions. The app extracts concepts automatically, schedules reviews via a spaced-repetition algorithm (SM-2), and visualizes progress via concept-graph growth and Feynman explanation quality over time.

Core learning stack (decided during brainstorming):
- **Core loop:** Feynman teach-back (AI plays curious student, user explains; drives understanding + retention).
- **Support:** Concept map (hybrid — AI proposes edges, user curates) for surfacing connections.
- **Atoms only:** Sparse flashcards for names/formulas/constants — not for concepts.
- **Progress signals:** Concept-map growth + Feynman quality-score trend.

## 3. Scope

### v1 (MVP)
- Auth (email/password + Google OAuth)
- LLM endpoint configuration (OpenAI-compatible; supports OpenRouter, vLLM, llama.cpp, Ollama, official APIs)
- PDF paper upload + ingest (extract, chunk, embed)
- Concept extraction (silent — populates DB, no map UI yet)
- Fresh Feynman session (right after upload)
- Scheduled Feynman session (SM-2 review queue)
- Dashboard: concept count + Feynman quality-score trend chart

### Out of v1 (later)
- Concept map visualization UI
- Hybrid edge-curation UI (accept/reject AI proposals)
- Atom flashcards UI and review
- OCR for scanned PDFs
- Mobile companion
- Sharing / teams

## 4. Architecture

```
┌─────────────────────┐        ┌──────────────────────────┐
│ Nuxt (SSR + SPA)    │ HTTPS  │ FastAPI                  │
│  - auth pages       │◄──────►│  - /auth   /papers       │
│  - PDF reader       │  JWT   │  - /feynman (SSE stream) │
│  - Feynman chat UI  │        │  - /review /concepts     │
│  - concept map view │        │  - /llm-config           │
│  - dashboard        │        └──────────┬───────────────┘
└─────────────────────┘                   │
                                          ▼
         ┌────────────────────────┬──────────────────┬────────────────┐
         │ Postgres + pgvector    │ S3-compat store  │ LLM endpoint   │
         │  users, papers, cards, │  PDF blobs       │  (user config) │
         │  sessions, concepts,   │                  │                │
         │  edges, embeddings     │                  │                │
         └────────────────────────┴──────────────────┴────────────────┘
```

### Units
Each unit has a single purpose and a clear interface; each can be understood and tested independently.

1. **Frontend (Nuxt, latest)** — UI, auth token management, SSE consumption.
2. **API layer (FastAPI routers)** — thin HTTP surface, request/response validation (Pydantic).
3. **PDF ingest service** — extract text, chunk, embed, extract concepts.
4. **Feynman engine** — build session prompt from paper chunks + run chat loop.
5. **Review scheduler** — SM-2 variant; pick what's due.
6. **Concept service** — extract candidate concepts, propose edges via embedding similarity.
7. **LLM gateway** — single abstraction over any OpenAI-compatible endpoint; handles retry, streaming, key decryption.
8. **Storage layer** — Postgres via SQLAlchemy 2.x async, S3 via boto3.

### Tech stack
- **Frontend:** Nuxt (latest), Vue 3, Pinia, Tailwind.
- **Backend:** FastAPI, Python 3.12, SQLAlchemy 2.x async, Alembic migrations.
- **DB:** Postgres 16 with `pgvector` extension.
- **Blob store:** S3-compatible (AWS S3, MinIO, or Supabase Storage).
- **Auth:** JWT (access + refresh); `authlib` for Google OAuth2; `passlib[bcrypt]` for passwords.
- **LLM client:** `openai` Python SDK (configurable `base_url` covers OpenAI-compatible providers).
- **PDF:** `pymupdf` for extraction.
- **Background jobs:** FastAPI `BackgroundTasks` for v1; upgrade path to `arq` or Celery if jobs grow.
- **Testing:** pytest + testcontainers (Postgres, localstack S3) on backend; Vitest + Playwright on frontend.

## 5. Data Model

```
user
  id, email (unique), pw_hash NULLABLE, created_at
  -- pw_hash NULL when user registered only via OAuth

oauth_account
  id, user_id, provider (google|...),
  provider_sub, email, created_at
  UNIQUE(provider, provider_sub)

llm_config                           -- per user; one marked active
  id, user_id, name,
  chat_base_url, chat_api_key_enc, chat_model,
  embed_base_url, embed_api_key_enc, embed_model,
  embed_dim int,                     -- dimension of the embedding model
                                     -- (e.g. 768, 1024, 1536); used to
                                     -- validate stored vectors
  is_active, created_at
  -- chat and embedding endpoints are separately configurable because
  -- some OpenAI-compatible servers (llama.cpp, certain vLLM deploys)
  -- ship only a chat endpoint; user may point embeddings elsewhere.
  -- Keys Fernet-encrypted at rest; master key from env FERNET_KEY.

paper
  id, user_id, title, authors, uploaded_at,
  s3_key, text_hash, status (uploaded | parsed | failed),
  parse_error NULLABLE

paper_chunk                          -- for retrieval + Feynman context
  id, paper_id, ord, text, tokens,
  embedding vector   -- pgvector; dim set by llm_config.embed_dim
                    -- (see note on storage strategy below)             -- pgvector

concept                              -- nodes of concept map
  id, user_id, name, summary,
  source_paper_ids int[],
  stage (new | learning | fluent | teach),
  embedding vector   -- pgvector; dim set by llm_config.embed_dim
                    -- (see note on storage strategy below)

concept_edge                         -- hybrid: AI-proposed, user-curated
  id, user_id, src_id, dst_id, relation,
  status (proposed | accepted | rejected), confidence

feynman_session
  id, user_id, paper_id NULLABLE, target_concept_id,
  kind (fresh | scheduled),
  started_at, ended_at NULLABLE,
  quality_score numeric NULLABLE,    -- AI-rated, 0..1, set on end
  transcript jsonb                   -- [{role, content, ts}]

review_item                          -- SM-2 queue
  id, user_id, concept_id,
  ease, interval_days, due_at,
  last_session_id, last_score

atom_card                            -- sparse flashcards (v1 silent; UI later)
  id, user_id, concept_id, front, back,
  ease, interval_days, due_at
```

### Notes
- **Embedding storage strategy:** pgvector requires a fixed dimension per column, but different users may choose different embedding models. Strategy: create one table per common dimension (`paper_chunk_768`, `paper_chunk_1024`, `paper_chunk_1536`) and dispatch by `llm_config.embed_dim`. A user who switches embedding model must reindex their corpus (a one-shot job that re-embeds all chunks and concepts).
- `paper_chunk.embedding` powers Feynman retrieval and concept similarity.
- `concept.embedding` powers edge proposal (cosine similarity).
- `api_key_enc` is encrypted at rest with a symmetric key supplied via environment (`FERNET_KEY`).
- `transcript` stores the full Feynman chat. `quality_score` is computed by a separate grading LLM call when the user ends the session.

## 6. Data Flows

### A. Paper upload + ingest
1. User drags PDF; frontend `POST /papers` (multipart).
2. Backend uploads to S3, inserts `paper(status=uploaded)`.
3. Backend enqueues ingest job (BackgroundTasks).
4. Job:
   - `pymupdf` extracts text.
   - Chunk to ~800 tokens with ~100 overlap.
   - Call LLM gateway `/embeddings` per chunk; insert `paper_chunk` rows.
   - Call LLM with prompt "list key concepts + short summaries".
   - Upsert `concept` rows; embed each; cosine-query existing concepts; insert `concept_edge(status=proposed)` for top-k matches above threshold.
   - Set `paper.status=parsed`.
5. Frontend notified via SSE (or polling in v1).

### B. Fresh Feynman (right after upload)
1. User clicks "teach me back" on a parsed paper.
2. `POST /feynman/start {paper_id, kind=fresh}` — backend selects highest-weight concept for the paper.
3. System prompt: "You are a curious student. The user will explain {concept}. Ask naive why/how questions until you find a gap. Do not give the answer."
4. Backend streams SSE; frontend renders chat.
5. User ends session via button.
6. Backend:
   - Sends transcript to grading LLM → `quality_score` (0..1).
   - Upserts `review_item` (SM-2 schedules next `due_at`).
   - Updates `concept.stage` if score trend crosses thresholds.

### C. Scheduled review (daily)
1. User opens app; frontend `GET /review/due`.
2. For each due `review_item`, start Feynman session with `kind=scheduled` targeting that concept.
3. Same loop as flow B; `quality_score` feeds SM-2 to set a new `due_at`.

### D. LLM gateway call (used by all above)
1. Caller invokes `llm_gateway.chat(messages, stream=True)` or `.embed(texts)`.
2. Gateway loads user's active `llm_config`, decrypts key.
3. Constructs `openai.AsyncClient(base_url=cfg.base_url, api_key=key)`.
4. Streams chunks to caller.
5. Retry policy: exponential backoff ×3 on 429 / 5xx / timeout.

## 7. Error Handling

### Ingest
- PDF unparseable (scanned image, encrypted, corrupt) → `paper.status=failed`, error stored in `parse_error`; UI shows failure with a "retry (with OCR, planned)" affordance.
- Embedding API error → 3 retries with exponential backoff; on persistent failure, chunks are saved without embedding and concept extraction is deferred (user can retry from UI).

### LLM gateway
- 429 rate-limit → exponential backoff ×3.
- Bad config (invalid `base_url`, dead endpoint) → surface the raw error on the settings page.
- Stream timeout → emit SSE `error` event; preserve partial transcript.
- Key decryption failure → force user to re-enter API key in settings.

### Feynman session
- User closes tab mid-session → transcript is persisted on every message; no `quality_score` until user explicitly ends. UI offers "resume session".
- User marks a turn "not helpful" → stored as negative signal in session metadata; that session is excluded from scheduling updates.

### Auth
- Expired JWT → frontend transparently refreshes via refresh token; if refresh fails, redirect to login.
- Google OAuth `sub` mismatch with an existing email → reject the implicit link and direct the user to link accounts explicitly via settings.

### Data
- S3 unavailable → upload fails loudly; user retries.
- DB constraint violation (duplicate email) → `409 Conflict` with a clear message.

## 8. Testing

- **Backend unit:** pytest. LLM gateway mocked via record/replay. SM-2 scheduler is a pure function — exhaustive tests. Concept-edge proposal deterministic given fixed embeddings.
- **Backend integration:** testcontainers (Postgres + pgvector, localstack S3). Real ingest on a small fixture PDF.
- **Frontend:** Vitest for components (Nuxt test utils). Playwright for end-to-end (upload → fresh Feynman → end → scheduled review next day, with time mocked).
- **LLM contract:** smoke test against a real cheap endpoint (e.g. OpenRouter `mistral-7b`) in CI, allowed to fail without blocking.

## 9. Open Questions / Future Work

- **OCR** for scanned PDFs (v2). Candidates: Tesseract, or an LLM with vision.
- **Concept map UI:** force-directed graph (d3-force or Cytoscape.js) vs hierarchical. Decide when v2 starts.
- **Atom card extraction strategy:** heuristic (regex for formulas + named-entity for names) vs LLM-only. Decide when v2 starts.
- **Offline / local-first mode:** not in v1; revisit if users want air-gapped work.
- **Paper deduplication** across a user's library (DOI / text-hash based). Not in v1 but schema allows it via `text_hash`.
